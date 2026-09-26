"""Locks shut the specific defects observed in the previous build's real
"Run #28" PDF export (reviewed during planning): a subject repeated 3x in
one day, one subject taught by two different teachers for the same
section, an entirely empty day next to an overloaded one, and lab batches
serialised instead of run in parallel. Each test below reproduces the
conditions that produced that symptom and asserts it can no longer happen.
"""
from datetime import time as dtime

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.types import ProblemData, RoomInfo, TeacherInfo, SessionDemand
from app.solver.engine import solve_with_alternatives
from app.solver.validator import validate_schedule


def _week_calendar(periods_per_day=8):
    raw = []
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        for period in range(1, periods_per_day + 1):
            start_min = 9 * 60 + (period - 1) * 50
            raw.append({
                "day": day, "period_index": period,
                "start_time": dtime(start_min // 60, start_min % 60),
                "end_time": dtime((start_min + 50) // 60, (start_min + 50) % 60),
            })
    return build_slot_calendar(raw)


def test_subject_never_repeats_more_than_max_per_day():
    """Run #28 showed Operating Systems on Wed periods 3, 7, and 8 - three
    times in one day, with no cap. 5 sessions/week across 5 weekdays,
    max_per_day=1: plenty of room overall, but the ONLY way to satisfy it
    while respecting the cap is exactly one session per day - so this
    only proves something if max_per_day is actually enforced (an
    unconstrained solver could otherwise legally bunch several sessions
    into one day and leave another empty)."""
    slots = _week_calendar(periods_per_day=3)
    demands = [
        SessionDemand(
            id=f"os:sec1:{i}", subject_id="os", subject_name="Operating Systems", kind="theory",
            audience_type="section", audience_id="sec1", parent_section_id="sec1",
            session_index=i, duration=1, room_type=None, equipment=[],
            eligible_room_ids=["R1"], eligible_teacher_ids=["t1"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
        )
        for i in range(5)  # exactly 5 sessions/week - one per weekday, given the cap
    ]
    problem = ProblemData(
        slots=slots, rooms={"R1": RoomInfo(id="R1", type="lecture", capacity=50)},
        teachers={"t1": TeacherInfo(id="t1", max_daily_classes=8)}, demands=demands,
    )
    results = solve_with_alternatives(problem, max_seconds=15, num_workers=4, num_alternatives=1)
    assert results[0].status in ("OPTIMAL", "FEASIBLE")
    by_day = {}
    for s in results[0].sessions:
        day = slots[s.start_slot_index].day
        by_day[day] = by_day.get(day, 0) + 1
    assert max(by_day.values()) <= 1, f"A day had more than 1 OS session: {by_day}"


def test_one_subject_never_gets_two_different_teachers_for_same_section():
    """Run #28 showed DBMS for one section taught by Dr. Sen AND Prof.
    Sharma. With two eligible teachers and 4 sessions/week, the solver
    could easily split them across teachers if consistency weren't a hard
    constraint by construction."""
    slots = _week_calendar(periods_per_day=4)
    demands = [
        SessionDemand(
            id=f"dbms:sec1:{i}", subject_id="dbms", subject_name="DBMS", kind="theory",
            audience_type="section", audience_id="sec1", parent_section_id="sec1",
            session_index=i, duration=1, room_type=None, equipment=[],
            eligible_room_ids=["R1"], eligible_teacher_ids=["t_sen", "t_sharma"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
        )
        for i in range(4)
    ]
    problem = ProblemData(
        slots=slots, rooms={"R1": RoomInfo(id="R1", type="lecture", capacity=50)},
        teachers={"t_sen": TeacherInfo(id="t_sen"), "t_sharma": TeacherInfo(id="t_sharma")}, demands=demands,
    )
    results = solve_with_alternatives(problem, max_seconds=15, num_workers=4, num_alternatives=1)
    assert results[0].status in ("OPTIMAL", "FEASIBLE")
    teacher_ids = {s.teacher_id for s in results[0].sessions}
    assert len(teacher_ids) == 1, f"DBMS was split across teachers: {teacher_ids}"


def test_lab_batches_prefer_running_in_parallel_not_serialised():
    """Run #28 showed batch A2's lab on Monday and batch A1's lab on
    Friday - fully serialised, each batch idle while the other was in the
    lab. With the parallel_lab_batches soft constraint weighted, both
    batches should land in the SAME slot (different rooms)."""
    slots = _week_calendar(periods_per_day=4)
    demands = []
    for batch in ["b1", "b2"]:
        demands.append(SessionDemand(
            id=f"lab:{batch}", subject_id="lab_subj", subject_name="Lab", kind="lab",
            audience_type="batch", audience_id=batch, parent_section_id="sec1",
            session_index=0, duration=1, room_type="lab", equipment=[],
            eligible_room_ids=["L1", "L2"], eligible_teacher_ids=["t1", "t2"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
        ))
    problem = ProblemData(
        slots=slots,
        rooms={"L1": RoomInfo(id="L1", type="lab", capacity=30), "L2": RoomInfo(id="L2", type="lab", capacity=30)},
        teachers={"t1": TeacherInfo(id="t1"), "t2": TeacherInfo(id="t2")},
        demands=demands, soft_weights={"parallel_lab_batches": 20},
    )
    results = solve_with_alternatives(problem, max_seconds=15, num_workers=4, num_alternatives=1)
    assert results[0].status in ("OPTIMAL", "FEASIBLE")
    starts = {s.start_slot_index for s in results[0].sessions}
    assert len(starts) == 1, f"Lab batches were serialised instead of parallel: {starts}"

    violations = validate_schedule(problem, results[0].sessions)
    assert violations == []


def test_batch_mode_sequential_forces_batches_apart():
    """Phase 2.9: batch_mode="sequential" is a hard requirement that
    sibling batches never overlap - the inverse of "parallel". Only one
    shared room is offered, so the solver has no choice but to place them
    at different times."""
    slots = _week_calendar(periods_per_day=4)
    demands = []
    for batch in ["b1", "b2"]:
        demands.append(SessionDemand(
            id=f"lab:{batch}", subject_id="lab_subj", subject_name="Lab", kind="lab",
            audience_type="batch", audience_id=batch, parent_section_id="sec1",
            session_index=0, duration=1, room_type="lab", equipment=[],
            eligible_room_ids=["L1"], eligible_teacher_ids=["t1", "t2"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
            batch_mode="sequential",
        ))
    problem = ProblemData(
        slots=slots, rooms={"L1": RoomInfo(id="L1", type="lab", capacity=30)},
        teachers={"t1": TeacherInfo(id="t1"), "t2": TeacherInfo(id="t2")}, demands=demands,
    )
    results = solve_with_alternatives(problem, max_seconds=15, num_workers=4, num_alternatives=1)
    assert results[0].status in ("OPTIMAL", "FEASIBLE")
    starts = [s.start_slot_index for s in results[0].sessions]
    assert len(set(starts)) == 2, f"Sequential batches landed at the same slot: {starts}"

    violations = validate_schedule(problem, results[0].sessions)
    assert violations == []


def test_batch_mode_merged_shares_one_room_and_teacher():
    """Phase 2.9: batch_mode="merged" forces sibling batches onto the SAME
    slot, room AND teacher - taught as one combined class - rather than
    parallel's "same slot, different room". Only one room is offered, big
    enough for both batches combined, and it should end up used by both."""
    slots = _week_calendar(periods_per_day=4)
    demands = []
    for batch in ["b1", "b2"]:
        demands.append(SessionDemand(
            id=f"lab:{batch}", subject_id="lab_subj", subject_name="Lab", kind="lab",
            audience_type="batch", audience_id=batch, parent_section_id="sec1",
            session_index=0, duration=1, room_type="lab", equipment=[],
            eligible_room_ids=["BIG"], eligible_teacher_ids=["t1", "t2"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
            batch_mode="merged",
        ))
    problem = ProblemData(
        slots=slots, rooms={"BIG": RoomInfo(id="BIG", type="lab", capacity=60)},
        teachers={"t1": TeacherInfo(id="t1"), "t2": TeacherInfo(id="t2")}, demands=demands,
    )
    results = solve_with_alternatives(problem, max_seconds=15, num_workers=4, num_alternatives=1)
    assert results[0].status in ("OPTIMAL", "FEASIBLE")
    starts = {s.start_slot_index for s in results[0].sessions}
    rooms = {s.room_id for s in results[0].sessions}
    teachers = {s.teacher_id for s in results[0].sessions}
    assert len(starts) == 1, f"Merged batches didn't share a start slot: {starts}"
    assert len(rooms) == 1, f"Merged batches didn't share a room: {rooms}"
    assert len(teachers) == 1, f"Merged batches didn't share a teacher: {teachers}"

    violations = validate_schedule(problem, results[0].sessions)
    assert violations == []
