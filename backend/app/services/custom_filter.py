"""Deterministic evaluation of a Custom Filter spec (app/schemas/custom_filter.py).

The LLM only ever produces the FilterSpec; everything here is plain,
testable logic over already-generated timetable data. Nothing in this
module writes to the database or asks a model anything.
"""
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models import (
    GeneratedEntry, LabBatch, Room, Subject, Teacher, TimeSlot, TimetableRun, User,
)
from app.schemas.custom_filter import FilterSpec
from app.services.department_calendar import department_time_slots
from app.services.entry_teachers import entry_teacher_ids
from app.solver.calendar import build_slot_calendar
from app.solver.data_loader import room_unavailable_indices, teacher_unavailable_indices

ME = "$me"


def _section_of(entry, batch_to_section: Dict[str, str]) -> Optional[str]:
    if entry.section_id:
        return entry.section_id
    return batch_to_section.get(entry.batch_id) if entry.batch_id else None


def _matches_section(entry, section_ids: Set[str], batch_to_section: Dict[str, str]) -> bool:
    # Same rule the By Section tab uses: a lab-batch entry belongs to its
    # batch's parent section even when section_id itself is empty.
    return (
        entry.section_id in section_ids
        or entry.batch_id in section_ids
        or _section_of(entry, batch_to_section) in section_ids
    )


def evaluate(
    spec: FilterSpec,
    entries: Iterable[Any],
    external_busy: Iterable[Any],
    slots: List[Dict[str, Any]],
    rooms: Dict[str, Room],
    teachers: Dict[str, Teacher],
    subjects: Dict[str, Subject],
    batch_to_section: Dict[str, str],
    me_teacher_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Returns [{"day","period","entries":[...],"free_rooms":[Room,...]}],
    in day/period order. `entries` are this view's entries; `external_busy`
    are extra bookings (other departments' published classes) that make a
    teacher/room/section busy but are never shown as results themselves.
    `slots` are {"day","period_index","start_time","end_time"} rows."""
    entries = list(entries)
    calendar = build_slot_calendar(slots)
    slot_index = {(s.day, s.period_index): s for s in calendar}

    teacher_ids = set(spec.teacher_ids)
    if ME in teacher_ids:
        teacher_ids.discard(ME)
        if me_teacher_id:
            teacher_ids.add(me_teacher_id)
        elif not teacher_ids:
            # "$me" with no linked teacher: matching everything would be a
            # misleading answer to "my classes", so match nothing.
            return []

    def in_window(day: str, period: int) -> bool:
        slot = slot_index.get((day, period))
        if spec.days and day not in spec.days:
            return False
        if slot is None:
            # A class on a slot that's no longer in the bell schedule can't
            # be placed in a time window - only keep it if no window is set.
            return not (spec.time_from or spec.time_to)
        if spec.time_from and slot.start_minutes < _minutes(spec.time_from):
            return False
        if spec.time_to and slot.end_minutes > _minutes(spec.time_to):
            return False
        return True

    if spec.mode == "classes":
        return _evaluate_classes(spec, entries, teacher_ids, subjects, batch_to_section, in_window)
    return _evaluate_free_slots(
        spec, entries, list(external_busy), calendar, rooms, teachers,
        teacher_ids, batch_to_section, in_window,
    )


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")[:2]
    return int(hours) * 60 + int(minutes)


def _evaluate_classes(spec, entries, teacher_ids, subjects, batch_to_section, in_window):
    section_ids = set(spec.section_ids)
    subject_ids = set(spec.subject_ids)
    room_ids = set(spec.room_ids)
    subject_types = set(spec.subject_types)

    cells: Dict[Tuple[str, int], List[Any]] = {}
    for entry in entries:
        if not in_window(entry.day, entry.period):
            continue
        if teacher_ids and not (teacher_ids & set(entry_teacher_ids(entry))):
            continue
        if section_ids and not _matches_section(entry, section_ids, batch_to_section):
            continue
        if subject_ids and entry.subject_id not in subject_ids:
            continue
        if room_ids and entry.room_id not in room_ids:
            continue
        if subject_types:
            subject = subjects.get(entry.subject_id)
            if not subject or subject.type not in subject_types:
                continue
        cells.setdefault((entry.day, entry.period), []).append(entry)

    return [
        {"day": day, "period": period, "entries": cell_entries, "free_rooms": []}
        for (day, period), cell_entries in sorted(cells.items(), key=lambda kv: (_day_rank(kv[0][0]), kv[0][1]))
    ]


def _day_rank(day: str) -> int:
    order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return order.index(day) if day in order else 99


def _evaluate_free_slots(
    spec, entries, external_busy, calendar, rooms, teachers,
    teacher_ids, batch_to_section, in_window,
):
    busy_entries = entries + external_busy
    section_ids = set(spec.section_ids)

    busy_teachers: Dict[Tuple[str, int], Set[str]] = {}
    busy_rooms: Dict[Tuple[str, int], Set[str]] = {}
    busy_sections: Dict[Tuple[str, int], Set[str]] = {}
    for entry in busy_entries:
        key = (entry.day, entry.period)
        # A co-taught lab makes EVERY teacher in it busy, so "when are we
        # all free?" must not offer a slot where one of them is the second
        # supervisor on a lab.
        for teacher_id in entry_teacher_ids(entry):
            busy_teachers.setdefault(key, set()).add(teacher_id)
        if entry.room_id:
            busy_rooms.setdefault(key, set()).add(entry.room_id)
        section = _section_of(entry, batch_to_section)
        if section:
            busy_sections.setdefault(key, set()).add(section)

    # A teacher's own declared availability windows count as "not free" too.
    teacher_blocked = {
        tid: {calendar[i].day + ":" + str(calendar[i].period_index) for i in teacher_unavailable_indices(teachers[tid], calendar)}
        for tid in teacher_ids if tid in teachers
    }
    room_needed = bool(spec.room_ids or spec.room_types or spec.min_room_capacity)
    candidate_rooms = [
        room for room in rooms.values()
        if (not spec.room_ids or room.id in spec.room_ids)
        and (not spec.room_types or room.type in spec.room_types)
        and (not spec.min_room_capacity or (room.capacity or 0) >= spec.min_room_capacity)
    ] if room_needed else []
    room_blocked = {
        room.id: {calendar[i].day + ":" + str(calendar[i].period_index) for i in room_unavailable_indices(room, calendar, None)}
        for room in candidate_rooms
    }

    cells = []
    for slot in calendar:
        if not in_window(slot.day, slot.period_index):
            continue
        key = (slot.day, slot.period_index)
        tag = f"{slot.day}:{slot.period_index}"
        if any(t in busy_teachers.get(key, ()) or tag in teacher_blocked.get(t, ()) for t in teacher_ids):
            continue
        if section_ids and (section_ids & busy_sections.get(key, set())):
            continue
        free_rooms: List[Room] = []
        if room_needed:
            free_rooms = [
                r for r in candidate_rooms
                if r.id not in busy_rooms.get(key, ()) and tag not in room_blocked[r.id]
            ]
            if not free_rooms:
                continue
        cells.append({"day": slot.day, "period": slot.period_index, "entries": [], "free_rooms": free_rooms})
    return cells


# ---------- data loading (DB-facing; evaluate() above stays pure) ----------

def published_entries(db: Session, exclude_run_id: Optional[int] = None,
                      exclude_department_id: Optional[str] = None,
                      only_other_departments: bool = False) -> List[GeneratedEntry]:
    """Rank-1 entries of every published run, optionally skipping one run or
    (for the run viewer's "what's really free" check) every run of the
    requesting run's own department."""
    query = db.query(TimetableRun).filter(TimetableRun.is_published.is_(True))
    if exclude_run_id is not None:
        query = query.filter(TimetableRun.id != exclude_run_id)
    if only_other_departments and exclude_department_id is not None:
        query = query.filter(TimetableRun.department_id != exclude_department_id)
    run_ids = [r.id for r in query.all()]
    if not run_ids:
        return []
    return db.query(GeneratedEntry).filter(
        GeneratedEntry.timetable_run_id.in_(run_ids), GeneratedEntry.alternative_rank == 1,
    ).all()


def evaluate_for_user(db: Session, user: User, spec: FilterSpec, run: Optional[TimetableRun]) -> List[Dict[str, Any]]:
    """run given: that run's rank-1 entries, with other departments'
    published classes as extra busy. No run: the union of every published
    timetable (what a faculty member can see)."""
    if run is not None:
        entries = db.query(GeneratedEntry).filter(
            GeneratedEntry.timetable_run_id == run.id, GeneratedEntry.alternative_rank == 1,
        ).all()
        external = published_entries(
            db, exclude_run_id=run.id, exclude_department_id=run.department_id, only_other_departments=True,
        )
    else:
        entries, external = published_entries(db), []

    slot_rows = department_time_slots(db, run.department_id if run else user.department_id)
    slots = [
        {"day": s.day, "period_index": s.period_index, "start_time": s.start_time, "end_time": s.end_time}
        for s in slot_rows
    ]
    return evaluate(
        spec, entries, external, slots,
        rooms={r.id: r for r in db.query(Room).all()},
        teachers={t.id: t for t in db.query(Teacher).all()},
        subjects={s.id: s for s in db.query(Subject).all()},
        batch_to_section={b.id: b.section_id for b in db.query(LabBatch).all()},
        me_teacher_id=user.teacher_id,
    )
