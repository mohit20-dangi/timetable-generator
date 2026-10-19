"""A frozen booking (e.g. a teacher teaching first year) is a HARD constraint:
the solver must route around it and the independent validator must catch a
schedule that ignores it. Hand-built ProblemData, no database.
"""
from datetime import time as dtime

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.engine import solve_with_alternatives
from app.solver.types import FixedBooking, ProblemData, RoomInfo, ScheduledSession, SessionDemand, TeacherInfo
from app.solver.validator import validate_schedule


def _slots():
    raw = []
    for day in ("Mon", "Tue"):
        for period in range(1, 5):
            start = 9 * 60 + (period - 1) * 60
            raw.append({"day": day, "period_index": period,
                        "start_time": dtime(start // 60, 0), "end_time": dtime(start // 60 + 1, 0)})
    return build_slot_calendar(raw)


def _problem(fixed):
    slots = _slots()
    demand = SessionDemand(
        id="math:s1:0", subject_id="math", subject_name="Maths", kind="theory",
        audience_type="section", audience_id="s1", parent_section_id="s1", session_index=0, duration=1,
        room_type="lecture", equipment=[], eligible_room_ids=["r1"], eligible_teacher_ids=["t1"],
        valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
    )
    return ProblemData(
        slots=slots, rooms={"r1": RoomInfo(id="r1", type="lecture", capacity=60)},
        teachers={"t1": TeacherInfo(id="t1")}, demands=[demand], fixed_bookings=fixed,
    ), slots


def test_solver_never_uses_a_slot_the_teacher_is_already_booked_in():
    _, slots = _problem([])
    free = slots[5].index  # Tue period 2 is the only slot left
    booked = [FixedBooking("teacher", "t1", s.index, 1, "1st yr CO34_CN") for s in slots if s.index != free]
    problem, _ = _problem(booked)

    result = solve_with_alternatives(problem, max_seconds=20, num_workers=2, num_alternatives=1)[0]
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.sessions[0].start_slot_index == free
    assert validate_schedule(problem, result.sessions) == []


def test_a_locked_room_is_avoided_the_same_way():
    _, slots = _problem([])
    free = slots[2].index
    booked = [FixedBooking("room", "r1", s.index, 1, "LT102 first year") for s in slots if s.index != free]
    problem, _ = _problem(booked)
    result = solve_with_alternatives(problem, max_seconds=20, num_workers=2, num_alternatives=1)[0]
    assert result.sessions[0].start_slot_index == free


def test_everything_locked_is_infeasible_not_silently_overridden():
    _, slots = _problem([])
    booked = [FixedBooking("teacher", "t1", s.index, 1, "1st yr") for s in slots]
    problem, _ = _problem(booked)
    result = solve_with_alternatives(problem, max_seconds=20, num_workers=2, num_alternatives=1)[0]
    assert result.status == "INFEASIBLE"


def test_validator_flags_a_session_placed_on_a_frozen_slot():
    _, slots = _problem([])
    locked = slots[0]
    problem, _ = _problem([FixedBooking("teacher", "t1", locked.index, 1, "1st yr CO34_OS")])
    clash = ScheduledSession(
        demand_id="math:s1:0", subject_id="math", audience_type="section", audience_id="s1",
        parent_section_id="s1", start_slot_index=locked.index, duration=1, room_id="r1", teacher_id="t1",
    )
    violations = validate_schedule(problem, [clash])
    assert [v.type for v in violations] == ["FIXED_BOOKING_CLASH"]
    assert "1st yr CO34_OS" in violations[0].message

    elsewhere = ScheduledSession(**{**clash.__dict__, "start_slot_index": slots[1].index})
    assert validate_schedule(problem, [elsewhere]) == []


def test_validator_flags_a_two_period_session_that_overlaps_a_frozen_slot_partly():
    _, slots = _problem([])
    problem, _ = _problem([FixedBooking("teacher", "t1", slots[1].index, 1, "1st yr")])
    lab = ScheduledSession(
        demand_id="math:s1:0", subject_id="math", audience_type="section", audience_id="s1",
        parent_section_id="s1", start_slot_index=slots[0].index, duration=2, room_id="r1", teacher_id="t1",
    )
    assert "FIXED_BOOKING_CLASH" in {v.type for v in validate_schedule(problem, [lab])}
