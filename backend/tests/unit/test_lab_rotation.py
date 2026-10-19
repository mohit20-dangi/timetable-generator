"""Phase 3.1: lab rotations and co-taught labs.

The failure these exist to prevent is a real one an admin hit: three lab
batches, three lab subjects, two qualified teachers per subject, and a
blocking "3 batches, only 2 teachers" every time. The old model could only
express "all three batches in the SAME lab at once" (batch_scheduling_mode
= parallel), which genuinely does need three teachers. A rotation runs the
three batches in three DIFFERENT labs at once, so one teacher per lab is
enough - and that has to be true of the model, the diagnostics and the
independent validator alike, not just of the docstrings.
"""
from datetime import time as dtime

import pytest

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.types import (
    ProblemData, RoomInfo, TeacherInfo, SessionDemand, RotationGroup, ScheduledSession,
)
from app.solver.engine import solve_with_alternatives
from app.solver.validator import validate_schedule
from app.solver.diagnostics import preflight_checks


def _week_calendar(periods_per_day=8):
    raw = []
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        for period in range(1, periods_per_day + 1):
            start_min = 9 * 60 + (period - 1) * 60
            raw.append({
                "day": day, "period_index": period,
                "start_time": dtime(start_min // 60, start_min % 60),
                "end_time": dtime((start_min + 60) // 60, (start_min + 60) % 60),
            })
    return build_slot_calendar(raw)


def _rotation_problem(slots, duration=2, rotation_window=None, teachers_per_subject=1):
    """Three labs x three batches of one section, as a rotation. Each
    subject deliberately has only `teachers_per_subject` qualified
    teacher(s) - the exact staffing that made the old parallel-batches
    model infeasible."""
    subjects = ["cn_lab", "dbms_lab", "oops_lab"]
    batches = ["A1", "A2", "A3"]
    demands = []
    for subject_id in subjects:
        teacher_ids = [f"t_{subject_id}_{i}" for i in range(teachers_per_subject)]
        for batch_id in batches:
            demands.append(SessionDemand(
                id=f"{subject_id}:{batch_id}:0", subject_id=subject_id,
                subject_name=subject_id.upper(), kind="lab",
                audience_type="batch", audience_id=batch_id, parent_section_id="sec3a",
                session_index=0, duration=duration, room_type="lab", equipment=[],
                eligible_room_ids=["L1", "L2", "L3"], eligible_teacher_ids=teacher_ids,
                valid_start_slot_indices=valid_starts_for_duration(slots, duration),
                max_per_day=1, rotation_group_id="rot1",
                teachers_required=teachers_per_subject,
            ))
    teachers = {
        f"t_{s}_{i}": TeacherInfo(id=f"t_{s}_{i}", max_daily_classes=8, max_continuous_classes=8)
        for s in subjects for i in range(teachers_per_subject)
    }
    return ProblemData(
        slots=slots,
        rooms={r: RoomInfo(id=r, type="lab", capacity=40) for r in ["L1", "L2", "L3"]},
        teachers=teachers, demands=demands,
        rotation_groups=[RotationGroup(
            id="rot1", label="3rd year A labs", section_id="sec3a",
            subject_ids=subjects, allowed_start_slot_indices=rotation_window,
        )],
    )


def test_rotation_schedules_three_labs_with_one_teacher_each():
    """The headline case. Three 3-batch labs, ONE qualified teacher each -
    which the old parallel-batches model declared impossible - must now
    solve, and must come out as a proper rotation: in every round the three
    batches are in three different labs, and every batch does every lab."""
    slots = _week_calendar()
    problem = _rotation_problem(slots)
    results = solve_with_alternatives(problem, max_seconds=30, num_workers=4)
    assert results[0].status in ("OPTIMAL", "FEASIBLE"), results[0].diagnostics
    assert validate_schedule(problem, results[0].sessions) == []

    by_start = {}
    for session in results[0].sessions:
        by_start.setdefault(session.start_slot_index, []).append(session)
    # Three rounds, each holding all three batches in three distinct labs.
    assert len(by_start) == 3, f"expected 3 rotation rounds, got {sorted(by_start)}"
    for start, group in by_start.items():
        assert len(group) == 3
        assert len({s.subject_id for s in group}) == 3, f"a lab ran twice at once at slot {start}"
        assert len({s.audience_id for s in group}) == 3
        assert len({s.room_id for s in group}) == 3
    # ...and over the week every batch has done every lab exactly once.
    for batch_id in ["A1", "A2", "A3"]:
        done = sorted(s.subject_id for s in results[0].sessions if s.audience_id == batch_id)
        assert done == ["cn_lab", "dbms_lab", "oops_lab"]


def test_rotation_honours_a_pinned_window():
    """"Monday 14:00-16:00" has to actually mean it. With a window only big
    enough for the rotation's rounds, every single lab lands inside it."""
    slots = _week_calendar()
    monday = [s for s in slots if s.day == "Mon"]
    window = {s.index for s in monday[:6]}  # three 2-period rounds, Monday only
    problem = _rotation_problem(slots, rotation_window=window)
    results = solve_with_alternatives(problem, max_seconds=30, num_workers=4)
    assert results[0].status in ("OPTIMAL", "FEASIBLE"), results[0].diagnostics
    assert validate_schedule(problem, results[0].sessions) == []
    for session in results[0].sessions:
        assert session.start_slot_index in window
        assert slots[session.start_slot_index].day == "Mon"


def test_rotation_with_more_batches_than_rounds_is_rejected_with_a_readable_reason():
    """Four batches through three lab sessions cannot work - two batches
    would share a lab. That must be said in words before the solver is
    asked, not returned as a bare INFEASIBLE."""
    slots = _week_calendar()
    problem = _rotation_problem(slots)
    extra = [
        SessionDemand(
            id=f"{subject_id}:A4:0", subject_id=subject_id, subject_name=subject_id.upper(),
            kind="lab", audience_type="batch", audience_id="A4", parent_section_id="sec3a",
            session_index=0, duration=2, room_type="lab", equipment=[],
            eligible_room_ids=["L1", "L2", "L3"],
            eligible_teacher_ids=[f"t_{subject_id}_0"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 2),
            max_per_day=1, rotation_group_id="rot1",
        )
        for subject_id in ["cn_lab", "dbms_lab", "oops_lab"]
    ]
    problem.demands.extend(extra)

    issues = preflight_checks(problem)
    too_few = [i for i in issues if i.id.startswith("rotation_too_few_rounds")]
    assert too_few, [i.id for i in issues]
    assert "4 batches" in too_few[0].fact

    results = solve_with_alternatives(problem, max_seconds=15, num_workers=4)
    assert results[0].status == "MODEL_INVALID"
    assert "rotation" in results[0].diagnostics["error"].lower()


def test_rotation_members_are_not_flagged_for_one_teacher_per_batch():
    """The exact diagnostic from the bug report. A lab in a rotation needs
    ONE qualified teacher, not one per batch, and the preflight must agree -
    otherwise the admin is still told to go and hire two more people."""
    slots = _week_calendar()
    problem = _rotation_problem(slots)
    issues = preflight_checks(problem)
    assert not [i for i in issues if i.id.startswith("insufficient_lab_teachers")], \
        [i.fact for i in issues]


def test_parallel_batches_still_demand_one_teacher_per_batch():
    """The rotation exemption must not quietly disarm the check for labs
    that really do run all their batches at once."""
    slots = _week_calendar()
    problem = _rotation_problem(slots)
    for demand in problem.demands:
        demand.rotation_group_id = None
        demand.batch_mode = "parallel"
    problem.rotation_groups = []
    issues = preflight_checks(problem)
    short = [i for i in issues if i.id.startswith("insufficient_lab_teachers")]
    assert short, [i.id for i in issues]
    assert "rotation" in short[0].suggestion.lower(), short[0].suggestion


def test_validator_catches_two_batches_put_in_the_same_lab_at_once():
    """The validator is the independent check, so it has to find a broken
    rotation even though the model builder would never produce one."""
    slots = _week_calendar()
    problem = _rotation_problem(slots)
    results = solve_with_alternatives(problem, max_seconds=30, num_workers=4)
    sessions = results[0].sessions
    assert validate_schedule(problem, sessions) == []

    # Force A2's CN lab on top of whoever else has CN lab that round.
    cn = [s for s in sessions if s.subject_id == "cn_lab"]
    victim = next(s for s in cn if s.audience_id == "A2")
    other = next(s for s in cn if s.audience_id != "A2")
    tampered = [
        ScheduledSession(
            demand_id=s.demand_id, subject_id=s.subject_id, audience_type=s.audience_type,
            audience_id=s.audience_id, parent_section_id=s.parent_section_id,
            start_slot_index=other.start_slot_index if s is victim else s.start_slot_index,
            duration=s.duration, room_id=s.room_id, teacher_id=s.teacher_id,
            co_teacher_ids=list(s.co_teacher_ids),
        )
        for s in sessions
    ]
    types = {v.type for v in validate_schedule(problem, tampered)}
    assert "ROTATION_SUBJECT_REPEATED" in types, types


def test_co_taught_lab_gets_two_distinct_teachers_and_keeps_them_all_week():
    """teachers_required=2: both teachers are real, distinct, qualified,
    and the same pair every session - not a different second supervisor
    each week."""
    slots = _week_calendar()
    demands = [
        SessionDemand(
            id=f"cn_lab:A1:{i}", subject_id="cn_lab", subject_name="CN Lab", kind="lab",
            audience_type="batch", audience_id="A1", parent_section_id="sec3a",
            session_index=i, duration=2, room_type="lab", equipment=[],
            eligible_room_ids=["L1"], eligible_teacher_ids=["t1", "t2", "t3"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 2),
            max_per_day=1, teachers_required=2,
        )
        for i in range(2)
    ]
    problem = ProblemData(
        slots=slots, rooms={"L1": RoomInfo(id="L1", type="lab", capacity=40)},
        teachers={t: TeacherInfo(id=t, max_daily_classes=8) for t in ["t1", "t2", "t3"]},
        demands=demands,
    )
    results = solve_with_alternatives(problem, max_seconds=20, num_workers=4)
    assert results[0].status in ("OPTIMAL", "FEASIBLE"), results[0].diagnostics
    assert validate_schedule(problem, results[0].sessions) == []

    teams = {tuple(sorted(s.teacher_ids)) for s in results[0].sessions}
    assert len(teams) == 1, f"the teaching pair changed between sessions: {teams}"
    team = next(iter(teams))
    assert len(team) == 2 and len(set(team)) == 2
    assert set(team) <= {"t1", "t2", "t3"}


def test_co_taught_lab_blocks_both_teachers_elsewhere():
    """A second supervisor is genuinely busy: nothing else may use either
    teacher during the lab. Two co-taught labs needing the same pair out of
    a 3-person pool cannot be made to overlap."""
    slots = _week_calendar(periods_per_day=2)  # 2 periods/day: a lab fills a whole day
    demands = [
        SessionDemand(
            id=f"{sid}:A{n}:0", subject_id=sid, subject_name=sid, kind="lab",
            audience_type="batch", audience_id=f"A{n}", parent_section_id=f"sec{n}",
            session_index=0, duration=2, room_type="lab", equipment=[],
            eligible_room_ids=["L1", "L2"], eligible_teacher_ids=["t1", "t2", "t3"],
            valid_start_slot_indices=valid_starts_for_duration(slots, 2),
            max_per_day=1, teachers_required=2,
        )
        for n, sid in enumerate(["cn_lab", "dbms_lab"], start=1)
    ]
    problem = ProblemData(
        slots=slots, rooms={r: RoomInfo(id=r, type="lab", capacity=40) for r in ["L1", "L2"]},
        teachers={t: TeacherInfo(id=t, max_daily_classes=8) for t in ["t1", "t2", "t3"]},
        demands=demands,
    )
    results = solve_with_alternatives(problem, max_seconds=20, num_workers=4)
    assert results[0].status in ("OPTIMAL", "FEASIBLE"), results[0].diagnostics
    assert validate_schedule(problem, results[0].sessions) == []
    a, b = results[0].sessions
    if a.start_slot_index == b.start_slot_index:
        assert not (set(a.teacher_ids) & set(b.teacher_ids)), \
            "two simultaneous labs share a teacher"


def test_asking_for_more_teachers_than_exist_is_explained_not_just_infeasible():
    slots = _week_calendar()
    demands = [SessionDemand(
        id="cn_lab:A1:0", subject_id="cn_lab", subject_name="CN Lab", kind="lab",
        audience_type="batch", audience_id="A1", parent_section_id="sec3a",
        session_index=0, duration=2, room_type="lab", equipment=[],
        eligible_room_ids=["L1"], eligible_teacher_ids=["t1"],
        valid_start_slot_indices=valid_starts_for_duration(slots, 2),
        max_per_day=1, teachers_required=3,
    )]
    problem = ProblemData(
        slots=slots, rooms={"L1": RoomInfo(id="L1", type="lab", capacity=40)},
        teachers={"t1": TeacherInfo(id="t1")}, demands=demands,
    )
    issues = preflight_checks(problem)
    short = [i for i in issues if i.id.startswith("teachers_required_short")]
    assert short, [i.id for i in issues]
    assert "3 teachers" in short[0].fact

    results = solve_with_alternatives(problem, max_seconds=10, num_workers=2)
    assert results[0].status == "MODEL_INVALID"
    assert "teachers at the same time" in results[0].diagnostics["error"]


@pytest.mark.parametrize("required", [1, 2])
def test_validator_rejects_a_schedule_with_the_wrong_number_of_teachers(required):
    slots = _week_calendar()
    demands = [SessionDemand(
        id="cn_lab:A1:0", subject_id="cn_lab", subject_name="CN Lab", kind="lab",
        audience_type="batch", audience_id="A1", parent_section_id="sec3a",
        session_index=0, duration=1, room_type="lab", equipment=[],
        eligible_room_ids=["L1"], eligible_teacher_ids=["t1", "t2"],
        valid_start_slot_indices=valid_starts_for_duration(slots, 1),
        max_per_day=1, teachers_required=required,
    )]
    problem = ProblemData(
        slots=slots, rooms={"L1": RoomInfo(id="L1", type="lab", capacity=40)},
        teachers={t: TeacherInfo(id=t) for t in ["t1", "t2"]}, demands=demands,
    )
    wrong = [ScheduledSession(
        demand_id="cn_lab:A1:0", subject_id="cn_lab", audience_type="batch", audience_id="A1",
        parent_section_id="sec3a", start_slot_index=0, duration=1, room_id="L1",
        teacher_id="t1", co_teacher_ids=["t2"] if required == 1 else [],
    )]
    types = {v.type for v in validate_schedule(problem, wrong)}
    assert "TEACHER_COUNT_WRONG" in types, types
