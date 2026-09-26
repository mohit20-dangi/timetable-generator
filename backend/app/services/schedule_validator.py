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
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import GeneratedEntry, Subject, Room, Section, LabBatch, AcademicYear, TimeSlot, Teacher, SectionSubject
from app.solver.calendar import build_slot_calendar
from app.solver.data_loader import teacher_unavailable_indices, room_unavailable_indices


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

    section_subject_rows = db.query(SectionSubject).filter(
        SectionSubject.section_id.in_({e.section_id for e in entries if e.section_id})
    ).all()
    section_subject_elective = {(r.section_id, r.subject_id): r.elective_group_id for r in section_subject_rows}
    subjects_by_id = {
        s.id: s for s in db.query(Subject).filter(Subject.id.in_({e.subject_id for e in entries if e.subject_id})).all()
    }
    batch_section = {
        b.id: b.section_id for b in db.query(LabBatch).filter(
            LabBatch.id.in_([e.batch_id for e in entries if e.batch_id])
        ).all()
    }

    def is_merged_batch_group(group) -> bool:
        """Phase 2.9: a subject in "merged" batch mode DELIBERATELY puts
        every sibling batch's entry in the same room, with the same
        teacher, at the same time - one combined class. Without this
        exemption every merged subject would fail ROOM_CLASH/TEACHER_CLASH,
        the same trap the elective exemption just below exists to avoid."""
        if not all(e.batch_id and e.subject_id for e in group):
            return False
        modes = set()
        sections = set()
        for e in group:
            subject = subjects_by_id.get(e.subject_id)
            modes.add(subject.batch_scheduling_mode if subject else None)
            sections.add(batch_section.get(e.batch_id))
        return modes == {"merged"} and len(sections) == 1

    def flag_clashes(key_fn, label):
        groups: Dict[tuple, list] = {}
        for e in entries:
            key = key_fn(e)
            if key is None:
                continue
            groups.setdefault(key, []).append(e)
        for key, group in groups.items():
            if len(group) > 1 and not is_merged_batch_group(group):
                ids = ", ".join(str(e.id) for e in group)
                violations.append(Violation(label, f"{label} at {key}: entries {ids}."))

    flag_clashes(lambda e: (e.room_id, e.day, e.period), "ROOM_CLASH")
    flag_clashes(lambda e: (e.teacher_id, e.day, e.period), "TEACHER_CLASH")

    # Elective basket options are deliberately co-scheduled onto the same
    # (section/batch, day, period) - each offered option is its own
    # GeneratedEntry row with its own subject/teacher/room, and that's the
    # whole point (see model_builder._overlap_intervals_collapsing_electives
    # for the matching exception on the generation side). Grouping by
    # audience+slot alone would flag every one of those as a false-positive
    # clash, so a group is only flagged when its members are NOT all the
    # same elective basket's co-scheduled options.
    def elective_group_of(e) -> Optional[str]:
        if not e.subject_id:
            return None
        override = section_subject_elective.get((e.section_id, e.subject_id)) if e.section_id else None
        if override:
            return override
        subject = subjects_by_id.get(e.subject_id)
        return subject.elective_group_id if subject else None

    def flag_audience_clashes(key_fn, label):
        groups: Dict[tuple, list] = {}
        for e in entries:
            key = key_fn(e)
            if key is None:
                continue
            groups.setdefault(key, []).append(e)
        for key, group in groups.items():
            if len(group) <= 1:
                continue
            elective_ids = {elective_group_of(e) for e in group}
            if len(elective_ids) == 1 and None not in elective_ids:
                continue  # every entry is the same elective basket's co-scheduled options
            ids = ", ".join(str(e.id) for e in group)
            violations.append(Violation(label, f"{label} at {key}: entries {ids}."))

    flag_audience_clashes(lambda e: (e.section_id, e.day, e.period) if e.section_id else None, "SECTION_CLASH")
    flag_audience_clashes(lambda e: (e.batch_id, e.day, e.period) if e.batch_id else None, "BATCH_CLASH")

    # ---- batch vs its own parent section ----
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
    year_lunch: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for section in sections.values():
        year = db.query(AcademicYear).filter(AcademicYear.id == section.year_id).first()
        if year and year.lunch_windows:
            year_lunch[section.id] = {
                day: (_minutes(window[0]), _minutes(window[1]))
                for day, window in year.lunch_windows.items()
                if window and len(window) == 2
            }
    for e in entries:
        section_id = e.section_id or (batch_section.get(e.batch_id) if e.batch_id else None)
        day_windows = year_lunch.get(section_id)
        if not day_windows:
            continue
        window = day_windows.get(e.day)
        if not window:
            continue
        slot_window = slot_minutes.get((e.day, e.period))
        if not slot_window:
            continue
        lunch_start, lunch_end = window
        slot_start, slot_end = slot_window
        if slot_start < lunch_end and lunch_start < slot_end:
            violations.append(Violation("LUNCH_BREAK", f"Entry {e.id} overlaps the lunch window on {e.day}."))

    # ---- teacher/room availability (mirrors Phase 1.1 / 1.2's hard model
    # constraints) - reuses the exact same window-parsing logic the solver
    # uses, so this independent check can never drift out of sync with
    # what the model actually enforces ----
    teachers = {
        t.id: t for t in db.query(Teacher).filter(Teacher.id.in_({e.teacher_id for e in entries if e.teacher_id})).all()
    }
    slots = build_slot_calendar([
        {"day": t.day, "period_index": t.period_index, "start_time": t.start_time, "end_time": t.end_time}
        for t in db.query(TimeSlot).all()
    ])
    slots_by_index = {s.index: s for s in slots}
    slot_index_by_day_period = {(s.day, s.period_index): s.index for s in slots}
    teacher_unavail = {t_id: teacher_unavailable_indices(t, slots) for t_id, t in teachers.items()}
    room_unavail = {r_id: room_unavailable_indices(r, slots, slots_by_index) for r_id, r in rooms.items()}
    for e in entries:
        slot_index = slot_index_by_day_period.get((e.day, e.period))
        if slot_index is None:
            continue
        if e.teacher_id and slot_index in teacher_unavail.get(e.teacher_id, set()):
            violations.append(Violation(
                "TEACHER_UNAVAILABLE",
                f"Entry {e.id}: teacher {e.teacher_id} is marked unavailable at {e.day} period {e.period}.",
            ))
        if e.room_id and slot_index in room_unavail.get(e.room_id, set()):
            violations.append(Violation(
                "ROOM_UNAVAILABLE",
                f"Entry {e.id}: room {e.room_id} is marked unavailable at {e.day} period {e.period}.",
            ))

    # ---- teacher workload caps (mirrors Phase 1.3's hard model
    # constraints): daily/weekly period counts and same-day back-to-back
    # runs, all counted in PERIODS (one GeneratedEntry row each), not
    # sessions ----
    entries_by_teacher: Dict[str, list] = {}
    for e in entries:
        if e.teacher_id:
            entries_by_teacher.setdefault(e.teacher_id, []).append(e)
    for teacher_id, t_entries in entries_by_teacher.items():
        teacher = teachers.get(teacher_id)
        if not teacher:
            continue
        if len(t_entries) > teacher.max_weekly_hours:
            violations.append(Violation(
                "TEACHER_WEEKLY_CAP",
                f"Teacher {teacher_id} is scheduled {len(t_entries)} periods this week (max {teacher.max_weekly_hours}).",
            ))
        by_day: Dict[str, list] = {}
        for e in t_entries:
            by_day.setdefault(e.day, []).append(e)
        for day, day_entries in by_day.items():
            if len(day_entries) > teacher.max_daily_classes:
                violations.append(Violation(
                    "TEACHER_DAILY_CAP",
                    f"Teacher {teacher_id} is scheduled {len(day_entries)} periods on {day} (max {teacher.max_daily_classes}).",
                ))
            ordered = sorted(day_entries, key=lambda e: slot_minutes.get((e.day, e.period), (0, 0))[0])
            run_len = 1
            max_run = 1
            for prev, curr in zip(ordered, ordered[1:]):
                prev_window = slot_minutes.get((prev.day, prev.period))
                curr_window = slot_minutes.get((curr.day, curr.period))
                run_len = run_len + 1 if prev_window and curr_window and prev_window[1] == curr_window[0] else 1
                max_run = max(max_run, run_len)
            if max_run > teacher.max_continuous_classes:
                violations.append(Violation(
                    "TEACHER_CONTINUOUS_CAP",
                    f"Teacher {teacher_id} has {max_run} back-to-back periods on {day} (max {teacher.max_continuous_classes}).",
                ))

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
