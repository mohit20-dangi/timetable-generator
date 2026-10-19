"""What has to happen around a department-load import beyond writing its rows.

The load workbook says who teaches what, and nothing about how a lab's
batches share teachers - so a plain import leaves two things wrong:

  * Allotments drift. When a newer revision moves a teacher off a subject,
    the old teacher-subject link would stay (the importer only adds and
    updates), so the timetable keeps offering someone who no longer takes it.
  * Labs can't be scheduled. A lab with 3 batches and 1 teacher, left on the
    default 'independent' batch mode, reads as "all 3 batches may run at
    once" and demands 3 qualified teachers - generation is blocked.

plan_followups() works out the fix from the parsed workbook rows plus what's
already in the database, changing nothing (so the preview can show it);
apply_followups() carries it out inside the import's transaction.

What it will NOT do: delete anything the workbook doesn't define. A subject
or room added by hand stays, even if it's absent from the workbook.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models import LabBatch, LabRotationGroup, SectionSubject, Subject, TeacherSubject

IMPORT_SOURCE = "import"
ROTATION_REASON = "Set up by the department-load import so each lab runs with one batch at a time"


@dataclass
class FollowupPlan:
    stale_teacher_links: List[Tuple[str, str]] = field(default_factory=list)   # (teacher_id, subject_id)
    stale_section_links: List[Tuple[str, str]] = field(default_factory=list)   # (section_id, subject_id)
    rotations: List[Dict[str, Any]] = field(default_factory=list)              # LabRotationGroup fields
    sequential_subjects: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class CollegeFollowup:
    """Everything the import needs to remember about a converted workbook."""
    department_id: str
    plan: FollowupPlan
    soft_fields: Mapping[str, Mapping[str, Set[str]]]
    soft_batch_sections: Set[str]


def _preview(items: List[str], limit: int = 6) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def plan_followups(
    db: Session,
    rows: Mapping[str, List[Dict[str, Any]]],
    department_id: str,
    soft_fields: Mapping[str, Mapping[str, Set[str]]],
    soft_batch_sections: Set[str],
) -> FollowupPlan:
    plan = FollowupPlan()
    subject_rows = {str(r["id"]): r for r in rows.get("Subjects", [])}
    section_ids = {str(r["id"]) for r in rows.get("Sections", [])}
    unallotted = set(soft_fields.get("Subjects", {}))

    new_teachers: Dict[str, Set[str]] = {}
    for r in rows.get("TeacherSubjects", []):
        new_teachers.setdefault(str(r["subject_id"]), set()).add(str(r["teacher_id"]))
    new_subjects: Dict[str, Set[str]] = {}
    for r in rows.get("SectionSubjects", []):
        new_subjects.setdefault(str(r["section_id"]), set()).add(str(r["subject_id"]))

    # --- allotments follow the newest revision. A subject nobody is allotted
    # to yet is left alone: its links may have been added by hand.
    stale_labels: List[str] = []
    for subject_id in subject_rows:
        if subject_id in unallotted:
            continue
        for link in db.query(TeacherSubject).filter(TeacherSubject.subject_id == subject_id).all():
            if link.teacher_id not in new_teachers.get(subject_id, set()):
                plan.stale_teacher_links.append((link.teacher_id, subject_id))
                stale_labels.append(f"{link.teacher_id} from {subject_id}")
    if stale_labels:
        plan.notes.append(
            f"{len(stale_labels)} teacher allotment(s) are no longer in the workbook and are removed: "
            f"{_preview(stale_labels)}."
        )

    moved_labels: List[str] = []
    unlisted: List[str] = []
    for section_id in section_ids:
        for link in db.query(SectionSubject).filter(SectionSubject.section_id == section_id).all():
            if link.subject_id in new_subjects.get(section_id, set()):
                continue
            if link.subject_id in subject_rows:
                # The workbook still defines this subject, just not for this
                # class any more - it moved, so un-assign it here.
                plan.stale_section_links.append((section_id, link.subject_id))
                moved_labels.append(f"{link.subject_id} from {section_id}")
            else:
                unlisted.append(f"{link.subject_id} ({section_id})")
    if moved_labels:
        plan.notes.append(
            f"{len(moved_labels)} subject(s) are no longer listed for their class and are un-assigned: "
            f"{_preview(moved_labels)}."
        )
    if unlisted:
        plan.notes.append(
            f"Left in place (not in the workbook, so possibly added by hand): {_preview(unlisted)}."
        )

    # --- lab batches that share teachers
    batches_in_workbook: Dict[str, int] = {}
    for r in rows.get("LabBatches", []):
        batches_in_workbook[str(r["section_id"])] = batches_in_workbook.get(str(r["section_id"]), 0) + 1
    section_names = {str(r["id"]): r["name"] for r in rows.get("Sections", [])}
    year_names = {str(r["id"]): r["name"] for r in rows.get("AcademicYears", [])}
    year_of = {str(r["id"]): str(r["year_id"]) for r in rows.get("Sections", [])}

    rotated: List[str] = []
    sequenced: List[str] = []
    for section_id in sorted(section_ids):
        existing_batches = db.query(LabBatch).filter(LabBatch.section_id == section_id).count()
        batch_count = (
            existing_batches
            if section_id in soft_batch_sections and existing_batches
            else batches_in_workbook.get(section_id, existing_batches)
        )
        if batch_count < 2:
            continue

        def current_mode(subject_id: str) -> str:
            record = db.get(Subject, subject_id)
            return (record.batch_scheduling_mode if record else None) or "independent"

        labs = [
            subject_rows[s] for s in sorted(new_subjects.get(section_id, set()))
            if s in subject_rows and s not in unallotted
            and subject_rows[s].get("type") == "lab" and (subject_rows[s].get("weekly_hours") or 0) > 0
            and subject_rows[s].get("delivery_mode", "IN_PERSON") == "IN_PERSON"
        ]
        needy = [
            lab for lab in labs
            if len(new_teachers.get(str(lab["id"]), set())) < batch_count * max(1, int(lab.get("teachers_required") or 1)) and current_mode(str(lab["id"])) == "independent"
        ]
        if not needy:
            continue

        covered_by_rotation: Set[str] = set()
        existing_groups = db.query(LabRotationGroup).filter(
            LabRotationGroup.section_id == section_id, LabRotationGroup.is_active.is_(True)
        ).all()
        for group in existing_groups:
            covered_by_rotation.update(group.subject_ids or [])
        needy = [lab for lab in needy if str(lab["id"]) not in covered_by_rotation]
        if not needy:
            continue

        # Labs of one length can take turns: every round, each batch is on a
        # different lab, so each lab only ever has one batch at a time.
        by_length: Dict[int, List[Dict[str, Any]]] = {}
        for lab in labs:
            by_length.setdefault(int(lab.get("periods_per_session") or 1), []).append(lab)
        best = max(by_length.values(), key=len)
        rotating: Set[str] = set()
        if not existing_groups and len(best) >= batch_count:
            rotating = {str(lab["id"]) for lab in best}
            year_name = year_names.get(year_of.get(section_id, ""), "")
            plan.rotations.append({
                "id": f"rot_{section_id.lower()}", "department_id": department_id, "section_id": section_id,
                "name": f"{year_name} {section_names.get(section_id, section_id)} labs".strip(),
                "subject_ids": [str(lab["id"]) for lab in best],
            })
            rotated.append(f"{section_id} ({', '.join(str(lab['id']) for lab in best)})")
        for lab in needy:
            if str(lab["id"]) not in rotating and str(lab["id"]) not in plan.sequential_subjects:
                plan.sequential_subjects.append(str(lab["id"]))
                sequenced.append(str(lab["id"]))

    if rotated:
        plan.notes.append(
            "Labs rotate (each round every batch is on a different lab, so one teacher per lab is enough) for: "
            f"{_preview(rotated)}."
        )
    if sequenced:
        plan.notes.append(
            "Batches run one after another (not enough labs of the same length to rotate) for: "
            f"{_preview(sequenced)}."
        )
    return plan


def apply_followups(db: Session, followup: CollegeFollowup) -> None:
    plan = followup.plan
    db.flush()  # the import's own rows must be visible before the links around them are fixed
    for teacher_id, subject_id in plan.stale_teacher_links:
        db.query(TeacherSubject).filter(
            TeacherSubject.teacher_id == teacher_id, TeacherSubject.subject_id == subject_id
        ).delete(synchronize_session=False)
    for section_id, subject_id in plan.stale_section_links:
        db.query(SectionSubject).filter(
            SectionSubject.section_id == section_id, SectionSubject.subject_id == subject_id
        ).delete(synchronize_session=False)
    for fields in plan.rotations:
        existing = db.get(LabRotationGroup, fields["id"])
        if existing is not None and existing.source != IMPORT_SOURCE:
            continue  # a rotation an admin made by hand under this id is theirs
        record = existing or LabRotationGroup(id=fields["id"])
        record.department_id = fields["department_id"]
        record.section_id = fields["section_id"]
        record.name = fields["name"]
        record.subject_ids = fields["subject_ids"]
        record.day = None
        record.start_time = None
        record.end_time = None
        record.source = IMPORT_SOURCE
        record.raw_instruction = ROTATION_REASON
        record.is_active = True
        db.add(record)
    for subject_id in plan.sequential_subjects:
        subject = db.get(Subject, subject_id)
        if subject is not None and (subject.batch_scheduling_mode or "independent") == "independent":
            subject.batch_scheduling_mode = "sequential"
    db.flush()


def drop_soft_fields(rows: Dict[str, List[Dict[str, Any]]], db: Session, followup: CollegeFollowup) -> None:
    """Placeholder values the converter invented must not overwrite what an
    admin has since corrected: for a record that already exists, take those
    fields out of the row so the upsert leaves them alone. A brand-new
    record still gets its placeholder."""
    from app.models import AcademicYear, ElectiveGroup, Section, Teacher

    models = {
        "Subjects": Subject, "Sections": Section, "Teachers": Teacher, "AcademicYears": AcademicYear,
        "ElectiveGroups": ElectiveGroup,
    }
    for sheet_name, per_id in followup.soft_fields.items():
        model = models.get(sheet_name)
        if model is None:
            continue
        for row in rows.get(sheet_name, []):
            soft = per_id.get(str(row.get("id")))
            if soft and db.get(model, str(row["id"])) is not None:
                for name in soft:
                    row.pop(name, None)
    if followup.soft_batch_sections and "LabBatches" in rows:
        keep_existing = {
            section_id for section_id in followup.soft_batch_sections
            if db.query(LabBatch).filter(LabBatch.section_id == section_id).count()
        }
        rows["LabBatches"] = [r for r in rows["LabBatches"] if str(r["section_id"]) not in keep_existing]
