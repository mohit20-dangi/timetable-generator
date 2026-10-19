from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import (
    Subject, SubjectType, Equipment, SectionSubject, TeacherSubject, Prerequisite,
    ElectiveGroup, GeneratedEntry, TimetableRun, User,
)
from collections import defaultdict
from app.schemas import SubjectCreate, SubjectResponse
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import get_scoped_or_404, scoped, target_department

router = APIRouter(prefix="/api/subjects", tags=["Subjects"])


def _validate_catalog_refs(subject: SubjectCreate, db: Session, department_id) -> None:
    """Subject types and equipment are per department; a subject may use
    its own department's entries and the shared ones (department NULL)."""
    def usable(model, record_id):
        record = db.get(model, record_id)
        return record is not None and record.department_id in (None, department_id)

    if not usable(SubjectType, subject.type):
        raise HTTPException(status_code=400, detail=f"'{subject.type}' is not a known subject type")
    unknown = [e for e in subject.requires_equipment if not usable(Equipment, e)]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown equipment: {', '.join(unknown)}")


def _derive_subject_code(subject_id: str) -> str:
    """A sensible default export code when the admin hasn't set one -
    Phase 4.1 needs SOME code on every subject, and re-typing the id in
    caps for every row would be busywork the admin didn't ask for."""
    return subject_id.upper()


@router.post("/", response_model=SubjectResponse)
def create_subject(subject: SubjectCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if db.query(Subject).filter(Subject.id == subject.id).first():
        raise HTTPException(status_code=409, detail="A subject with this id already exists")
    data = subject.model_dump()
    data["department_id"] = target_department(admin, data.get("department_id"))
    _validate_catalog_refs(subject, db, data["department_id"])
    data["code"] = data["code"] or _derive_subject_code(subject.id)
    db_subject = Subject(**data)
    db.add(db_subject)
    db.commit()
    db.refresh(db_subject)
    return db_subject

@router.get("/", response_model=List[SubjectResponse])
def list_subjects(department_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return scoped(db.query(Subject), Subject, user, department_id).all()

@router.get("/teacher-qualifications-map")
def get_teacher_qualifications_map(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """subject_id -> [teacher_id, ...] for every subject in one query, so
    the Setup sub-nav can flag "N subjects have no qualified teacher"
    without an N+1 fetch per subject. Registered before /{subject_id} so
    that path parameter can't shadow this fixed one."""
    mapping: dict[str, list[str]] = defaultdict(list)
    for row in scoped(db.query(TeacherSubject), TeacherSubject, user).all():
        mapping[row.subject_id].append(row.teacher_id)
    return mapping

@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(subject_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_scoped_or_404(db, Subject, subject_id, user, "Subject")

@router.get("/{subject_id}/teachers")
def get_subject_teachers(subject_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Which teachers are currently qualified to teach this subject - the
    reverse of a teacher's subject list, so an admin editing a subject can
    immediately see "no one can teach this" instead of discovering it only
    when generation fails."""
    get_scoped_or_404(db, Subject, subject_id, user, "Subject")
    rows = db.query(TeacherSubject).filter(TeacherSubject.subject_id == subject_id).all()
    return [row.teacher_id for row in rows]


@router.put("/{subject_id}", response_model=SubjectResponse)
def update_subject(subject_id: str, subject: SubjectCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, Subject, subject_id, admin, "Subject")
    data = subject.model_dump(exclude={"id"})
    data["department_id"] = target_department(admin, data.get("department_id"))
    _validate_catalog_refs(subject, db, data["department_id"])
    data["code"] = data["code"] or _derive_subject_code(subject_id)
    for key, value in data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record

@router.delete("/{subject_id}")
def delete_subject(
    subject_id: str, dry_run: bool = False, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    subject = get_scoped_or_404(db, Subject, subject_id, admin, "Subject")

    published = (
        db.query(GeneratedEntry)
        .join(TimetableRun, TimetableRun.id == GeneratedEntry.timetable_run_id)
        .filter(GeneratedEntry.subject_id == subject_id, TimetableRun.is_published.is_(True))
        .first()
    )
    blocked_reason = (
        "This subject is used in a published timetable and cannot be deleted while it is live."
        if published else None
    )

    section_count = db.query(SectionSubject).filter(SectionSubject.subject_id == subject_id).count()
    teacher_count = db.query(TeacherSubject).filter(TeacherSubject.subject_id == subject_id).count()
    prereq_count = db.query(Prerequisite).filter(
        (Prerequisite.subject_id == subject_id) | (Prerequisite.requires_subject_id == subject_id)
    ).count()
    counts = {"section_subjects": section_count, "teacher_subjects": teacher_count, "prerequisites": prereq_count}
    warning = f"{section_count} section(s) currently teach this subject." if section_count else None

    if dry_run:
        return {"deletes": counts, "warning": warning, "blocked_reason": blocked_reason}
    if blocked_reason:
        raise HTTPException(status_code=409, detail=blocked_reason)

    db.query(SectionSubject).filter(SectionSubject.subject_id == subject_id).delete()
    db.query(TeacherSubject).filter(TeacherSubject.subject_id == subject_id).delete()
    db.query(Prerequisite).filter(
        (Prerequisite.subject_id == subject_id) | (Prerequisite.requires_subject_id == subject_id)
    ).delete()
    for group in db.query(ElectiveGroup).all():
        if subject_id in (group.offered_subject_ids or []):
            group.offered_subject_ids = [s for s in group.offered_subject_ids if s != subject_id]
    db.delete(subject)
    db.commit()
    return {"message": "Subject deleted", "deleted": counts, "warning": warning}
