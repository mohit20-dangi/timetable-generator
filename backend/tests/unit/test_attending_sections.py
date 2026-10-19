"""A section that attends another section's class (a repeater in its host's
class) must never be double-booked, and must avoid slots it is already
committed to outside the solve."""
from datetime import time as dtime

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.engine import solve_with_alternatives
from app.solver.types import ProblemData, RoomInfo, SessionDemand, TeacherInfo
from app.solver.validator import validate_schedule


def _slots(days=("Mon", "Tue"), periods=3):
    raw = []
    for day in days:
        for period in range(1, periods + 1):
            start = 9 * 60 + (period - 1) * 50
            raw.append({
                "day": day, "period_index": period,
                "start_time": dtime(start // 60, start % 60),
                "end_time": dtime((start + 50) // 60, (start + 50) % 60),
            })
    return build_slot_calendar(raw)


def _demand(slots, demand_id, subject, section, attending=(), room="R1", teacher="t1"):
    return SessionDemand(
        id=demand_id, subject_id=subject, subject_name=subject, kind="theory",
        audience_type="section", audience_id=section, parent_section_id=section,
        session_index=0, duration=1, room_type=None, equipment=[],
        eligible_room_ids=[room], eligible_teacher_ids=[teacher],
        valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
        attending_section_ids=list(attending),
    )


def _problem(slots, demands, busy=None):
    return ProblemData(
        slots=slots,
        rooms={"R1": RoomInfo(id="R1", type="lecture", capacity=80), "R2": RoomInfo(id="R2", type="lecture", capacity=80)},
        teachers={"t1": TeacherInfo(id="t1"), "t2": TeacherInfo(id="t2")},
        demands=demands, section_busy_slot_indices=busy or {},
    )


def test_attended_classes_never_overlap_for_the_repeater_section():
    slots = _slots(periods=2)  # 4 slots, 3 demands for the repeater: must use 3 distinct slots
    demands = [
        _demand(slots, "x:A:0", "x", "A", attending=["R"], room="R1", teacher="t1"),
        _demand(slots, "y:B:0", "y", "B", attending=["R"], room="R2", teacher="t2"),
        _demand(slots, "z:R:0", "z", "R", room="R1", teacher="t1"),
    ]
    problem = _problem(slots, demands)
    result = solve_with_alternatives(problem, max_seconds=10, num_workers=1)[0]
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert validate_schedule(problem, result.sessions) == []
    starts = {s.demand_id: s.start_slot_index for s in result.sessions}
    assert len({starts["x:A:0"], starts["y:B:0"], starts["z:R:0"]}) == 3


def test_attended_class_avoids_slots_the_section_is_already_committed_to():
    slots = _slots(periods=2)
    demands = [_demand(slots, "x:A:0", "x", "A", attending=["R"])]
    busy = {"R": {slots[0].index, slots[1].index, slots[2].index}}
    problem = _problem(slots, demands, busy=busy)
    result = solve_with_alternatives(problem, max_seconds=10, num_workers=1)[0]
    assert result.sessions[0].start_slot_index == slots[3].index
    assert validate_schedule(problem, result.sessions) == []


def test_validator_flags_an_attending_clash():
    slots = _slots()
    demands = [
        _demand(slots, "x:A:0", "x", "A", attending=["R"], room="R1", teacher="t1"),
        _demand(slots, "z:R:0", "z", "R", room="R2", teacher="t2"),
    ]
    problem = _problem(slots, demands)
    from app.solver.types import ScheduledSession
    sessions = [
        ScheduledSession("x:A:0", "x", "section", "A", "A", slots[0].index, 1, "R1", "t1"),
        ScheduledSession("z:R:0", "z", "section", "R", "R", slots[0].index, 1, "R2", "t2"),
    ]
    assert any(v.type == "SECTION_CLASH" for v in validate_schedule(problem, sessions))
