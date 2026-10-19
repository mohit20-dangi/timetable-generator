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
    ConstraintRule, LabRotationGroup,
)
from app.models.reservation import FIRST_YEAR_SOURCE
from app.services.department_calendar import department_time_slots
from app.services.entry_teachers import entry_teacher_ids
from app.services.section_attendance import Attendance, default_batch_id, list_attendance
from app.solver.types import (
    ProblemData, RoomInfo, TeacherInfo, SessionDemand, FixedBooking, SoftAvoidRule, CustomRule,
    RotationGroup,
)
from app.solver.calendar import build_slot_calendar, valid_starts_for_duration, occupied_indices
from app.solver.weights import resolve_rule_params


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


def _day_edge_starts(slots, lunch_windows, forbidden: set, slots_by_index) -> List[int]:
    """The first and last period of every day, where a self-study block may
    sit - never between two classes."""
    edges = set()
    by_day: Dict[str, List[int]] = {}
    for slot in slots:
        by_day.setdefault(slot.day, []).append(slot.index)
    for indices in by_day.values():
        edges.update({min(indices), max(indices)})
    allowed = set(_valid_starts_excluding(slots, 1, lunch_windows, forbidden, slots_by_index))
    return sorted(edges & allowed)


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


def _load_rotation_groups(
    db: Session, department_id: str, slots, target_section_ids: set,
    subjects_by_id: Dict[str, "Subject"], section_subject_pairs: set, warnings: List[str],
) -> Tuple[List[RotationGroup], Dict[Tuple[str, str], str]]:
    """Active LabRotationGroup rows for the sections being solved, turned
    into solver RotationGroups. Returns them plus a
    {(subject_id, section_id) -> group_id} lookup the demand builder uses
    to tag each member demand.

    A group is dropped - with a warning naming exactly what is wrong, never
    a bare "check your data" - rather than half-applied, because a rotation
    the solver silently ignores would look like it worked while quietly
    going back to the parallel-batches behaviour the admin was trying to
    get away from.
    """
    groups: List[RotationGroup] = []
    group_id_by_subject_section: Dict[Tuple[str, str], str] = {}
    if not target_section_ids:
        return groups, group_id_by_subject_section

    rows = (
        db.query(LabRotationGroup)
        .filter(
            LabRotationGroup.department_id == department_id,
            LabRotationGroup.is_active.is_(True),
            LabRotationGroup.section_id.in_(target_section_ids),
        )
        .all()
    )
    for row in rows:
        label = row.name or row.id
        subject_ids = [sid for sid in (row.subject_ids or [])]
        if len(subject_ids) < 2:
            warnings.append(
                f"Lab rotation '{label}' lists fewer than two subjects - a rotation needs at "
                "least two labs to swap between, so it was ignored."
            )
            continue

        bad = [sid for sid in subject_ids if sid not in subjects_by_id]
        if bad:
            warnings.append(
                f"Lab rotation '{label}' refers to subject(s) {', '.join(sorted(bad))}, which are "
                f"not scheduled for section {row.section_id} - the rotation was ignored."
            )
            continue
        unmapped = [sid for sid in subject_ids if (row.section_id, sid) not in section_subject_pairs]
        if unmapped:
            warnings.append(
                f"Lab rotation '{label}': section {row.section_id} does not take "
                f"{', '.join(sorted(unmapped))} - the rotation was ignored."
            )
            continue
        non_lab = [sid for sid in subject_ids if subjects_by_id[sid].type != "lab"]
        if non_lab:
            warnings.append(
                f"Lab rotation '{label}' includes non-lab subject(s) "
                f"{', '.join(sorted(non_lab))} - only lab subjects split into batches can "
                "rotate, so the rotation was ignored."
            )
            continue
        # One round is ONE shared block of time, so every lab in it must be
        # the same number of periods long; mixing a 2-period and a 3-period
        # lab has no consistent round length.
        lengths = {subjects_by_id[sid].periods_per_session or 1 for sid in subject_ids}
        if len(lengths) > 1:
            warnings.append(
                f"Lab rotation '{label}' mixes labs of different session lengths "
                f"({', '.join(str(x) for x in sorted(lengths))} periods) - every lab in a rotation "
                "must have the same periods_per_session, so the rotation was ignored."
            )
            continue

        allowed = None
        if row.day and row.start_time is not None and row.end_time is not None:
            start_min = _minutes(row.start_time)
            end_min = _minutes(row.end_time)
            allowed = {
                sl.index for sl in slots
                if sl.day == row.day and sl.start_minutes >= start_min and sl.end_minutes <= end_min
            }
            if not allowed:
                warnings.append(
                    f"Lab rotation '{label}' is pinned to {row.day} {row.start_time}-{row.end_time}, "
                    "which matches no configured time slot - the rotation was ignored."
                )
                continue

        clashing = [sid for sid in subject_ids if (row.section_id, sid) in group_id_by_subject_section]
        if clashing:
            warnings.append(
                f"Lab rotation '{label}' reuses subject(s) {', '.join(sorted(clashing))} already in "
                "another rotation for this section - a lab can only be in one rotation, so this "
                "group was ignored."
            )
            continue

        groups.append(RotationGroup(
            id=row.id, label=label, section_id=row.section_id,
            subject_ids=subject_ids, allowed_start_slot_indices=allowed,
        ))
        for sid in subject_ids:
            group_id_by_subject_section[(row.section_id, sid)] = row.id
    return groups, group_id_by_subject_section
CUSTOM_RULE_KINDS = {"subject_time_window", "max_subjects_per_day", "teacher_max_days_per_week"}


def _time_window_slot_indices(rule: "ConstraintRule", slots) -> set:
    """Like _rule_slot_indices, but a blank day means EVERY day (so "Maths
    only 08:00-12:00" doesn't have to be entered once per weekday)."""
    if rule.start_time is None or rule.end_time is None:
        return set()
    start_min, end_min = _minutes(rule.start_time), _minutes(rule.end_time)
    return {
        s.index for s in slots
        if (not rule.day or s.day == rule.day)
        and s.start_minutes >= start_min and s.end_minutes <= end_min
    }


def _build_custom_rule(rule: "ConstraintRule", slots, teachers, subject_ids, warnings) -> Optional[CustomRule]:
    """Resolves one admin-defined preference into solver terms, or warns and
    returns None if it points at something outside this solve's scope."""
    label = (rule.description or rule.id).replace(" ", "_")
    params = rule.params or {}
    hard = rule.priority == "hard"
    if rule.rule_type == "teacher_max_days_per_week" and rule.target_id not in teachers:
        return None  # teacher not relevant to this department's solve
    if rule.rule_type == "subject_time_window":
        if rule.target_id not in subject_ids:
            return None  # subject not taught in this scope
        slot_indices = _time_window_slot_indices(rule, slots)
        if not slot_indices:
            warnings.append(f"Rule '{rule.description or rule.id}' matches no configured time slots and was skipped.")
            return None
        return CustomRule(
            kind=rule.rule_type, hard=hard, weight=rule.weight, target_id=rule.target_id,
            slot_indices=slot_indices, mode=params.get("mode", "within"), label=label,
        )
    limit = params.get("max")
    if not isinstance(limit, int) or limit < 1:
        warnings.append(f"Rule '{rule.description or rule.id}' has no valid 'max' value and was skipped.")
        return None
    return CustomRule(
        kind=rule.rule_type, hard=hard, weight=rule.weight, target_id=rule.target_id,
        limit=limit, label=label,
    )


def _apply_constraint_rules(
    db: Session, department_id: str, slots, rooms: Dict[str, RoomInfo],
    teachers: Dict[str, TeacherInfo], warnings: List[str],
    custom_rules: Optional[List[CustomRule]] = None, subject_ids: Optional[set] = None,
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

        if rule.rule_type in CUSTOM_RULE_KINDS:
            if custom_rules is not None:
                built = _build_custom_rule(rule, slots, teachers, subject_ids or set(), warnings)
                if built is not None:
                    custom_rules.append(built)
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
            # Always hard, whatever an older row's stored priority says.
            teacher.unavailable_slot_indices |= slot_indices
        elif rule.rule_type == "room_unavailable":
            room = rooms.get(rule.target_id)
            if not room:
                continue
            room.unavailable_slot_indices |= slot_indices
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


def department_rooms(db: Session, department_id: str, slots, slots_by_index) -> Dict[str, RoomInfo]:
    """Rooms this department may use: its own, unowned ones, and rooms
    another department shares with it."""
    rooms: Dict[str, RoomInfo] = {}
    for room in db.query(Room).all():
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
    return rooms


def load_department_problem(
    db: Session,
    department_id: str,
    year_ids: Optional[List[str]] = None,
    section_ids: Optional[List[str]] = None,
    scope_mode: str = "fit_into_existing",
    soft_weights: Optional[Dict[str, int]] = None,
    must_have_rules: Optional[set] = None,
    subject_overrides: Optional[List[Dict]] = None,
    rule_params: Optional[Dict[str, int]] = None,
    locked_sessions: Optional[Dict[str, Dict]] = None,
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

    locked_sessions: a locked class kept from the run this one was forked
    from (see TimetableEntry.is_locked): {demand_id: {"day", "period",
    "teacher_id", "room_id"}}. The matching demand is pinned to that exact
    slot/teacher/room, so regenerating never moves it.
    """
    warnings: List[str] = []
    override_by_pair: Dict[Tuple[str, str], Dict] = {
        (o["section_id"], o["subject_id"]): o for o in (subject_overrides or [])
    }

    raw_slots = department_time_slots(db, department_id)
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

    rooms = department_rooms(db, department_id, slots, slots_by_index)

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
            # The first-year timetable is run centrally, so those hours are
            # already spoken for.
            max_weekly_hours=max(0, (teacher.max_weekly_hours or 0) - (teacher.first_year_hours or 0)),
            unavailable_slot_indices=teacher_unavailable_indices(teacher, slots),
            preferred_slot_indices=_teacher_preferred_indices(teacher, slots),
        )

    eligible_teachers_by_subject: Dict[str, List[str]] = {}
    main_teachers_by_subject: Dict[str, List[str]] = {}
    for row in teacher_subject_rows:
        eligible_teachers_by_subject.setdefault(row.subject_id, []).append(row.teacher_id)
        if (row.role or "main") == "main":
            main_teachers_by_subject.setdefault(row.subject_id, []).append(row.teacher_id)

    section_subject_elective: Dict[Tuple[str, str], Optional[str]] = {
        (row.section_id, row.subject_id): row.elective_group_id for row in section_subject_rows
    }

    # ---- repeater sections: a section that takes a subject by sitting in a
    # host section's class has no demand of its own - the HOST's class gets
    # the repeater as an extra attending section instead (see
    # SessionDemand.attending_section_ids). Links are kept when either end is
    # in scope: a repeater outside the scope still has to be kept clash-free
    # against a host being regenerated. ----
    attendance_links = list_attendance(db, target_section_ids)
    attendees_by_host: Dict[Tuple[str, str], List[Attendance]] = {}
    for link in attendance_links:
        if link.host_section_id in target_section_ids:
            attendees_by_host.setdefault((link.host_section_id, link.subject_id), []).append(link)
    repeater_sections = {
        s.id: s for s in db.query(Section).filter(
            Section.id.in_({link.repeater_section_id for link in attendance_links})
        ).all()
    } if attendance_links else {}

    # ---- fold in ConstraintRule rows (Phase 1.4) ----
    custom_rules: List[CustomRule] = []
    hard_forbidden_by_section, soft_avoid_rules, batch_mode_overrides, batch_window_by_subject = _apply_constraint_rules(
        db, department_id, slots, rooms, teachers, warnings,
        custom_rules=custom_rules, subject_ids=subject_ids_in_scope,
    )

    # ---- lab rotations (Phase 3.1): several lab subjects one section runs
    # as a rotation. Loaded before the demands so each member demand can be
    # tagged with its group; model_builder then schedules those demands in
    # shared rounds instead of applying batch_mode to them. ----
    rotation_groups, rotation_group_of = _load_rotation_groups(
        db, department_id, slots, target_section_ids, subjects,
        {(row.section_id, row.subject_id) for row in section_subject_rows}, warnings,
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
            # MOOC_NPTEL / INDUSTRY / SELF_STUDY never occupy a room or
            # teacher. A subject with self-study hours still holds its
            # section for those periods - at the very start or end of a
            # day, so the class never has a gap in the middle of it.
            if (subject.self_study_hours or 0) > 0 and not row.attends_with_section_id:
                forbidden = hard_forbidden_by_section.get(row.section_id, set())
                edge_starts = _day_edge_starts(slots, lunch_windows.get(row.section_id), forbidden, slots_by_index)
                if not edge_starts:
                    warnings.append(
                        f"{subject.name} for section {section.name if section else row.section_id}: no first or "
                        "last period of any day is free for its self-study periods."
                    )
                else:
                    for i in range(subject.self_study_hours):
                        demands.append(SessionDemand(
                            id=f"{subject.id}:{row.section_id}:{i}",
                            subject_id=subject.id, subject_name=subject.name, kind=subject.type,
                            audience_type="section", audience_id=row.section_id, parent_section_id=row.section_id,
                            session_index=i, duration=1, room_type=None, equipment=[],
                            eligible_room_ids=[], eligible_teacher_ids=[],
                            valid_start_slot_indices=edge_starts, max_per_day=1,
                            self_study=True,
                        ))
            continue
        if row.attends_with_section_id:
            continue  # a repeater section sitting in its host's class: no class of its own

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
        main_teacher_ids = [t for t in main_teachers_by_subject.get(subject.id, []) if t in eligible_teacher_ids]
        if main_teacher_ids and len(main_teacher_ids) < len(eligible_teacher_ids) and (subject.teachers_required or 1) <= 1:
            # One teacher per session: that is a main teacher. Secondary
            # teachers only ever assist someone else.
            eligible_teacher_ids = main_teacher_ids
        elective_group_id = section_subject_elective.get((row.section_id, row.subject_id)) or subject.elective_group_id

        # A lab that needs two supervisors on the floor asks for two
        # distinct teachers per session. Clamped at 1 (a column left NULL by
        # an older row, or a nonsense 0, must not silently mean "no teacher")
        # and warned about - never silently lowered to what happens to be
        # available - when fewer teachers are qualified than it asks for,
        # since that is a staffing fact the admin has to see.
        teachers_required = max(1, subject.teachers_required or 1)
        if teachers_required > len(eligible_teacher_ids):
            warnings.append(
                f"{subject.name} needs {teachers_required} teachers at once but only "
                f"{len(eligible_teacher_ids)} teacher(s) are qualified to teach it - qualify more "
                "teachers, or lower its 'teachers required' setting."
            )

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

            # A lab in a rotation is scheduled by the rotation itself, which
            # already fixes how its batches sit relative to one another (one
            # batch per round, each in a different lab). batch_mode only ever
            # describes ONE subject's batches, so leaving it on top would
            # either duplicate that or contradict it outright - "parallel"
            # would put every batch in this same lab at once, which is the
            # opposite of a rotation. It is dropped, loudly, not quietly.
            rotation_group_id = rotation_group_of.get((section.id, subject.id))
            if rotation_group_id:
                if batch_mode != "independent":
                    warnings.append(
                        f"{subject.name} is in a lab rotation for section {section.name}, so its "
                        f"'{batch_mode}' batch scheduling mode does not apply - the rotation decides "
                        "how its batches are placed."
                    )
                batch_mode = "independent"

            # Phase 2.9: "merged" means every batch is taught as ONE
            # combined class - same room, same teacher, same slot - so
            # every batch needs the SAME set of eligible rooms, each big
            # enough for the batches' COMBINED strength, not just its own.
            # A subject with only one batch can't meaningfully merge with
            # a sibling, so it falls back to ordinary per-batch capacity.
            attendees = attendees_by_host.get((section.id, subject.id), [])
            first_batch_id = default_batch_id(b.id for b in batches)
            attendee_ids_by_batch: Dict[str, List[str]] = {b.id: [] for b in batches}
            for link in attendees:
                target_batch = link.host_batch_id or first_batch_id
                if target_batch not in attendee_ids_by_batch:
                    warnings.append(
                        f"Repeater section {link.repeater_section_id} attends {subject.name} with a lab "
                        f"batch that doesn't exist in section {section.name} - it was not scheduled with them."
                    )
                    continue
                if link.host_batch_id is None:
                    warnings.append(
                        f"Repeater section {link.repeater_section_id} attends {subject.name} with section "
                        f"{section.name} but no lab batch was chosen - using batch {target_batch}."
                    )
                attendee_ids_by_batch[target_batch].append(link.repeater_section_id)
            extra_strength = sum(
                repeater_sections[rid].strength for ids in attendee_ids_by_batch.values() for rid in ids
                if rid in repeater_sections
            )

            if batch_mode == "merged" and len(batches) > 1:
                total_strength = sum(b.strength for b in batches) + extra_strength
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
            if rotation_group_id:
                # The rotation's own pinned window (if any) is applied to the
                # shared round start slots in model_builder; mirroring it on
                # the member demands' domains here is what lets the solver
                # prune before it ever branches, and lets the "no session
                # fits this window" warning below fire for a rotation too.
                rotation_window = next(
                    (g.allowed_start_slot_indices for g in rotation_groups if g.id == rotation_group_id), None
                )
                if rotation_window is not None:
                    window = (window & rotation_window) if window else set(rotation_window)
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
                batch_attendees = attendee_ids_by_batch[batch.id]
                batch_extra = sum(repeater_sections[rid].strength for rid in batch_attendees if rid in repeater_sections)
                batch_room_ids = shared_room_ids if shared_room_ids is not None else [
                    r for r in eligible_room_ids if rooms[r].capacity >= batch.strength + batch_extra
                ]
                if batch_attendees and not batch_room_ids:
                    warnings.append(
                        f"{subject.name} for section {section.name}: no eligible room seats batch "
                        f"{batch.batch_name} plus the repeater section(s) {', '.join(batch_attendees)} "
                        f"({batch.strength + batch_extra} students). Add a bigger room."
                    )
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
                            teachers_required=teachers_required,
                        main_teacher_ids=main_teacher_ids,
                            rotation_group_id=rotation_group_id,
                            attending_section_ids=list(batch_attendees),
                        ))
        else:
            attendee_ids = [link.repeater_section_id for link in attendees_by_host.get((section.id, subject.id), [])]
            attendee_strength = sum(repeater_sections[rid].strength for rid in attendee_ids if rid in repeater_sections)
            section_room_ids = [r for r in eligible_room_ids if rooms[r].capacity >= section.strength + attendee_strength]
            if attendee_ids and not section_room_ids:
                warnings.append(
                    f"{subject.name} for section {section.name}: no eligible room seats the section plus the "
                    f"repeater section(s) {', '.join(attendee_ids)} ({section.strength + attendee_strength} students). "
                    "Add a bigger room."
                )
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
                        teachers_required=teachers_required,
                        main_teacher_ids=main_teacher_ids,
                        attending_section_ids=list(attendee_ids),
                    ))

    # ---- repeater sections: classes a repeater already has in a published
    # timetable OUTSIDE this solve (its host's class in a section not being
    # regenerated, or its own classes when the repeater itself is not in scope)
    # are fixed, so anything the repeater attends in this solve must avoid
    # them. In "fresh" scope mode published timetables are ignored by design,
    # so there is nothing to avoid. ----
    section_busy: Dict[str, set] = {}
    published_rank1: Optional[List[GeneratedEntry]] = None

    def published_entries_rank1() -> List[GeneratedEntry]:
        nonlocal published_rank1
        if published_rank1 is None:
            published_rank1 = (
                db.query(GeneratedEntry)
                .join(TimetableRun, GeneratedEntry.timetable_run_id == TimetableRun.id)
                .filter(TimetableRun.is_published.is_(True))
                .filter(GeneratedEntry.alternative_rank == 1)
                .all()
            )
        return published_rank1

    if attendance_links:
        slot_index_by_dp_for_busy = {(s.day, s.period_index): s.index for s in slots}
        batch_parent = {b.id: b.section_id for b in db.query(LabBatch).all()}
        batch_ids_by_section: Dict[str, List[str]] = {}
        for batch_id, parent_id in batch_parent.items():
            batch_ids_by_section.setdefault(parent_id, []).append(batch_id)
        default_batch_for = {sid: default_batch_id(ids) for sid, ids in batch_ids_by_section.items()}
        repeater_ids = {link.repeater_section_id for link in attendance_links}
        published_hosts = set()  # (host section, subject) that has a published class
        if scope_mode == "fit_into_existing":
            for entry in published_entries_rank1():
                entry_section = entry.section_id or batch_parent.get(entry.batch_id)
                slot_index = slot_index_by_dp_for_busy.get((entry.day, entry.period))
                if slot_index is None or entry_section is None:
                    continue
                published_hosts.add((entry_section, entry.subject_id))
                if entry_section in target_section_ids:
                    continue  # being regenerated: the solver handles it, nothing fixed
                # the repeater's own published classes (it is out of scope)
                if entry_section in repeater_ids:
                    section_busy.setdefault(entry_section, set()).add(slot_index)
                # published host classes the repeater attends (host is out of scope)
                for link in attendance_links:
                    if link.host_section_id != entry_section or link.subject_id != entry.subject_id:
                        continue
                    if entry.batch_id and entry.batch_id != (link.host_batch_id or default_batch_for.get(entry_section)):
                        continue
                    section_busy.setdefault(link.repeater_section_id, set()).add(slot_index)
            for link in attendance_links:
                if link.host_section_id not in target_section_ids and (link.host_section_id, link.subject_id) not in published_hosts:
                    warnings.append(
                        f"Repeater section {link.repeater_section_id} attends {link.subject_id} with section "
                        f"{link.host_section_id}, which has no published timetable yet - publish that "
                        "section first, or this section's own classes may clash with it."
                    )
        # A repeater IN scope has classes of its own too: they must avoid the
        # published host classes it attends.
        for demand in demands:
            busy = section_busy.get(demand.parent_section_id)
            if busy and demand.parent_section_id in target_section_ids:
                demand.valid_start_slot_indices = [
                    v for v in demand.valid_start_slot_indices
                    if not (set(occupied_indices(v, demand.duration, slots_by_index)) & busy)
                ]

    # ---- pin locked classes carried over from the parent run ----
    if locked_sessions:
        slot_index_by_dp = {(s.day, s.period_index): s.index for s in slots}
        for demand in demands:
            pin = locked_sessions.get(demand.id)
            if not pin:
                continue
            start = slot_index_by_dp.get((pin.get("day"), pin.get("period")))
            if start is None or start not in demand.valid_start_slot_indices:
                warnings.append(f"A locked class ({demand.subject_name}) no longer fits its slot and was not kept locked.")
                continue
            demand.valid_start_slot_indices = [start]
            if pin.get("teacher_id") in teachers:
                demand.eligible_teacher_ids = [pin["teacher_id"]]
            if pin.get("room_id") in rooms:
                demand.eligible_room_ids = [pin["room_id"]]

    # ---- frozen bookings: explicit Reservations + already-published entries outside scope ----
    fixed_bookings: List[FixedBooking] = []
    slot_index_by_day_period = {(s.day, s.period_index): s.index for s in slots}

    # The central first-year timetable is outside this department's control,
    # so it binds every run - even a "fresh" one, which otherwise ignores
    # frozen bookings.
    reservation_query = db.query(Reservation).filter(Reservation.department_id == department_id)
    if scope_mode != "fit_into_existing":
        reservation_query = reservation_query.filter(Reservation.source == FIRST_YEAR_SOURCE)
    for reservation in reservation_query.all():
        slot_index = slot_index_by_day_period.get((reservation.day, reservation.period))
        if slot_index is None:
            continue
        fixed_bookings.append(FixedBooking(
            resource_type=reservation.resource_type, resource_id=reservation.resource_id,
            start_slot_index=slot_index, duration=1, reason=reservation.reason or "reserved",
        ))

    if scope_mode == "fit_into_existing":
        relevant_room_ids = set(rooms.keys())
        relevant_teacher_ids = set(teachers.keys())

        for entry in published_entries_rank1():
            if entry.section_id in target_section_ids:
                continue  # this entry belongs to the scope we're about to regenerate - not frozen
            slot_index = slot_index_by_day_period.get((entry.day, entry.period))
            if slot_index is None:
                continue
            for teacher_id in entry_teacher_ids(entry):
                if teacher_id not in relevant_teacher_ids:
                    continue
                fixed_bookings.append(FixedBooking(
                    resource_type="teacher", resource_id=teacher_id,
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
        section_busy_slot_indices={sid: idx for sid, idx in section_busy.items() if idx},
        must_have_rules=set(must_have_rules or set()),
        soft_avoid_rules=soft_avoid_rules,
        custom_rules=custom_rules,
        rule_params=resolve_rule_params(rule_params),
        rotation_groups=rotation_groups,
    )
    return problem, warnings


def apply_manual_blocks(problem: ProblemData, blocks: List[Dict], batch_section: Dict[str, str]) -> None:
    """Makes a regeneration respect classes an admin placed BY HAND (see
    app/services/timetable_editor.py), which have no solver demand of their
    own. blocks: [{"rows": [{day, period, section_id, batch_id, subject_id,
    teacher_id, room_id}, ...]}], one entry per block, one row per period.

    For each block, in the problem in place:
      * its teacher and room are frozen at those slots (FixedBooking), and
        the teacher's weekly cap is reduced by the periods it takes;
      * the class (section, or batch + its parent section) can't be given
        another class in those slots;
      * it counts toward its subject's weekly sessions: one matching demand
        is dropped, so a hand-added class doesn't quietly add hours on top
        of the subject's configured load; the rest of that subject for that
        audience keeps the block's teacher (one teacher per subject) and
        avoids days the block already uses up (max sessions per day).
    """
    slot_index = {(s.day, s.period_index): s.index for s in problem.slots}
    slots_by_index = {s.index: s for s in problem.slots}
    by_section: Dict[str, set] = {}
    by_batch: Dict[str, set] = {}
    used_days: Dict[Tuple[str, str], Dict[str, int]] = {}
    teacher_override: Dict[Tuple[str, str], str] = {}
    weekly_used: Dict[str, int] = {}

    for block in blocks:
        rows = block.get("rows") or []
        first = rows[0] if rows else None
        if not first:
            continue
        audience = first.get("batch_id") or first.get("section_id")
        for row in rows:
            i = slot_index.get((row["day"], row["period"]))
            if i is None:
                continue
            if row.get("teacher_id") in problem.teachers:
                problem.fixed_bookings.append(FixedBooking("teacher", row["teacher_id"], i, 1, "hand-placed class"))
                weekly_used[row["teacher_id"]] = weekly_used.get(row["teacher_id"], 0) + 1
            if row.get("room_id") in problem.rooms:
                problem.fixed_bookings.append(FixedBooking("room", row["room_id"], i, 1, "hand-placed class"))
            if row.get("batch_id"):
                by_batch.setdefault(row["batch_id"], set()).add(i)
            else:
                by_section.setdefault(row["section_id"], set()).add(i)
        days = used_days.setdefault((first.get("subject_id"), audience), {})
        days[first["day"]] = days.get(first["day"], 0) + 1
        if first.get("teacher_id"):
            teacher_override[(first.get("subject_id"), audience)] = first["teacher_id"]
        # consume one matching demand (prefer one of the same length)
        matches = [d for d in problem.demands if d.subject_id == first.get("subject_id") and d.audience_id == audience]
        matches.sort(key=lambda d: (d.duration != len(rows), d.session_index))
        if matches:
            problem.demands.remove(matches[0])

    for teacher_id, used in weekly_used.items():
        info = problem.teachers[teacher_id]
        info.max_weekly_hours = max(0, info.max_weekly_hours - used)

    batches_of_section: Dict[str, List[str]] = {}
    for batch_id, section_id in batch_section.items():
        batches_of_section.setdefault(section_id, []).append(batch_id)

    for d in problem.demands:
        forbidden: set = set()
        if d.audience_type == "section":
            forbidden |= by_section.get(d.audience_id, set())
            for batch_id in batches_of_section.get(d.audience_id, []):
                forbidden |= by_batch.get(batch_id, set())
        else:
            forbidden |= by_batch.get(d.audience_id, set()) | by_section.get(d.parent_section_id, set())
        key = (d.subject_id, d.audience_id)
        full_days = {day for day, n in used_days.get(key, {}).items() if n >= d.max_per_day}
        if forbidden or full_days:
            d.valid_start_slot_indices = [
                v for v in d.valid_start_slot_indices
                if slots_by_index[v].day not in full_days
                and not (set(occupied_indices(v, d.duration, slots_by_index)) & forbidden)
            ]
        teacher = teacher_override.get(key)
        if teacher and teacher in d.eligible_teacher_ids:
            d.eligible_teacher_ids = [teacher]
