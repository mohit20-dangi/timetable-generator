"""Independent re-check of a solved schedule against every hard
constraint, written without reusing model_builder's constraint-building
code. This is deliberate: a bug shared between the model builder and its
checker would hide itself. The property that matters most in this whole
project is "for any schedule the solver calls feasible, this validator
finds zero violations" - see tests/unit/test_validator_property.py.
"""
from dataclasses import dataclass
from typing import List, Dict, Tuple

from app.solver.calendar import occupied_indices
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

    def same_elective_slot(a, b) -> bool:
        """Elective basket options sharing (elective_group_id,
        session_index) are REQUIRED to start together (see
        ELECTIVE_NOT_SYNCHRONISED below) - they must be exempted from the
        audience-overlap checks rather than flagged as a clash, or every
        basket with 2+ offered options fails this validator by
        construction (the model builder has the matching exception in
        _overlap_intervals_collapsing_electives)."""
        a_demand = demands_by_id.get(a.demand_id)
        b_demand = demands_by_id.get(b.demand_id)
        if not a_demand or not b_demand or not a_demand.elective_group_id:
            return False
        return (
            a_demand.elective_group_id == b_demand.elective_group_id
            and a_demand.session_index == b_demand.session_index
        )

    def same_merged_batch_group(a, b) -> bool:
        """Phase 2.9: lab batches whose subject is in "merged" mode are
        DELIBERATELY co-scheduled in the same room with the same teacher -
        model_builder forces that equality (see build_model's merged-batch
        block). Without this exemption every merged subject would fail
        this validator by construction, the same trap same_elective_slot
        above exists to avoid."""
        a_demand = demands_by_id.get(a.demand_id)
        b_demand = demands_by_id.get(b.demand_id)
        if not a_demand or not b_demand:
            return False
        if a_demand.audience_type != "batch" or b_demand.audience_type != "batch":
            return False
        if a_demand.batch_mode != "merged" or b_demand.batch_mode != "merged":
            return False
        return (
            a_demand.subject_id == b_demand.subject_id
            and a_demand.parent_section_id == b_demand.parent_section_id
        )

    # ---- no room double-booked ----
    by_room: Dict[str, List[ScheduledSession]] = {}
    for s in sessions:
        if s.room_id is None:
            continue
        by_room.setdefault(s.room_id, []).append(s)
    for room_id, group in by_room.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if overlaps(group[i], group[j]) and not same_merged_batch_group(group[i], group[j]):
                    violations.append(Violation(
                        "ROOM_CLASH",
                        f"Room {room_id} double-booked: {group[i].demand_id} and {group[j].demand_id}.",
                    ))

    # ---- no teacher double-booked ----
    # Every teacher of a co-taught session counts, not just teacher_ids[0]:
    # a second supervisor booked into two labs at once is exactly the kind
    # of clash this validator exists to catch, and reading teacher_id alone
    # would look clean while the timetable was unworkable.
    by_teacher: Dict[str, List[ScheduledSession]] = {}
    for s in sessions:
        for tid in s.teacher_ids:
            by_teacher.setdefault(tid, []).append(s)
    for teacher_id, group in by_teacher.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if overlaps(group[i], group[j]) and not same_merged_batch_group(group[i], group[j]):
                    violations.append(Violation(
                        "TEACHER_CLASH",
                        f"Teacher {teacher_id} double-booked: {group[i].demand_id} and {group[j].demand_id}.",
                    ))

    # ---- nothing may sit on a frozen booking (central first-year classes,
    # other departments' reservations). The solver enforces this too; this
    # is the independent re-check. ----
    for booking in problem.fixed_bookings:
        b_first = booking.start_slot_index
        b_last = b_first + booking.duration - 1
        b_day = slots_by_index[b_first].day if b_first in slots_by_index else None
        for s in sessions:
            owners = s.teacher_ids if booking.resource_type == "teacher" else [s.room_id]
            if booking.resource_id not in owners:
                continue
            s_first, s_last, s_day = ranges[s.demand_id]
            if s_day == b_day and s_first <= b_last and b_first <= s_last:
                violations.append(Violation(
                    "FIXED_BOOKING_CLASH",
                    f"{booking.resource_type.title()} {booking.resource_id} is already booked "
                    f"({booking.reason or 'reserved'}) at {b_day} slot {b_first}, "
                    f"but {s.demand_id} uses it.",
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
                if overlaps(group[i], group[j]) and not same_elective_slot(group[i], group[j]):
                    violations.append(Violation(
                        "SECTION_CLASH",
                        f"Section {section_id} double-booked: {group[i].demand_id} and {group[j].demand_id}.",
                    ))

    batch_to_section = {s.audience_id: s.parent_section_id for group in by_batch.values() for s in group}
    for batch_id, group in by_batch.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if overlaps(group[i], group[j]) and not same_elective_slot(group[i], group[j]):
                    violations.append(Violation(
                        "BATCH_CLASH",
                        f"Batch {batch_id} double-booked: {group[i].demand_id} and {group[j].demand_id}.",
                    ))
        parent_section = batch_to_section.get(batch_id)
        for section_session in by_section_level.get(parent_section, []):
            for batch_session in group:
                if overlaps(section_session, batch_session) and not same_elective_slot(section_session, batch_session):
                    violations.append(Violation(
                        "BATCH_CLASH",
                        f"Batch {batch_id} clashes with its own section's class "
                        f"({section_session.demand_id} vs {batch_session.demand_id}).",
                    ))

    # ---- attending sections: a section sitting in someone else's class (a
    # repeater in its host's class, a remedial group's member section) must
    # not also be in one of its own classes, another class it attends, or a
    # slot it is already committed to outside this solve. ----
    attended_by_section: Dict[str, List[ScheduledSession]] = {}
    for s in sessions:
        demand = demands_by_id.get(s.demand_id)
        for attending_id in (demand.attending_section_ids if demand else []):
            attended_by_section.setdefault(attending_id, []).append(s)
    for section_id, attended in attended_by_section.items():
        own = [
            s for s in sessions
            if (s.parent_section_id == section_id or s.audience_id == section_id)
            and s not in attended
        ]
        for i in range(len(attended)):
            for other in attended[i + 1:] + own:
                if overlaps(attended[i], other) and not same_elective_slot(attended[i], other):
                    violations.append(Violation(
                        "SECTION_CLASH",
                        f"Section {section_id} attends {attended[i].demand_id} but it overlaps "
                        f"{other.demand_id}.",
                    ))
        busy = problem.section_busy_slot_indices.get(section_id, set())
        for s in attended:
            first, last, _day = ranges[s.demand_id]
            if busy & set(range(first, last + 1)):
                violations.append(Violation(
                    "SECTION_CLASH",
                    f"Section {section_id} is already committed to another class during "
                    f"{s.demand_id}'s scheduled time.",
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
        for teacher_id in session.teacher_ids:
            teacher = problem.teachers.get(teacher_id)
            if teacher and occupied & teacher.unavailable_slot_indices:
                violations.append(Violation(
                    "TEACHER_UNAVAILABLE",
                    f"Teacher {teacher_id} is unavailable during {session.demand_id}'s scheduled time.",
                ))

    # ---- lunch window (per day - Phase 2.5) ----
    for session in sessions:
        demand = demands_by_id.get(session.demand_id)
        if not demand:
            continue
        first, last, day = ranges[session.demand_id]
        day_windows = problem.lunch_windows.get(demand.parent_section_id)
        window = day_windows.get(day) if day_windows else None
        if not window:
            continue
        lunch_start, lunch_end = window
        start_slot = slots_by_index[session.start_slot_index]
        end_slot = slots_by_index[last]
        if start_slot.start_minutes < lunch_end and lunch_start < end_slot.end_minutes:
            violations.append(Violation(
                "LUNCH_BREAK",
                f"{session.demand_id} overlaps the lunch window for section {demand.parent_section_id}.",
            ))

    # ---- teacher consistency per (subject, audience) ----
    # With teachers_required > 1 the promise is "the same TEAM every week",
    # so the whole set is compared, not just one name - two sessions sharing
    # a lead but swapping the second supervisor is still inconsistent.
    by_group: Dict[Tuple[str, str], set] = {}
    for session in sessions:
        key = (session.subject_id, session.audience_id)
        by_group.setdefault(key, set()).add(tuple(sorted(session.teacher_ids)))
    for (subject_id, audience_id), teams in by_group.items():
        if len(teams) > 1:
            violations.append(Violation(
                "TEACHER_INCONSISTENT",
                f"Subject {subject_id} for {audience_id} is taught by {len(teams)} "
                f"different sets of teachers ({sorted(teams)}) instead of one.",
            ))

    # ---- the right NUMBER of teachers, all of them eligible and distinct ----
    for session in sessions:
        demand = demands_by_id.get(session.demand_id)
        if not demand or demand.self_study:
            continue
        teacher_ids = session.teacher_ids
        if len(set(teacher_ids)) != len(teacher_ids):
            violations.append(Violation(
                "TEACHER_DUPLICATED",
                f"{session.demand_id} lists the same teacher more than once ({teacher_ids}).",
            ))
        if len(set(teacher_ids)) != max(1, demand.teachers_required):
            violations.append(Violation(
                "TEACHER_COUNT_WRONG",
                f"{session.demand_id} needs {max(1, demand.teachers_required)} teacher(s) at once "
                f"but was given {len(set(teacher_ids))} ({sorted(teacher_ids)}).",
            ))
        not_eligible = sorted(set(teacher_ids) - set(demand.eligible_teacher_ids))
        if not_eligible:
            violations.append(Violation(
                "TEACHER_NOT_ELIGIBLE",
                f"{session.demand_id} was given teacher(s) {not_eligible}, who are not qualified "
                "to teach it.",
            ))
        if demand.main_teacher_ids and not set(teacher_ids) & set(demand.main_teacher_ids):
            violations.append(Violation(
                "NO_MAIN_TEACHER",
                f"{session.demand_id} has only secondary teachers ({sorted(teacher_ids)}); a main "
                "teacher must run it.",
            ))

    # ---- self-study blocks sit only in the first or last period of a day ----
    first_of_day: Dict[str, int] = {}
    last_of_day: Dict[str, int] = {}
    for slot in problem.slots:
        first_of_day[slot.day] = min(first_of_day.get(slot.day, slot.index), slot.index)
        last_of_day[slot.day] = max(last_of_day.get(slot.day, slot.index), slot.index)
    for session in sessions:
        demand = demands_by_id.get(session.demand_id)
        if not demand or not demand.self_study:
            continue
        day = slots_by_index[session.start_slot_index].day
        if session.start_slot_index not in (first_of_day[day], last_of_day[day]):
            violations.append(Violation(
                "SELF_STUDY_MID_DAY",
                f"{session.demand_id} is self study but sits in the middle of {day}.",
            ))

    # ---- lab rotations: in every round each batch is in a different lab,
    # and each lab holds at most one batch. Re-derived straight from the
    # finished schedule rather than trusting the model builder's rounds. ----
    violations.extend(_validate_rotations(problem, sessions, demands_by_id, ranges))

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
    # Keyed by (group, session_index, parent_section_id), matching what the
    # model builder actually promises. Co-scheduling a basket is a per-cohort
    # guarantee - "a student who picked any option never clashes with THEIR
    # OWN core subjects" - not a college-wide one, and the same basket is
    # routinely offered to several sections. Without parent_section_id here
    # this check demanded that every section's occurrence of a shared basket
    # land on one global slot, which the model deliberately does not do, so
    # every reused basket was reported as a violation of a rule that was
    # never enforced. See model_builder's by_elective_slot block.
    by_elective: Dict[Tuple[str, int, str], set] = {}
    for session in sessions:
        demand = demands_by_id.get(session.demand_id)
        if demand and demand.elective_group_id:
            key = (demand.elective_group_id, demand.session_index, demand.parent_section_id)
            by_elective.setdefault(key, set()).add(session.start_slot_index)
    for (group_id, idx, section_id), starts in by_elective.items():
        if len(starts) > 1:
            violations.append(Violation(
                "ELECTIVE_NOT_SYNCHRONISED",
                f"Elective group {group_id} session #{idx} has options starting at different times "
                f"for section {section_id}: {sorted(starts)}.",
            ))

    violations.extend(_validate_custom_rules(problem, sessions, slots_by_index, demands_by_id, ranges))
    return violations


def _validate_rotations(problem, sessions, demands_by_id, ranges) -> List[Violation]:
    """Independent re-check of every LabRotationGroup, derived from where
    the classes actually ended up rather than from the round variables the
    model builder used. Two things have to hold, and each one is a real
    failure mode rather than a formality:

      * within one round, no two batches are in the SAME lab - if they were,
        that lab would need two qualified teachers and two rooms at that
        moment, which is the staffing wall rotations exist to avoid;
      * over the whole rotation, every batch does every lab exactly once -
        otherwise some batch quietly never gets taught one of its subjects.

    A "round" is read back as a start slot: every member of a rotation that
    begins at the same slot is in the same round, by construction.
    """
    out: List[Violation] = []
    sessions_by_demand = {s.demand_id: s for s in sessions}
    for rotation in problem.rotation_groups:
        members = [
            d for d in problem.demands
            if d.rotation_group_id == rotation.id and d.audience_type == "batch"
        ]
        if not members:
            continue
        by_round: Dict[int, List] = {}
        done: Dict[str, List[str]] = {}
        for demand in members:
            session = sessions_by_demand.get(demand.id)
            if not session:
                continue  # already reported as MISSING_SESSION
            by_round.setdefault(session.start_slot_index, []).append((demand, session))
            done.setdefault(demand.audience_id, []).append(demand.subject_id)

        for start_slot, pairs in sorted(by_round.items()):
            subjects_seen: Dict[str, str] = {}
            batches_seen: Dict[str, str] = {}
            for demand, _session in pairs:
                clash = subjects_seen.get(demand.subject_id)
                if clash is not None:
                    out.append(Violation(
                        "ROTATION_SUBJECT_REPEATED",
                        f"Lab rotation '{rotation.label}': batches {clash} and {demand.audience_id} "
                        f"are both in {demand.subject_id} at slot {start_slot} - in a rotation each "
                        "lab runs with one batch at a time.",
                    ))
                subjects_seen[demand.subject_id] = demand.audience_id
                if demand.audience_id in batches_seen:
                    out.append(Violation(
                        "ROTATION_BATCH_REPEATED",
                        f"Lab rotation '{rotation.label}': batch {demand.audience_id} is in two "
                        f"labs at slot {start_slot}.",
                    ))
                batches_seen[demand.audience_id] = demand.subject_id

        expected = sorted(rotation.subject_ids)
        for batch_id, subject_ids in sorted(done.items()):
            missing = sorted(set(expected) - set(subject_ids))
            if missing:
                out.append(Violation(
                    "ROTATION_INCOMPLETE",
                    f"Lab rotation '{rotation.label}': batch {batch_id} never does "
                    f"{', '.join(missing)}.",
                ))
    return out


def _validate_custom_rules(problem, sessions, slots_by_index, demands_by_id, ranges) -> List[Violation]:
    """Re-checks every HARD admin-defined rule (app/solver/custom_rules.py)
    directly against the finished schedule - independently of how the model
    builder encoded it. Soft rules are preferences and are never violations."""
    out: List[Violation] = []
    for rule in problem.custom_rules:
        if not rule.hard:
            continue
        if rule.kind == "subject_time_window":
            for s in sessions:
                if s.subject_id != rule.target_id:
                    continue
                occupied = set(occupied_indices(s.start_slot_index, s.duration, slots_by_index))
                bad = not occupied <= rule.slot_indices if rule.mode == "within" else bool(occupied & rule.slot_indices)
                if bad:
                    out.append(Violation(
                        "CUSTOM_TIME_WINDOW",
                        f"{s.demand_id} breaks the rule '{rule.label}' ({rule.mode} the allowed window).",
                    ))
        elif rule.kind == "max_subjects_per_day":
            per_day: Dict[Tuple[str, str], set] = {}
            for s in sessions:
                if rule.target_id not in ("*", s.parent_section_id):
                    continue
                demand = demands_by_id.get(s.demand_id)
                key = (demand.elective_group_id if demand and demand.elective_group_id else s.subject_id)
                per_day.setdefault((s.parent_section_id, ranges[s.demand_id][2]), set()).add(key)
            for (section_id, day), subjects in per_day.items():
                if len(subjects) > rule.limit:
                    out.append(Violation(
                        "CUSTOM_MAX_SUBJECTS_PER_DAY",
                        f"Section {section_id} has {len(subjects)} different subjects on {day} "
                        f"(rule '{rule.label}' allows {rule.limit}).",
                    ))
        elif rule.kind == "teacher_max_days_per_week":
            days = {ranges[s.demand_id][2] for s in sessions if rule.target_id in s.teacher_ids}
            days |= {
                slots_by_index[b.start_slot_index].day for b in problem.fixed_bookings
                if b.resource_type == "teacher" and b.resource_id == rule.target_id
                and b.start_slot_index in slots_by_index
            }
            if len(days) > rule.limit:
                out.append(Violation(
                    "CUSTOM_TEACHER_MAX_DAYS",
                    f"Teacher {rule.target_id} teaches on {len(days)} days (rule '{rule.label}' allows {rule.limit}).",
                ))
    return out
