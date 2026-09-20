"""Re-validates a PERSISTED run's GeneratedEntry rows directly against the
database, independently of app/solver/validator.py (which checks the
solver's in-memory output before it's ever written down) and independently
of app/solver/model_builder.py's constraint logic. Two different
representations (variable-duration intervals pre-save vs. one-row-per-
period post-save) checked by two different code paths is the actual
safety net - if a bug ever let a bad schedule through the first check, a
second, structurally different check is very unlikely to share the same
blind spot.

This is also what GET /api/timetable/runs/{id}/validate calls, and what a
completed run is re-checked against immediately after generation, before
its status is ever reported to the admin as "completed" (see
app/routers/timetable.py::_run_generation).
"""
from typing import List, Dict, Tuple
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import GeneratedEntry, Subject, Room, Section, LabBatch, AcademicYear, TimeSlot


@dataclass
class Violation:
    type: str
    message: str


def _minutes(value) -> int:
    if value is None:
        return 0
    if hasattr(value, "hour"):
        return value.hour * 60 + value.minute
    parts = str(value).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def validate_persisted_run(db: Session, run_id: int, alternative_rank: int = 1) -> List[Violation]:
    entries = (
        db.query(GeneratedEntry)
        .filter(GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == alternative_rank)
        .all()
    )
    if not entries:
        return []

    violations: List[Violation] = []

    def flag_clashes(key_fn, label):
        groups: Dict[tuple, list] = {}
        for e in entries:
            key = key_fn(e)
            if key is None:
                continue
            groups.setdefault(key, []).append(e)
        for key, group in groups.items():
            if len(group) > 1:
                ids = ", ".join(str(e.id) for e in group)
                violations.append(Violation(label, f"{label} at {key}: entries {ids}."))

    flag_clashes(lambda e: (e.room_id, e.day, e.period), "ROOM_CLASH")
    flag_clashes(lambda e: (e.teacher_id, e.day, e.period), "TEACHER_CLASH")
    flag_clashes(lambda e: (e.section_id, e.day, e.period) if e.section_id else None, "SECTION_CLASH")
    flag_clashes(lambda e: (e.batch_id, e.day, e.period) if e.batch_id else None, "BATCH_CLASH")

    # ---- batch vs its own parent section ----
    batch_section = {
        b.id: b.section_id for b in db.query(LabBatch).filter(
            LabBatch.id.in_([e.batch_id for e in entries if e.batch_id])
        ).all()
    }
    section_slots = {(e.section_id, e.day, e.period) for e in entries if e.section_id}
    for e in entries:
        if e.batch_id and (batch_section.get(e.batch_id), e.day, e.period) in section_slots:
            violations.append(Violation(
                "BATCH_CLASH",
                f"Batch {e.batch_id} clashes with its own section's class on {e.day} period {e.period}.",
            ))

    # ---- room capacity ----
    rooms = {r.id: r for r in db.query(Room).filter(Room.id.in_({e.room_id for e in entries})).all()}
    sections = {s.id: s for s in db.query(Section).filter(Section.id.in_({e.section_id for e in entries if e.section_id})).all()}
    batches = {b.id: b for b in db.query(LabBatch).filter(LabBatch.id.in_({e.batch_id for e in entries if e.batch_id})).all()}
    for e in entries:
        room = rooms.get(e.room_id)
        if not room:
            continue
        strength = None
        if e.section_id and e.section_id in sections:
            strength = sections[e.section_id].strength
        elif e.batch_id and e.batch_id in batches:
            strength = batches[e.batch_id].strength
        if strength is not None and strength > room.capacity:
            violations.append(Violation(
                "ROOM_CAPACITY",
                f"Entry {e.id}: audience of {strength} exceeds room {room.id}'s capacity of {room.capacity}.",
            ))

    # ---- lunch window ----
    slot_minutes = {
        (t.day, t.period_index): (_minutes(t.start_time), _minutes(t.end_time))
        for t in db.query(TimeSlot).all()
    }
    year_lunch: Dict[str, Tuple[int, int]] = {}
    for section in sections.values():
        year = db.query(AcademicYear).filter(AcademicYear.id == section.year_id).first()
        if year and year.lunch_start and year.lunch_end:
            year_lunch[section.id] = (_minutes(year.lunch_start), _minutes(year.lunch_end))
    for e in entries:
        section_id = e.section_id or (batch_section.get(e.batch_id) if e.batch_id else None)
        window = year_lunch.get(section_id)
        if not window:
            continue
        slot_window = slot_minutes.get((e.day, e.period))
        if not slot_window:
            continue
        lunch_start, lunch_end = window
        slot_start, slot_end = slot_window
        if slot_start < lunch_end and lunch_start < slot_end:
            violations.append(Violation("LUNCH_BREAK", f"Entry {e.id} overlaps the lunch window."))

    # ---- teacher consistency + max-per-day, per (subject, audience) ----
    subjects = {s.id: s for s in db.query(Subject).filter(Subject.id.in_({e.subject_id for e in entries})).all()}
    by_group: Dict[Tuple[str, str], list] = {}
    for e in entries:
        audience = e.section_id or e.batch_id or "unknown"
        by_group.setdefault((e.subject_id, audience), []).append(e)
    for (subject_id, audience), group in by_group.items():
        teacher_ids = {e.teacher_id for e in group}
        if len(teacher_ids) > 1:
            violations.append(Violation(
                "TEACHER_INCONSISTENT",
                f"Subject {subject_id} for {audience} has {len(teacher_ids)} different teachers.",
            ))
        subject = subjects.get(subject_id)
        cap = subject.max_per_day if subject else 1
        # Count distinct SESSIONS per day, not raw rows - a single
        # multi-period block (e.g. a 2-hour lab) produces one row per
        # occupied period and must count as one session, not several.
        sessions_by_day: Dict[str, set] = {}
        for e in group:
            sessions_by_day.setdefault(e.day, set()).add(e.session_group)
        for day, session_groups in sessions_by_day.items():
            count = len(session_groups)
            if count > cap:
                violations.append(Violation(
                    "MAX_PER_DAY_EXCEEDED",
                    f"Subject {subject_id} for {audience} appears {count} times on {day} (max {cap}).",
                ))

    return violations
