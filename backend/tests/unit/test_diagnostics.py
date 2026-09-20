from datetime import time as dtime

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.types import ProblemData, RoomInfo, TeacherInfo, SessionDemand
from app.solver.diagnostics import preflight_checks


def _calendar():
    raw = [{"day": "Mon", "period_index": i, "start_time": dtime(9 + i, 0), "end_time": dtime(9 + i, 50)} for i in range(1, 4)]
    return build_slot_calendar(raw)


def test_no_time_slots_is_blocking():
    problem = ProblemData(slots=[], rooms={}, teachers={}, demands=[])
    issues = preflight_checks(problem)
    assert any(i.id == "no_time_slots" and i.severity == "blocking" for i in issues)


def test_demand_with_no_eligible_teacher_is_blocking_and_names_it():
    slots = _calendar()
    demand = SessionDemand(
        id="d1", subject_id="orphan", subject_name="Orphan Subject", kind="theory",
        audience_type="section", audience_id="sec1", parent_section_id="sec1",
        session_index=0, duration=1, room_type=None, equipment=[],
        eligible_room_ids=["R1"], eligible_teacher_ids=[],
        valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
    )
    problem = ProblemData(slots=slots, rooms={"R1": RoomInfo(id="R1", type="lecture", capacity=50)}, teachers={}, demands=[demand])
    issues = preflight_checks(problem)
    blocking = [i for i in issues if i.severity == "blocking"]
    assert any("Orphan Subject" in i.fact for i in blocking)


def test_sole_teacher_overload_is_named_with_arithmetic():
    """A teacher who is the ONLY option for more hours than their cap
    allows must be named specifically, with the actual numbers - this is
    the 'Prof. Sharma needs 31 hrs but is capped at 24' check."""
    slots = _calendar()
    teacher = TeacherInfo(id="t1", max_weekly_hours=2)
    demands = [
        SessionDemand(
            id=f"d{i}", subject_id=f"subj{i}", subject_name=f"Subject {i}", kind="theory",
            audience_type="section", audience_id="sec1", parent_section_id="sec1",
            session_index=0, duration=1, room_type=None, equipment=[],
            eligible_room_ids=["R1"], eligible_teacher_ids=["t1"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
        )
        for i in range(3)  # 3 hours of sole-teacher demand, cap is 2
    ]
    problem = ProblemData(
        slots=slots, rooms={"R1": RoomInfo(id="R1", type="lecture", capacity=50)},
        teachers={"t1": teacher}, demands=demands,
    )
    issues = preflight_checks(problem)
    overload = [i for i in issues if i.id.startswith("teacher_overloaded")]
    assert len(overload) == 1
    assert "3 hours" in overload[0].fact and "2 hours" in overload[0].fact


def test_insufficient_lab_teachers_flagged():
    slots = _calendar()
    demands = [
        SessionDemand(
            id=f"lab:{batch}", subject_id="lab_subj", subject_name="Lab", kind="lab",
            audience_type="batch", audience_id=batch, parent_section_id="sec1",
            session_index=0, duration=1, room_type="lab", equipment=[],
            eligible_room_ids=["L1", "L2"], eligible_teacher_ids=["t1"],  # only 1 teacher for 2 batches
            valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
        )
        for batch in ["b1", "b2"]
    ]
    problem = ProblemData(
        slots=slots,
        rooms={"L1": RoomInfo(id="L1", type="lab", capacity=30), "L2": RoomInfo(id="L2", type="lab", capacity=30)},
        teachers={"t1": TeacherInfo(id="t1")}, demands=demands,
    )
    issues = preflight_checks(problem)
    assert any(i.id.startswith("insufficient_lab_teachers") for i in issues)
