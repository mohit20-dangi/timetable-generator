"""Converts database rows into a ProblemData the solver can consume.
This is the only place ORM models and solver dataclasses meet - the
solver package itself never imports SQLAlchemy.
"""
from datetime import time as dtime
from typing import List, Optional, Dict, Tuple

from sqlalchemy.orm import Session

from app.models import (
    AcademicYear, Section, LabBatch, Subject, Teacher, Room, TeacherSubject,
    SectionSubject, TimeSlot, GeneratedEntry, TimetableRun, Reservation,
)
from app.solver.types import ProblemData, RoomInfo, TeacherInfo, SessionDemand, FixedBooking
from app.solver.calendar import build_slot_calendar, valid_starts_for_duration


def _minutes(value) -> int:
    if value is None:
        return 0
    if hasattr(value, "hour"):
        return value.hour * 60 + value.minute
    parts = str(value).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _resolve_target_sections(db: Session, department_id: str, year_ids, section_ids) -> List[Section]:
    query = (
        db.query(Section)
        .join(AcademicYear, Section.year_id == AcademicYear.id)
        .filter(AcademicYear.department_id == department_id)
    )
    if section_ids:
        query = query.filter(Section.id.in_(section_ids))
    elif year_ids:
        query = query.filter(AcademicYear.id.in_(year_ids))
    return query.all()


def _room_unavailable_indices(room: Room, slots, slots_by_index) -> set:
    if not room.availability:
        return set()
    allowed = set()
    for window in room.availability:
        day = window.get("day")
        start_min = _minutes(window.get("start"))
        end_min = _minutes(window.get("end"))
        for slot in slots:
            if slot.day == day and slot.start_minutes >= start_min and slot.end_minutes <= end_min:
                allowed.add(slot.index)
    return {s.index for s in slots} - allowed


def _teacher_unavailable_indices(teacher: Teacher, slots) -> set:
    if not teacher.availability:
        return set()
    allowed = set()
    for window in teacher.availability:
        day = window.get("day")
        start_min = _minutes(window.get("start"))
        end_min = _minutes(window.get("end"))
        for slot in slots:
            if slot.day == day and slot.start_minutes >= start_min and slot.end_minutes <= end_min:
                allowed.add(slot.index)
    return {s.index for s in slots} - allowed


def _teacher_preferred_indices(teacher: Teacher, slots) -> set:
    preferred = set()
    for entry in teacher.preferred_slots or []:
        day = entry.get("day")
        for window in entry.get("slots", []):
            start_min = _minutes(window.get("start"))
            end_min = _minutes(window.get("end"))
            for slot in slots:
                if slot.day == day and slot.start_minutes >= start_min and slot.end_minutes <= end_min:
                    preferred.add(slot.index)
    return preferred


def load_department_problem(
    db: Session,
    department_id: str,
    year_ids: Optional[List[str]] = None,
    section_ids: Optional[List[str]] = None,
    scope_mode: str = "fit_into_existing",
    soft_weights: Optional[Dict[str, int]] = None,
) -> Tuple[ProblemData, List[str]]:
    """Returns (problem, warnings). Warnings are non-fatal data issues
    (e.g. weekly_hours not evenly divisible by block_size) that a caller
    should surface to the admin but that don't block generation."""
    warnings: List[str] = []

    raw_slots = db.query(TimeSlot).all()
    slots = build_slot_calendar([
        {"day": t.day, "period_index": t.period_index, "start_time": t.start_time, "end_time": t.end_time}
        for t in raw_slots
    ])
    slots_by_index = {s.index: s for s in slots}
    if not slots:
        return ProblemData(slots=[], rooms={}, teachers={}, demands=[]), ["No time slots are configured."]

    target_sections = _resolve_target_sections(db, department_id, year_ids, section_ids)
    if not target_sections:
        return ProblemData(slots=slots, rooms={}, teachers={}, demands=[]), ["No sections matched the requested scope."]
    target_section_ids = {s.id for s in target_sections}

    # ---- lunch windows, per section (via its academic year) ----
    lunch_windows: Dict[str, Tuple[int, int]] = {}
    for section in target_sections:
        year = db.query(AcademicYear).filter(AcademicYear.id == section.year_id).first()
        if year and year.lunch_start and year.lunch_end:
            lunch_windows[section.id] = (_minutes(year.lunch_start), _minutes(year.lunch_end))

    # ---- rooms accessible to this department ----
    all_rooms = db.query(Room).all()
    rooms: Dict[str, RoomInfo] = {}
    for room in all_rooms:
        accessible = (
            room.department_id is None
            or room.department_id == department_id
            or (room.shared_with_departments and department_id in room.shared_with_departments)
        )
        if not accessible:
            continue
        rooms[room.id] = RoomInfo(
            id=room.id, type=room.type, capacity=room.capacity,
            equipment=room.equipment or [],
            unavailable_slot_indices=_room_unavailable_indices(room, slots, slots_by_index),
        )

    # ---- subjects taught in scope, via SectionSubject ----
    section_subject_rows = (
        db.query(SectionSubject).filter(SectionSubject.section_id.in_(target_section_ids)).all()
    )
    subject_ids_in_scope = {row.subject_id for row in section_subject_rows}
    subjects = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids_in_scope)).all()}

    # ---- teachers: department's own + anyone qualified for an in-scope subject ----
    teacher_subject_rows = (
        db.query(TeacherSubject).filter(TeacherSubject.subject_id.in_(subject_ids_in_scope)).all()
    )
    qualified_teacher_ids = {row.teacher_id for row in teacher_subject_rows}
    all_relevant_teachers = (
        db.query(Teacher)
        .filter((Teacher.department_id == department_id) | (Teacher.id.in_(qualified_teacher_ids)))
        .all()
    )
    teachers: Dict[str, TeacherInfo] = {}
    for teacher in all_relevant_teachers:
        teachers[teacher.id] = TeacherInfo(
            id=teacher.id,
            max_continuous_classes=teacher.max_continuous_classes,
            max_daily_classes=teacher.max_daily_classes,
            max_weekly_hours=teacher.max_weekly_hours,
            unavailable_slot_indices=_teacher_unavailable_indices(teacher, slots),
            preferred_slot_indices=_teacher_preferred_indices(teacher, slots),
        )

    eligible_teachers_by_subject: Dict[str, List[str]] = {}
    for row in teacher_subject_rows:
        eligible_teachers_by_subject.setdefault(row.subject_id, []).append(row.teacher_id)

    section_subject_elective: Dict[Tuple[str, str], Optional[str]] = {
        (row.section_id, row.subject_id): row.elective_group_id for row in section_subject_rows
    }

    # ---- build demands ----
    demands: List[SessionDemand] = []
    sections_by_id = {s.id: s for s in target_sections}

    for row in section_subject_rows:
        subject = subjects.get(row.subject_id)
        section = sections_by_id.get(row.section_id)
        if not subject or not section:
            continue
        if not subject.is_schedulable:
            continue  # MOOC_NPTEL / INDUSTRY / SELF_STUDY never occupy a room or teacher
        if subject.weekly_hours <= 0:
            continue

        duration = max(1, subject.block_size)
        num_sessions = subject.weekly_hours // duration
        if subject.weekly_hours % duration != 0:
            warnings.append(
                f"{subject.name}: {subject.weekly_hours} weekly hours doesn't divide evenly into "
                f"{duration}-period blocks; only {num_sessions * duration} hours will be scheduled."
            )
        if num_sessions == 0:
            continue

        eligible_room_ids = [
            r.id for r in rooms.values()
            if (subject.requires_room_type is None or r.type == subject.requires_room_type)
            and set(subject.requires_equipment or []) <= set(r.equipment)
        ]
        eligible_teacher_ids = eligible_teachers_by_subject.get(subject.id, [])
        elective_group_id = section_subject_elective.get((row.section_id, row.subject_id)) or subject.elective_group_id

        if subject.type == "lab":
            batches = db.query(LabBatch).filter(LabBatch.section_id == section.id).all()
            if not batches:
                warnings.append(
                    f"{subject.name} is a lab subject for section {section.name} but has no lab "
                    "batches configured - it will not be scheduled. Add at least one LabBatch."
                )
                continue
            for batch in batches:
                batch_room_ids = [r for r in eligible_room_ids if rooms[r].capacity >= batch.strength]
                for i in range(num_sessions):
                    demands.append(SessionDemand(
                        id=f"{subject.id}:{batch.id}:{i}",
                        subject_id=subject.id, subject_name=subject.name, kind=subject.type,
                        audience_type="batch", audience_id=batch.id, parent_section_id=section.id,
                        session_index=i, duration=duration,
                        room_type=subject.requires_room_type, equipment=subject.requires_equipment or [],
                        eligible_room_ids=batch_room_ids, eligible_teacher_ids=eligible_teacher_ids,
                        valid_start_slot_indices=valid_starts_for_duration(
                            slots, duration, lunch_windows.get(section.id)
                        ),
                        max_per_day=subject.max_per_day,
                        elective_group_id=elective_group_id,
                    ))
        else:
            section_room_ids = [r for r in eligible_room_ids if rooms[r].capacity >= section.strength]
            for i in range(num_sessions):
                demands.append(SessionDemand(
                    id=f"{subject.id}:{section.id}:{i}",
                    subject_id=subject.id, subject_name=subject.name, kind=subject.type,
                    audience_type="section", audience_id=section.id, parent_section_id=section.id,
                    session_index=i, duration=duration,
                    room_type=subject.requires_room_type, equipment=subject.requires_equipment or [],
                    eligible_room_ids=section_room_ids, eligible_teacher_ids=eligible_teacher_ids,
                    valid_start_slot_indices=valid_starts_for_duration(
                        slots, duration, lunch_windows.get(section.id)
                    ),
                    max_per_day=subject.max_per_day,
                    elective_group_id=elective_group_id,
                ))

    # ---- frozen bookings: explicit Reservations + already-published entries outside scope ----
    fixed_bookings: List[FixedBooking] = []
    if scope_mode == "fit_into_existing":
        relevant_room_ids = set(rooms.keys())
        relevant_teacher_ids = set(teachers.keys())
        slot_index_by_day_period = {(s.day, s.period_index): s.index for s in slots}

        for reservation in db.query(Reservation).filter(Reservation.department_id == department_id).all():
            slot_index = slot_index_by_day_period.get((reservation.day, reservation.period))
            if slot_index is None:
                continue
            fixed_bookings.append(FixedBooking(
                resource_type=reservation.resource_type, resource_id=reservation.resource_id,
                start_slot_index=slot_index, duration=1, reason=reservation.reason or "reserved",
            ))

        published_entries = (
            db.query(GeneratedEntry)
            .join(TimetableRun, GeneratedEntry.timetable_run_id == TimetableRun.id)
            .filter(TimetableRun.is_published.is_(True))
            .filter(GeneratedEntry.alternative_rank == 1)
            .all()
        )
        for entry in published_entries:
            if entry.section_id in target_section_ids:
                continue  # this entry belongs to the scope we're about to regenerate - not frozen
            slot_index = slot_index_by_day_period.get((entry.day, entry.period))
            if slot_index is None:
                continue
            if entry.teacher_id in relevant_teacher_ids:
                fixed_bookings.append(FixedBooking(
                    resource_type="teacher", resource_id=entry.teacher_id,
                    start_slot_index=slot_index, duration=1, reason="published elsewhere",
                ))
            if entry.room_id in relevant_room_ids:
                fixed_bookings.append(FixedBooking(
                    resource_type="room", resource_id=entry.room_id,
                    start_slot_index=slot_index, duration=1, reason="published elsewhere",
                ))

    problem = ProblemData(
        slots=slots, rooms=rooms, teachers=teachers, demands=demands,
        fixed_bookings=fixed_bookings, soft_weights=soft_weights or {},
        lunch_windows=lunch_windows,
    )
    return problem, warnings
