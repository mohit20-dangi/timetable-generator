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
    ConstraintRule,
)
from app.solver.types import ProblemData, RoomInfo, TeacherInfo, SessionDemand, FixedBooking, SoftAvoidRule
from app.solver.calendar import build_slot_calendar, valid_starts_for_duration, occupied_indices


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


def room_unavailable_indices(room: Room, slots, slots_by_index) -> set:
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


def teacher_unavailable_indices(teacher: Teacher, slots) -> set:
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


def _valid_starts_excluding(slots, duration, lunch_windows, forbidden: set, slots_by_index) -> List[int]:
    """Same as valid_starts_for_duration, minus any start whose occupied
    span touches a `section_unavailable` hard rule's slots (Phase 1.4).
    `lunch_windows` is per-day: {day: (start_minutes, end_minutes)}."""
    starts = valid_starts_for_duration(slots, duration, lunch_windows)
    if not forbidden:
        return starts
    return [
        v for v in starts
        if not (set(occupied_indices(v, duration, slots_by_index)) & forbidden)
    ]


def _rule_slot_indices(rule: "ConstraintRule", slots) -> set:
    """The slot indices a ConstraintRule's (day, start_time, end_time)
    window covers. A rule with no day/time set applies to nothing - it
    would be a data-entry mistake to fold in "every slot" by default."""
    if not rule.day or rule.start_time is None or rule.end_time is None:
        return set()
    start_min = _minutes(rule.start_time)
    end_min = _minutes(rule.end_time)
    return {
        s.index for s in slots
        if s.day == rule.day and s.start_minutes >= start_min and s.end_minutes <= end_min
    }


VALID_BATCH_MODES = {"independent", "parallel", "sequential", "merged"}


def _apply_constraint_rules(
    db: Session, department_id: str, slots, rooms: Dict[str, RoomInfo],
    teachers: Dict[str, TeacherInfo], warnings: List[str],
) -> Tuple[Dict[str, set], List[SoftAvoidRule], Dict[str, str], Dict[str, set]]:
    """Folds active ConstraintRule rows (Phase 1.4) into the ProblemData
    the solver already knows how to enforce, instead of the previous
    build's dead end where an approved, audited rule had zero effect on
    the timetable. Returns (hard_forbidden_by_section, soft_avoid_rules,
    batch_mode_overrides, batch_window_by_subject) - the effects that
    can't be applied directly to `rooms`/`teachers` in place.
    batch_mode_overrides/batch_window_by_subject (Phase 2.9) come from
    rule_type="batch_scheduling_mode" rows: target_id is a subject id,
    `batch_mode` overrides that subject's own batch_scheduling_mode, and
    an optional day/time window additionally confines that subject's
    lab-batch sessions to it (see ConstraintRule's docstring).
    """
    hard_forbidden_by_section: Dict[str, set] = {}
    soft_avoid_rules: List[SoftAvoidRule] = []
    batch_mode_overrides: Dict[str, str] = {}
    batch_window_by_subject: Dict[str, set] = {}

    rules = (
        db.query(ConstraintRule)
        .filter(ConstraintRule.department_id == department_id, ConstraintRule.is_active.is_(True))
        .all()
    )
    for rule in rules:
        if rule.rule_type == "custom":
            label = rule.description or rule.raw_instruction or rule.id
            warnings.append(
                f"'{label}' is a custom rule and isn't automatically applied to the schedule - review it manually."
            )
            continue

        if rule.rule_type == "teacher_preferred":
            teacher = teachers.get(rule.target_id)
            if teacher:
                teacher.preferred_slot_indices |= _rule_slot_indices(rule, slots)
            continue

        if rule.rule_type == "max_daily_override":
            teacher = teachers.get(rule.target_id)
            if not teacher:
                continue
            if rule.weight > 0:
                teacher.max_daily_classes = rule.weight
            else:
                warnings.append(f"max_daily_override rule '{rule.id}' has no override value set and was skipped.")
            continue

        if rule.rule_type == "batch_scheduling_mode":
            if rule.batch_mode not in VALID_BATCH_MODES:
                warnings.append(
                    f"Constraint rule '{rule.id}' has an invalid batch_mode "
                    f"'{rule.batch_mode}' and was skipped."
                )
                continue
            batch_mode_overrides[rule.target_id] = rule.batch_mode
            if rule.day and rule.start_time is not None and rule.end_time is not None:
                batch_window_by_subject.setdefault(rule.target_id, set()).update(
                    _rule_slot_indices(rule, slots)
                )
            continue

        slot_indices = _rule_slot_indices(rule, slots)
        if not slot_indices:
            warnings.append(f"Constraint rule '{rule.id}' has no day/time window and was skipped.")
            continue

        if rule.rule_type == "teacher_unavailable":
            teacher = teachers.get(rule.target_id)
            if not teacher:
                continue
            if rule.priority == "hard":
                teacher.unavailable_slot_indices |= slot_indices
            else:
                soft_avoid_rules.append(SoftAvoidRule("teacher", rule.target_id, slot_indices, rule.weight))
        elif rule.rule_type == "room_unavailable":
            room = rooms.get(rule.target_id)
            if not room:
                continue
            if rule.priority == "hard":
                room.unavailable_slot_indices |= slot_indices
            else:
                soft_avoid_rules.append(SoftAvoidRule("room", rule.target_id, slot_indices, rule.weight))
        elif rule.rule_type == "section_unavailable":
            if rule.priority == "hard":
                hard_forbidden_by_section.setdefault(rule.target_id, set()).update(slot_indices)
            else:
                soft_avoid_rules.append(SoftAvoidRule("section", rule.target_id, slot_indices, rule.weight))

    return hard_forbidden_by_section, soft_avoid_rules, batch_mode_overrides, batch_window_by_subject


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
    must_have_rules: Optional[set] = None,
    subject_overrides: Optional[List[Dict]] = None,
) -> Tuple[ProblemData, List[str]]:
    """Returns (problem, warnings). Warnings are non-fatal data issues
    (e.g. weekly_hours not evenly divisible by block_size) that a caller
    should surface to the admin but that don't block generation.

    subject_overrides: run-scoped-only tweaks (TimetableRun.subject_overrides
    - see that column's docstring), each {"section_id", "subject_id",
    "weekly_hours": optional int, "exclude": optional bool}. Applied only to
    the in-memory demand this run builds - the real Subject/SectionSubject
    rows are never touched, so this is safe to pass for a one-off "just for
    this timetable" edit without affecting any other run.
    """
    warnings: List[str] = []
    override_by_pair: Dict[Tuple[str, str], Dict] = {
        (o["section_id"], o["subject_id"]): o for o in (subject_overrides or [])
    }

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

    # ---- lunch windows, per section (via its academic year), per day
    # (Phase 2.5) - a day absent from the year's lunch_windows has no
    # lunch break at all, so e.g. Thursday can run a class straight
    # through what's lunch on every other day. ----
    lunch_windows: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for section in target_sections:
        year = db.query(AcademicYear).filter(AcademicYear.id == section.year_id).first()
        if year and year.lunch_windows:
            lunch_windows[section.id] = {
                day: (_minutes(window[0]), _minutes(window[1]))
                for day, window in year.lunch_windows.items()
                if window and len(window) == 2
            }

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
            unavailable_slot_indices=room_unavailable_indices(room, slots, slots_by_index),
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
            unavailable_slot_indices=teacher_unavailable_indices(teacher, slots),
            preferred_slot_indices=_teacher_preferred_indices(teacher, slots),
        )

    eligible_teachers_by_subject: Dict[str, List[str]] = {}
    for row in teacher_subject_rows:
        eligible_teachers_by_subject.setdefault(row.subject_id, []).append(row.teacher_id)

    section_subject_elective: Dict[Tuple[str, str], Optional[str]] = {
        (row.section_id, row.subject_id): row.elective_group_id for row in section_subject_rows
    }

    # ---- fold in ConstraintRule rows (Phase 1.4) ----
    hard_forbidden_by_section, soft_avoid_rules, batch_mode_overrides, batch_window_by_subject = _apply_constraint_rules(
        db, department_id, slots, rooms, teachers, warnings,
    )

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

        override = override_by_pair.get((row.section_id, row.subject_id))
        if override and override.get("exclude"):
            continue
        effective_weekly_hours = (
            override["weekly_hours"] if override and override.get("weekly_hours") is not None
            else subject.weekly_hours
        )
        if effective_weekly_hours <= 0:
            continue

        # Phase 2.4: "sessions per week" x "periods per session" replaces
        # the old single block_size/needs_continuous_block pair. When
        # sessions_per_week isn't set explicitly it's derived from
        # weekly_hours, matching the previous block_size-based behaviour.
        periods_per_session = max(1, subject.periods_per_session)
        if override and override.get("weekly_hours") is not None and subject.sessions_per_week is not None:
            # This subject pins its session count directly rather than
            # deriving it from weekly_hours - an hours-only override can't
            # change how many sessions get scheduled, so say so instead of
            # silently doing nothing.
            warnings.append(
                f"{subject.name} for {section.name}: the requested hours/week change was applied, "
                f"but this subject has a fixed sessions_per_week ({subject.sessions_per_week}) that "
                "doesn't derive from hours/week, so the number of scheduled sessions is unchanged."
            )
        num_sessions = (
            subject.sessions_per_week if subject.sessions_per_week is not None
            else effective_weekly_hours // periods_per_session
        )
        if num_sessions * periods_per_session != effective_weekly_hours:
            warnings.append(
                f"{subject.name}: {num_sessions} session(s) of {periods_per_session} period(s) "
                f"= {num_sessions * periods_per_session} hours, not the {effective_weekly_hours} "
                "configured contact hours/week."
            )
        if num_sessions == 0:
            continue

        # A session whose periods don't have to be back-to-back is emitted
        # as separate 1-period demands instead of one contiguous block -
        # model_builder adds a soft same-day preference between the parts
        # of one session (matched by session_index) instead of a hard
        # contiguity requirement.
        split_session = not subject.back_to_back and periods_per_session > 1
        demand_duration = 1 if split_session else periods_per_session
        parts_per_session = periods_per_session if split_session else 1

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

            batch_mode = batch_mode_overrides.get(subject.id, subject.batch_scheduling_mode)
            if batch_mode not in VALID_BATCH_MODES:
                batch_mode = "independent"

            # Phase 2.9: "merged" means every batch is taught as ONE
            # combined class - same room, same teacher, same slot - so
            # every batch needs the SAME set of eligible rooms, each big
            # enough for the batches' COMBINED strength, not just its own.
            # A subject with only one batch can't meaningfully merge with
            # a sibling, so it falls back to ordinary per-batch capacity.
            if batch_mode == "merged" and len(batches) > 1:
                total_strength = sum(b.strength for b in batches)
                shared_room_ids = [r for r in eligible_room_ids if rooms[r].capacity >= total_strength]
                if not shared_room_ids:
                    warnings.append(
                        f"{subject.name} for section {section.name} is set to merge its {len(batches)} "
                        f"lab batches ({total_strength} students combined), but no eligible room seats "
                        f"that many - it will not be scheduled. Add a bigger room, or switch this "
                        "subject out of merged batch mode."
                    )
                    continue
            else:
                shared_room_ids = None

            window = batch_window_by_subject.get(subject.id)
            forbidden = hard_forbidden_by_section.get(section.id, set())
            base_valid_starts = _valid_starts_excluding(
                slots, demand_duration, lunch_windows.get(section.id), forbidden, slots_by_index
            )
            if window:
                base_valid_starts = [
                    v for v in base_valid_starts
                    if set(occupied_indices(v, demand_duration, slots_by_index)) <= window
                ]
                if not base_valid_starts:
                    warnings.append(
                        f"{subject.name} for section {section.name} has a batch-scheduling-mode "
                        "constraint restricting it to a day/time window that no valid session fits "
                        "in - it will not be scheduled. Widen the window or shorten the session."
                    )
                    continue

            for batch in batches:
                batch_room_ids = shared_room_ids if shared_room_ids is not None else [
                    r for r in eligible_room_ids if rooms[r].capacity >= batch.strength
                ]
                valid_starts = base_valid_starts
                for i in range(num_sessions):
                    for p in range(parts_per_session):
                        demand_id = f"{subject.id}:{batch.id}:{i}" if parts_per_session == 1 else f"{subject.id}:{batch.id}:{i}:{p}"
                        demands.append(SessionDemand(
                            id=demand_id,
                            subject_id=subject.id, subject_name=subject.name, kind=subject.type,
                            audience_type="batch", audience_id=batch.id, parent_section_id=section.id,
                            session_index=i, duration=demand_duration,
                            room_type=subject.requires_room_type, equipment=subject.requires_equipment or [],
                            eligible_room_ids=batch_room_ids, eligible_teacher_ids=eligible_teacher_ids,
                            valid_start_slot_indices=valid_starts,
                            max_per_day=subject.max_per_day,
                            elective_group_id=elective_group_id,
                            batch_mode=batch_mode,
                        ))
        else:
            section_room_ids = [r for r in eligible_room_ids if rooms[r].capacity >= section.strength]
            forbidden = hard_forbidden_by_section.get(section.id, set())
            valid_starts = _valid_starts_excluding(
                slots, demand_duration, lunch_windows.get(section.id), forbidden, slots_by_index
            )
            for i in range(num_sessions):
                for p in range(parts_per_session):
                    demand_id = f"{subject.id}:{section.id}:{i}" if parts_per_session == 1 else f"{subject.id}:{section.id}:{i}:{p}"
                    demands.append(SessionDemand(
                        id=demand_id,
                        subject_id=subject.id, subject_name=subject.name, kind=subject.type,
                        audience_type="section", audience_id=section.id, parent_section_id=section.id,
                        session_index=i, duration=demand_duration,
                        room_type=subject.requires_room_type, equipment=subject.requires_equipment or [],
                        eligible_room_ids=section_room_ids, eligible_teacher_ids=eligible_teacher_ids,
                        valid_start_slot_indices=valid_starts,
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
        must_have_rules=set(must_have_rules or set()),
        soft_avoid_rules=soft_avoid_rules,
    )
    return problem, warnings
