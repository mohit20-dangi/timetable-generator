"""Builds the solver problem for remedial classes: extra classes for
low-attendance students, placed AROUND the published main timetable, which is
never touched. Free periods in the main timetable and the department's
remedial-only slots (after hours, a free Saturday) are the candidates; the
published classes' teachers, rooms and sections are frozen.

The result is an ordinary ProblemData, so the regular build_model/engine
solve it unchanged - app/solver/remedial_model.py adds the remedial-only rules.
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models import (
    AcademicYear, GeneratedEntry, LabBatch, RemedialEntry, RemedialGroup, RemedialRun, Reservation, Section,
    Subject, Teacher, TeacherSubject, TimetableRun,
)
from app.schemas.remedial import RemedialSettings
from app.services.department_calendar import REMEDIAL_SLOT, department_time_slots
from app.services.section_attendance import (
    by_host, default_batch_by_section, list_attendance, repeaters_attending,
)
from app.solver.calendar import build_slot_calendar
from app.solver.data_loader import (
    _minutes, _valid_starts_excluding, department_rooms, teacher_unavailable_indices,
)
from app.solver.diagnostics import DiagnosticIssue
from app.services.entry_teachers import entry_teacher_ids
from app.solver.types import FixedBooking, ProblemData, SessionDemand, TeacherInfo


@dataclass
class RemedialContext:
    """What remedial_model needs beyond ProblemData."""
    settings: RemedialSettings
    remedial_slot_indices: Set[int] = field(default_factory=set)
    # demand id -> start slots that fall in the MIDDLE of a member section's
    # day (a main class follows later); after-class and remedial-slot starts
    # are not listed.
    mid_day_starts: Dict[str, Set[int]] = field(default_factory=dict)
    # demand id -> teachers who regularly teach that subject to the group's sections
    regular_teachers: Dict[str, Set[str]] = field(default_factory=dict)
    # group id -> the group's sections
    group_sections: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class RemedialProblem:
    problem: ProblemData
    context: RemedialContext
    warnings: List[str] = field(default_factory=list)
    issues: List[DiagnosticIssue] = field(default_factory=list)  # severity "blocking" stops the run


def _blocking(issue_id: str, fact: str, suggestion: str) -> DiagnosticIssue:
    return DiagnosticIssue(issue_id, "blocking", fact, suggestion)


def load_remedial_problem(db: Session, department_id: str, settings: RemedialSettings) -> RemedialProblem:
    context = RemedialContext(settings=settings)
    empty = ProblemData(slots=[], rooms={}, teachers={}, demands=[])
    result = RemedialProblem(problem=empty, context=context)

    groups = (
        db.query(RemedialGroup)
        .filter(RemedialGroup.department_id == department_id, RemedialGroup.is_active.is_(True))
        .order_by(RemedialGroup.id).all()
    )
    if not groups:
        result.issues.append(_blocking(
            "no_groups", "There are no remedial groups to schedule.",
            "Add at least one remedial group (subject, sections, periods per week).",
        ))
        return result

    published_main = (
        db.query(TimetableRun)
        .filter(TimetableRun.department_id == department_id, TimetableRun.is_published.is_(True)).first()
    )
    if published_main is None:
        result.issues.append(_blocking(
            "no_published_timetable",
            "This department has no published main timetable, so there is nothing to build remedial classes around.",
            "Generate and publish the main timetable first.",
        ))
        return result

    # ---- slots: regular bell schedule plus the remedial-only periods ----
    raw_slots = department_time_slots(db, department_id, kind=None)
    remedial_keys = {(t.day, t.period_index) for t in raw_slots if t.slot_kind == REMEDIAL_SLOT}
    slots = build_slot_calendar([
        {"day": t.day, "period_index": t.period_index, "start_time": t.start_time, "end_time": t.end_time}
        for t in raw_slots
    ])
    slots_by_index = {s.index: s for s in slots}
    slot_index_by_dp = {(s.day, s.period_index): s.index for s in slots}
    context.remedial_slot_indices = {slot_index_by_dp[k] for k in remedial_keys if k in slot_index_by_dp}
    if not context.remedial_slot_indices and not settings.use_free_regular_slots:
        result.issues.append(_blocking(
            "no_remedial_slots",
            "No remedial slots are defined and free periods in the main timetable are switched off.",
            "Add remedial slots (e.g. after regular hours or on Saturday) or allow free regular periods.",
        ))
        return result

    rooms = department_rooms(db, department_id, slots, slots_by_index)

    # ---- the frozen main timetable (every department: teachers and rooms are shared) ----
    published_entries = (
        db.query(GeneratedEntry)
        .join(TimetableRun, GeneratedEntry.timetable_run_id == TimetableRun.id)
        .filter(TimetableRun.is_published.is_(True), GeneratedEntry.alternative_rank == 1)
        .all()
    )
    batch_parent = {b.id: b.section_id for b in db.query(LabBatch).all()}
    fixed_bookings: List[FixedBooking] = []
    section_busy: Dict[str, Set[int]] = {}
    last_main_slot: Dict[Tuple[str, str], int] = {}  # (section, day) -> last main-class slot index
    regular_teacher_by_section_subject: Dict[Tuple[str, str], Set[str]] = {}
    entries_by_host_subject: Dict[Tuple[str, str], List[Tuple[Optional[str], int, str]]] = {}
    for entry in published_entries:
        slot_index = slot_index_by_dp.get((entry.day, entry.period))
        if slot_index is None:
            continue
        # Every teacher in a published class is busy then, including the
        # second supervisor of a co-taught lab.
        for teacher_id in entry_teacher_ids(entry):
            fixed_bookings.append(FixedBooking("teacher", teacher_id, slot_index, 1, "main timetable"))
        if entry.room_id in rooms:
            fixed_bookings.append(FixedBooking("room", entry.room_id, slot_index, 1, "main timetable"))
        owner = entry.section_id or batch_parent.get(entry.batch_id)
        if owner is None:
            continue
        section_busy.setdefault(owner, set()).add(slot_index)
        key = (owner, entry.day)
        last_main_slot[key] = max(last_main_slot.get(key, -1), slot_index)
        if entry.subject_id and entry.teacher_id:
            regular_teacher_by_section_subject.setdefault((owner, entry.subject_id), set()).add(entry.teacher_id)
        if entry.subject_id:
            entries_by_host_subject.setdefault((owner, entry.subject_id), []).append(
                (entry.batch_id, slot_index, entry.day)
            )

    # Reservations and other departments' published remedial classes also freeze teachers/rooms.
    for reservation in db.query(Reservation).filter(Reservation.department_id == department_id).all():
        slot_index = slot_index_by_dp.get((reservation.day, reservation.period))
        if slot_index is not None:
            fixed_bookings.append(FixedBooking(
                reservation.resource_type, reservation.resource_id, slot_index, 1, reservation.reason or "reserved",
            ))
    other_remedial = (
        db.query(RemedialEntry).join(RemedialRun, RemedialEntry.remedial_run_id == RemedialRun.id)
        .filter(RemedialRun.is_published.is_(True), RemedialRun.department_id != department_id).all()
    )
    for entry in other_remedial:
        slot_index = slot_index_by_dp.get((entry.day, entry.period))
        if slot_index is None:
            continue
        for teacher_id in entry_teacher_ids(entry):
            fixed_bookings.append(FixedBooking(
                "teacher", teacher_id, slot_index, 1, "another department's remedial class",
            ))
        if entry.room_id in rooms:
            fixed_bookings.append(FixedBooking(
                "room", entry.room_id, slot_index, 1, "another department's remedial class",
            ))

    # A repeater section is also busy whenever it sits in a host's class.
    links_by_host = by_host(list_attendance(db))
    default_batch = default_batch_by_section(db)
    for (host_id, subject_id), host_entries in entries_by_host_subject.items():
        for batch_id, slot_index, day in host_entries:
            for repeater_id in repeaters_attending(links_by_host, default_batch, host_id, subject_id, batch_id):
                section_busy.setdefault(repeater_id, set()).add(slot_index)
                key = (repeater_id, day)
                last_main_slot[key] = max(last_main_slot.get(key, -1), slot_index)

    # ---- lunch per section ----
    sections = {s.id: s for s in db.query(Section).all()}
    years = {y.id: y for y in db.query(AcademicYear).all()}

    def lunch_for(section_id: str) -> Dict[str, Tuple[int, int]]:
        year = years.get(sections[section_id].year_id) if section_id in sections else None
        return {
            day: (_minutes(w[0]), _minutes(w[1]))
            for day, w in ((year.lunch_windows or {}) if year else {}).items() if w and len(w) == 2
        }

    # ---- teachers ----
    subjects = {s.id: s for s in db.query(Subject).filter(Subject.id.in_({g.subject_id for g in groups})).all()}
    qualified: Dict[str, List[str]] = {}
    for row in db.query(TeacherSubject).filter(TeacherSubject.subject_id.in_(list(subjects.keys()))).all():
        qualified.setdefault(row.subject_id, []).append(row.teacher_id)
    teacher_ids = {t for ts in qualified.values() for t in ts} | {g.teacher_id for g in groups if g.teacher_id}
    teachers: Dict[str, TeacherInfo] = {}
    for teacher in db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all():
        teachers[teacher.id] = TeacherInfo(
            id=teacher.id,
            max_continuous_classes=teacher.max_continuous_classes,
            # Only the remedial load is counted by the model; the main
            # timetable's load is already frozen via fixed bookings.
            max_daily_classes=settings.teacher_max_remedial_per_day,
            max_weekly_hours=settings.teacher_max_remedial_per_week,
            unavailable_slot_indices=teacher_unavailable_indices(teacher, slots),
        )

    # ---- demands ----
    demands: List[SessionDemand] = []
    lunch_windows: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for group in groups:
        subject = subjects.get(group.subject_id)
        if subject is None or not subject.is_schedulable:
            result.warnings.append(
                f"Remedial group {group.name}: its subject cannot be scheduled in a room and was skipped."
            )
            continue
        missing = [sid for sid in group.section_ids if sid not in sections]
        if missing:
            result.issues.append(_blocking(
                f"unknown_section:{group.id}", f"Remedial group {group.name} names unknown section(s) {missing}.",
                "Edit the group and pick existing sections.",
            ))
            continue
        context.group_sections[group.id] = list(group.section_ids)

        eligible_teachers = [group.teacher_id] if group.teacher_id else qualified.get(subject.id, [])
        eligible_teachers = [t for t in eligible_teachers if t in teachers]
        if not eligible_teachers:
            result.issues.append(_blocking(
                f"no_teacher:{group.id}", f"Remedial group {group.name} has no teacher who can teach {subject.name}.",
                f"Qualify a teacher for {subject.name} (Teacher-Subject mapping) or pick one for the group.",
            ))
            continue
        eligible_rooms = [
            r.id for r in rooms.values()
            if (subject.requires_room_type is None or r.type == subject.requires_room_type)
            and set(subject.requires_equipment or []) <= set(r.equipment)
            and r.capacity >= group.strength
        ]
        if not eligible_rooms:
            result.issues.append(_blocking(
                f"no_room:{group.id}",
                f"No room can seat remedial group {group.name} ({group.strength} students) for {subject.name}.",
                "Add a bigger room, or split the group.",
            ))
            continue

        # Lunch: the hull of every member section's window, per day.
        per_day: Dict[str, Tuple[int, int]] = {}
        for sid in group.section_ids:
            for day, (start, end) in lunch_for(sid).items():
                lo, hi = per_day.get(day, (start, end))
                per_day[day] = (min(lo, start), max(hi, end))
        lunch_windows[group.id] = per_day

        forbidden: Set[int] = set()
        for sid in group.section_ids:
            forbidden |= section_busy.get(sid, set())
        for index, slot in slots_by_index.items():
            if group.allowed_days and slot.day not in group.allowed_days:
                forbidden.add(index)
            if index not in context.remedial_slot_indices and not settings.use_free_regular_slots:
                forbidden.add(index)

        duration = group.periods_per_session
        valid_starts = _valid_starts_excluding(slots, duration, per_day, forbidden, slots_by_index)
        if not valid_starts:
            result.issues.append(_blocking(
                f"no_free_slot:{group.id}",
                f"Remedial group {group.name} has no free {duration}-period slot: every period is taken by "
                f"the main timetable for section(s) {', '.join(group.section_ids)}, falls in lunch, or is on an "
                "excluded day.",
                "Add remedial slots (after hours / Saturday), widen the allowed days, or allow free regular periods.",
            ))
            continue

        num_sessions = math.ceil(group.periods_per_week / duration)
        regular: Set[str] = set()
        for sid in group.section_ids:
            regular |= regular_teacher_by_section_subject.get((sid, subject.id), set())
        for i in range(num_sessions):
            demand_id = f"remedial:{group.id}:{i}"
            demands.append(SessionDemand(
                id=demand_id, subject_id=subject.id, subject_name=subject.name, kind=subject.type,
                audience_type="section", audience_id=group.id, parent_section_id=group.id,
                session_index=i, duration=duration,
                room_type=subject.requires_room_type, equipment=subject.requires_equipment or [],
                eligible_room_ids=eligible_rooms, eligible_teacher_ids=eligible_teachers,
                valid_start_slot_indices=valid_starts, max_per_day=settings.hard_max_per_day,
                attending_section_ids=list(group.section_ids),
            ))
            context.regular_teachers[demand_id] = regular & set(eligible_teachers)
            context.mid_day_starts[demand_id] = {
                v for v in valid_starts
                if v not in context.remedial_slot_indices
                and any(
                    last_main_slot.get((sid, slots_by_index[v].day), -1) > v
                    for sid in group.section_ids
                )
            }

    # ---- per-section capacity check: even the best placement can't beat this ----
    needed: Dict[str, int] = {}
    for demand in demands:
        for sid in demand.attending_section_ids:
            needed[sid] = needed.get(sid, 0) + demand.duration
    days_with_slots = {s.day for s in slots}
    for sid, periods in needed.items():
        ceiling = len(days_with_slots) * settings.hard_max_per_day
        if periods > ceiling:
            result.issues.append(_blocking(
                f"too_many_periods:{sid}",
                f"Section {sid} is asked to attend {periods} remedial periods a week, but the limit of "
                f"{settings.hard_max_per_day} a day over {len(days_with_slots)} days allows only {ceiling}.",
                "Reduce the groups' periods per week, or raise the per-day limit.",
            ))

    result.problem = ProblemData(
        slots=slots, rooms=rooms, teachers=teachers, demands=demands,
        fixed_bookings=fixed_bookings, lunch_windows=lunch_windows,
        section_busy_slot_indices={sid: idx for sid, idx in section_busy.items() if idx},
    )
    return result
