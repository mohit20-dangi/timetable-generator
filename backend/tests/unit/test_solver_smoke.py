"""Hand-built ProblemData smoke test - no database involved. Exercises the
full build -> solve -> validate pipeline on a small, realistic instance
before any DB-backed code depends on it.
"""
from datetime import time as dtime

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.types import ProblemData, RoomInfo, TeacherInfo, SessionDemand
from app.solver.engine import solve_with_alternatives
from app.solver.validator import validate_schedule


def _make_calendar():
    raw = []
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        for period in range(1, 5):
            start_min = 9 * 60 + (period - 1) * 50
            raw.append({
                "day": day, "period_index": period,
                "start_time": dtime(start_min // 60, start_min % 60),
                "end_time": dtime((start_min + 50) // 60, (start_min + 50) % 60),
            })
    return build_slot_calendar(raw)


def test_small_instance_solves_and_validates_clean():
    slots = _make_calendar()

    rooms = {
        "LT1": RoomInfo(id="LT1", type="lecture", capacity=70),
        "LAB1": RoomInfo(id="LAB1", type="lab", capacity=30),
        "LAB2": RoomInfo(id="LAB2", type="lab", capacity=30),
    }
    teachers = {
        "t_sharma": TeacherInfo(id="t_sharma"),
        "t_verma": TeacherInfo(id="t_verma"),
    }

    demands = []
    # DBMS theory: 4 sessions/week, 1 period each, section-level
    for i in range(4):
        demands.append(SessionDemand(
            id=f"dbms:cse3a:{i}", subject_id="dbms", subject_name="DBMS",
            kind="theory", audience_type="section", audience_id="cse3a",
            parent_section_id="cse3a", session_index=i, duration=1,
            room_type="lecture", equipment=[], eligible_room_ids=["LT1"],
            eligible_teacher_ids=["t_sharma"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 1),
            max_per_day=1,
        ))
    # DBMS Lab: 1 session/week, 2-period block, two batches in parallel
    for batch in ["cse3a_b1", "cse3a_b2"]:
        demands.append(SessionDemand(
            id=f"dbms_lab:{batch}:0", subject_id="dbms_lab", subject_name="DBMS Lab",
            kind="lab", audience_type="batch", audience_id=batch,
            parent_section_id="cse3a", session_index=0, duration=2,
            room_type="lab", equipment=[], eligible_room_ids=["LAB1", "LAB2"],
            eligible_teacher_ids=["t_verma"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 2),
            max_per_day=1,
        ))

    problem = ProblemData(
        slots=slots, rooms=rooms, teachers=teachers, demands=demands,
        soft_weights={"minimize_student_gaps": 5, "balance_load_across_days": 5},
    )

    results = solve_with_alternatives(problem, max_seconds=30, num_workers=4, num_alternatives=1)
    assert len(results) == 1
    result = results[0]
    assert result.status in ("OPTIMAL", "FEASIBLE"), result.diagnostics
    assert len(result.sessions) == len(demands)

    violations = validate_schedule(problem, result.sessions)
    assert violations == [], [f"{v.type}: {v.message}" for v in violations]

    # This test doesn't weight parallel_lab_batches, so the two batches are
    # free to land at the same time or different times - both are valid.
    # If they DO land at the same time, distinct rooms is a hard
    # requirement (room eligibility + no-overlap), not a soft preference;
    # if they land at different times, sharing a room is legitimately fine.
    # The parallel-placement PREFERENCE itself is tested in isolation, with
    # nothing else competing in the objective, by
    # test_golden_regression.py::test_lab_batches_prefer_running_in_parallel_not_serialised.
    lab_sessions = [s for s in result.sessions if s.subject_id == "dbms_lab"]
    assert len(lab_sessions) == 2
    if lab_sessions[0].start_slot_index == lab_sessions[1].start_slot_index:
        assert lab_sessions[0].room_id != lab_sessions[1].room_id


def test_infeasible_when_teacher_insufficient_for_parallel_labs():
    """Two simultaneous lab batches need two eligible teachers. With only
    one, the model must be provably infeasible, not silently wrong."""
    slots = _make_calendar()
    rooms = {
        "LAB1": RoomInfo(id="LAB1", type="lab", capacity=30),
        "LAB2": RoomInfo(id="LAB2", type="lab", capacity=30),
    }
    teachers = {"t_verma": TeacherInfo(id="t_verma")}

    demands = []
    for batch in ["b1", "b2"]:
        demands.append(SessionDemand(
            id=f"lab:{batch}", subject_id="lab_subj", subject_name="Lab",
            kind="lab", audience_type="batch", audience_id=batch,
            parent_section_id="sec1", session_index=0, duration=1,
            room_type="lab", equipment=[], eligible_room_ids=["LAB1", "LAB2"],
            eligible_teacher_ids=["t_verma"],
            valid_start_slot_indices=[slots[0].index],  # force both into the SAME single slot
            max_per_day=1,
        ))

    problem = ProblemData(slots=slots, rooms=rooms, teachers=teachers, demands=demands)
    results = solve_with_alternatives(problem, max_seconds=10, num_workers=2, num_alternatives=1)
    assert results[0].status == "INFEASIBLE"


if __name__ == "__main__":
    test_small_instance_solves_and_validates_clean()
    print("test_small_instance_solves_and_validates_clean: PASS")
    test_infeasible_when_teacher_insufficient_for_parallel_labs()
    print("test_infeasible_when_teacher_insufficient_for_parallel_labs: PASS")
