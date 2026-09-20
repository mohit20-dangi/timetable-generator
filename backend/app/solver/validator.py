"""Independent re-check of a solved schedule against every hard
constraint, written without reusing model_builder's constraint-building
code. This is deliberate: a bug shared between the model builder and its
checker would hide itself. The property that matters most in this whole
project is "for any schedule the solver calls feasible, this validator
finds zero violations" - see tests/unit/test_validator_property.py.
"""
from dataclasses import dataclass
from typing import List, Dict, Tuple

from app.solver.types import ProblemData, ScheduledSession
from app.solver.calendar import DAY_ORDER


@dataclass
class Violation:
    type: str
    message: str


def _occupied_range(session: ScheduledSession, slots_by_index: Dict[int, object]) -> Tuple[int, int, str]:
    """Returns (first_slot_index, last_slot_index, day) actually spanned.
    Independently walks forward from start rather than trusting duration
    blindly lines up with contiguous slots - if it doesn't, that's a
    CONTIGUITY_BROKEN violation, not a silent pass."""
    start = session.start_slot_index
    day = slots_by_index[start].day
    current = slots_by_index[start]
    last = start
    for _ in range(session.duration - 1):
        nxt = slots_by_index.get(last + 1)
        if nxt is None or nxt.day != current.day or nxt.start_minutes != current.end_minutes:
            return start, last, day  # contiguity actually broke; caller flags it
        last += 1
        current = nxt
    return start, last, day


def validate_schedule(problem: ProblemData, sessions: List[ScheduledSession]) -> List[Violation]:
    violations: List[Violation] = []
    slots_by_index = {s.index: s for s in problem.slots}
    demands_by_id = {d.id: d for d in problem.demands}

    # ---- every demand scheduled exactly once ----
    seen_demand_ids = [s.demand_id for s in sessions]
    expected_ids = {d.id for d in problem.demands}
    if set(seen_demand_ids) != expected_ids or len(seen_demand_ids) != len(set(seen_demand_ids)):
        missing = expected_ids - set(seen_demand_ids)
        duplicated = {i for i in seen_demand_ids if seen_demand_ids.count(i) > 1}
        for m in missing:
            violations.append(Violation("MISSING_SESSION", f"Demand {m} was never scheduled."))
        for d in duplicated:
            violations.append(Violation("DUPLICATE_SESSION", f"Demand {d} was scheduled more than once."))

    ranges = {}
    for session in sessions:
        first, last, day = _occupied_range(session, slots_by_index)
        if last - first + 1 != session.duration:
            violations.append(Violation(
                "CONTIGUITY_BROKEN",
                f"Session {session.demand_id} claims duration {session.duration} but only "
                f"{last - first + 1} contiguous periods actually exist from its start slot.",
            ))
        ranges[session.demand_id] = (first, last, day)

    def overlaps(a, b) -> bool:
        (a_first, a_last, a_day) = ranges[a.demand_id]
        (b_first, b_last, b_day) = ranges[b.demand_id]
        return a_day == b_day and a_first <= b_last and b_first <= a_last

    # ---- no room double-booked ----
    by_room: Dict[str, List[ScheduledSession]] = {}
    for s in sessions:
        by_room.setdefault(s.room_id, []).append(s)
    for room_id, group in by_room.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if overlaps(group[i], group[j]):
                    violations.append(Violation(
                        "ROOM_CLASH",
                        f"Room {room_id} double-booked: {group[i].demand_id} and {group[j].demand_id}.",
                    ))

    # ---- no teacher double-booked ----
    by_teacher: Dict[str, List[ScheduledSession]] = {}
    for s in sessions:
        by_teacher.setdefault(s.teacher_id, []).append(s)
    for teacher_id, group in by_teacher.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if overlaps(group[i], group[j]):
                    violations.append(Violation(
                        "TEACHER_CLASH",
                        f"Teacher {teacher_id} double-booked: {group[i].demand_id} and {group[j].demand_id}.",
                    ))

    # ---- audience clashes: section vs section, batch vs batch, batch vs parent section ----
    by_section_level: Dict[str, List[ScheduledSession]] = {}
    by_batch: Dict[str, List[ScheduledSession]] = {}
    for s in sessions:
        if s.audience_type == "section":
            by_section_level.setdefault(s.parent_section_id, []).append(s)
        else:
            by_batch.setdefault(s.audience_id, []).append(s)

    for section_id, group in by_section_level.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if overlaps(group[i], group[j]):
                    violations.append(Violation(
                        "SECTION_CLASH",
                        f"Section {section_id} double-booked: {group[i].demand_id} and {group[j].demand_id}.",
                    ))

    batch_to_section = {s.audience_id: s.parent_section_id for group in by_batch.values() for s in group}
    for batch_id, group in by_batch.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if overlaps(group[i], group[j]):
                    violations.append(Violation(
                        "BATCH_CLASH",
                        f"Batch {batch_id} double-booked: {group[i].demand_id} and {group[j].demand_id}.",
                    ))
        parent_section = batch_to_section.get(batch_id)
        for section_session in by_section_level.get(parent_section, []):
            for batch_session in group:
                if overlaps(section_session, batch_session):
                    violations.append(Violation(
                        "BATCH_CLASH",
                        f"Batch {batch_id} clashes with its own section's class "
                        f"({section_session.demand_id} vs {batch_session.demand_id}).",
                    ))

    # ---- room type / capacity / equipment ----
    for session in sessions:
        demand = demands_by_id.get(session.demand_id)
        room = problem.rooms.get(session.room_id)
        if not demand or not room:
            continue
        if demand.room_type and room.type != demand.room_type:
            violations.append(Violation(
                "ROOM_TYPE_MISMATCH",
                f"{session.demand_id} needs room type {demand.room_type} but got {room.type}.",
            ))
        if room.id not in demand.eligible_room_ids:
            violations.append(Violation(
                "ROOM_NOT_ELIGIBLE",
                f"{session.demand_id} was placed in room {room.id}, which was never in its eligible list.",
            ))
        missing_equipment = set(demand.equipment) - set(room.equipment)
        if missing_equipment:
            violations.append(Violation(
                "ROOM_EQUIPMENT_MISSING",
                f"Room {room.id} is missing {sorted(missing_equipment)} required by {session.demand_id}.",
            ))

    # ---- room / teacher availability windows ----
    for session in sessions:
        first, last, _day = ranges[session.demand_id]
        occupied = set(range(first, last + 1))
        room = problem.rooms.get(session.room_id)
        if room and occupied & room.unavailable_slot_indices:
            violations.append(Violation(
                "ROOM_UNAVAILABLE",
                f"Room {session.room_id} is unavailable during {session.demand_id}'s scheduled time.",
            ))
        teacher = problem.teachers.get(session.teacher_id)
        if teacher and occupied & teacher.unavailable_slot_indices:
            violations.append(Violation(
                "TEACHER_UNAVAILABLE",
                f"Teacher {session.teacher_id} is unavailable during {session.demand_id}'s scheduled time.",
            ))

    # ---- lunch window ----
    for session in sessions:
        demand = demands_by_id.get(session.demand_id)
        if not demand:
            continue
        window = problem.lunch_windows.get(demand.parent_section_id)
        if not window:
            continue
        lunch_start, lunch_end = window
        start_slot = slots_by_index[session.start_slot_index]
        first, last, _day = ranges[session.demand_id]
        end_slot = slots_by_index[last]
        if start_slot.start_minutes < lunch_end and lunch_start < end_slot.end_minutes:
            violations.append(Violation(
                "LUNCH_BREAK",
                f"{session.demand_id} overlaps the lunch window for section {demand.parent_section_id}.",
            ))

    # ---- teacher consistency per (subject, audience) ----
    by_group: Dict[Tuple[str, str], set] = {}
    for session in sessions:
        key = (session.subject_id, session.audience_id)
        by_group.setdefault(key, set()).add(session.teacher_id)
    for (subject_id, audience_id), teacher_ids in by_group.items():
        if len(teacher_ids) > 1:
            violations.append(Violation(
                "TEACHER_INCONSISTENT",
                f"Subject {subject_id} for {audience_id} is taught by {len(teacher_ids)} "
                f"different teachers ({sorted(teacher_ids)}) instead of one.",
            ))

    # ---- max sessions per day per (subject, audience) ----
    by_group_day: Dict[Tuple[str, str, str], int] = {}
    max_per_day_by_group: Dict[Tuple[str, str], int] = {}
    for session in sessions:
        demand = demands_by_id.get(session.demand_id)
        if not demand:
            continue
        key = (session.subject_id, session.audience_id)
        max_per_day_by_group[key] = demand.max_per_day
        _first, _last, day = ranges[session.demand_id]
        by_group_day[(*key, day)] = by_group_day.get((*key, day), 0) + 1
    for (subject_id, audience_id, day), count in by_group_day.items():
        cap = max_per_day_by_group.get((subject_id, audience_id), 1)
        if count > cap:
            violations.append(Violation(
                "MAX_PER_DAY_EXCEEDED",
                f"Subject {subject_id} for {audience_id} appears {count} times on {day} "
                f"(max allowed: {cap}).",
            ))

    # ---- elective basket synchronisation ----
    by_elective: Dict[Tuple[str, int], set] = {}
    for session in sessions:
        demand = demands_by_id.get(session.demand_id)
        if demand and demand.elective_group_id:
            key = (demand.elective_group_id, demand.session_index)
            by_elective.setdefault(key, set()).add(session.start_slot_index)
    for (group_id, idx), starts in by_elective.items():
        if len(starts) > 1:
            violations.append(Violation(
                "ELECTIVE_NOT_SYNCHRONISED",
                f"Elective group {group_id} session #{idx} has options starting at different times: {sorted(starts)}.",
            ))

    return violations
