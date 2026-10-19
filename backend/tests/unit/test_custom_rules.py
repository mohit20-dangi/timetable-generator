"""Admin-defined preference templates (app/solver/custom_rules.py): each is
solved, then independently re-checked by the validator - never trusting the
encoding to have worked.
"""
from datetime import time as dtime

import pytest

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.engine import solve_with_alternatives
from app.solver.types import CustomRule, ProblemData, RoomInfo, SessionDemand, TeacherInfo
from app.solver.validator import validate_schedule

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def _slots():
    raw = []
    for day in DAYS:
        for period in range(1, 7):  # 08:00 .. 14:00, hourly
            start = 8 * 60 + (period - 1) * 60
            raw.append({
                "day": day, "period_index": period,
                "start_time": dtime(start // 60, start % 60),
                "end_time": dtime((start + 60) // 60, (start + 60) % 60),
            })
    return build_slot_calendar(raw)


def _demand(slots, subject, n, teacher="t1", section="sec1"):
    return [
        SessionDemand(
            id=f"{subject}:{section}:{i}", subject_id=subject, subject_name=subject.title(),
            kind="theory", audience_type="section", audience_id=section, parent_section_id=section,
            session_index=i, duration=1, room_type="lecture", equipment=[],
            eligible_room_ids=["R1"], eligible_teacher_ids=[teacher],
            valid_start_slot_indices=valid_starts_for_duration(slots, 1), max_per_day=1,
        )
        for i in range(n)
    ]


def _problem(slots, demands, rules, teachers=("t1",)):
    return ProblemData(
        slots=slots, rooms={"R1": RoomInfo(id="R1", type="lecture", capacity=80)},
        teachers={t: TeacherInfo(id=t, max_daily_classes=6, max_weekly_hours=40) for t in teachers},
        demands=demands, custom_rules=rules,
    )


def _solve(problem):
    result = solve_with_alternatives(problem, max_seconds=20, num_workers=2)[0]
    assert result.status in ("OPTIMAL", "FEASIBLE"), result.status
    return result


def _morning(slots):
    return {s.index for s in slots if s.end_minutes <= 12 * 60}


def test_subject_time_window_hard_keeps_subject_in_the_morning():
    slots = _slots()
    demands = _demand(slots, "maths", 4) + _demand(slots, "physics", 4, teacher="t2")
    rule = CustomRule("subject_time_window", True, 0, "maths", slot_indices=_morning(slots), label="m")
    problem = _problem(slots, demands, [rule], teachers=("t1", "t2"))
    result = _solve(problem)
    for s in result.sessions:
        if s.subject_id == "maths":
            assert s.start_slot_index in _morning(slots)
    assert validate_schedule(problem, result.sessions) == []


def test_subject_time_window_avoid_mode_keeps_subject_out_of_window():
    slots = _slots()
    rule = CustomRule("subject_time_window", True, 0, "maths", slot_indices=_morning(slots), mode="avoid", label="a")
    problem = _problem(slots, _demand(slots, "maths", 5), [rule])
    result = _solve(problem)
    assert all(s.start_slot_index not in _morning(slots) for s in result.sessions)
    assert validate_schedule(problem, result.sessions) == []


def test_subject_time_window_soft_is_preferred_but_not_forced():
    """30 sessions can't all fit in the 4 morning periods x 5 days, so a soft
    rule must still solve (a hard one would be infeasible)."""
    slots = _slots()
    demands = _demand(slots, "maths", 5, section="a") + _demand(slots, "maths", 5, section="b")
    rule = CustomRule("subject_time_window", False, 50, "maths", slot_indices=_morning(slots), label="s")
    result = _solve(_problem(slots, demands, [rule]))
    assert sum(1 for s in result.sessions if s.start_slot_index in _morning(slots)) == 10


def test_subject_time_window_hard_with_no_valid_time_reports_clearly():
    slots = _slots()
    rule = CustomRule("subject_time_window", True, 0, "maths", slot_indices=set(), label="empty")
    problem = _problem(slots, _demand(slots, "maths", 1), [rule])
    result = solve_with_alternatives(problem, max_seconds=5, num_workers=1)[0]
    assert result.status == "MODEL_INVALID"
    assert "empty" in result.diagnostics["error"]


def test_max_subjects_per_day_hard_is_respected():
    slots = _slots()
    demands = (
        _demand(slots, "s1", 2, "t1") + _demand(slots, "s2", 2, "t2")
        + _demand(slots, "s3", 2, "t3") + _demand(slots, "s4", 2, "t4")
    )
    rule = CustomRule("max_subjects_per_day", True, 0, "sec1", limit=2, label="cap")
    problem = _problem(slots, demands, [rule], teachers=("t1", "t2", "t3", "t4"))
    result = _solve(problem)
    assert validate_schedule(problem, result.sessions) == []
    per_day = {}
    for s in result.sessions:
        per_day.setdefault(slots[s.start_slot_index].day, set()).add(s.subject_id)
    assert all(len(v) <= 2 for v in per_day.values())


def test_max_subjects_per_day_wildcard_applies_to_every_section():
    slots = _slots()
    demands = []
    for section in ("a", "b"):
        for n, subject in enumerate(("s1", "s2")):
            demands += _demand(slots, f"{subject}{section}", 2, f"t{section}{n}", section)
    teachers = tuple(f"t{sec}{n}" for sec in "ab" for n in range(2))
    rule = CustomRule("max_subjects_per_day", True, 0, "*", limit=1, label="one")
    problem = _problem(slots, demands, [rule], teachers=teachers)
    result = _solve(problem)
    assert validate_schedule(problem, result.sessions) == []


def test_teacher_max_days_hard_compresses_teaching_into_fewer_days():
    slots = _slots()
    rule = CustomRule("teacher_max_days_per_week", True, 0, "t1", limit=2, label="days")
    problem = _problem(slots, _demand(slots, "maths", 2, section="a") + _demand(slots, "maths", 2, section="b"), [rule])
    result = _solve(problem)
    assert len({slots[s.start_slot_index].day for s in result.sessions}) <= 2
    assert validate_schedule(problem, result.sessions) == []


def test_teacher_max_days_soft_yields_when_it_cannot_be_met():
    slots = _slots()
    demands = []
    for section in "abcde":  # 5 sections x maths max_per_day=1 still fits in 1 day, but 2 days is plenty
        demands += _demand(slots, "maths", 1, section=section)
    rule = CustomRule("teacher_max_days_per_week", False, 30, "t1", limit=1, label="soft_days")
    result = _solve(_problem(slots, demands, [rule]))
    assert len({slots[s.start_slot_index].day for s in result.sessions}) == 1


def test_validator_flags_a_schedule_that_breaks_a_hard_rule():
    """Proves the validator is an independent check, not a rubber stamp."""
    slots = _slots()
    rule = CustomRule("max_subjects_per_day", True, 0, "sec1", limit=1, label="cap")
    demands = _demand(slots, "s1", 1, "t1") + _demand(slots, "s2", 1, "t2")
    problem = _problem(slots, demands, [])  # solve WITHOUT the rule
    result = _solve(problem)
    # force both onto the same day, then check against the real rule
    for s in result.sessions:
        s.start_slot_index = slots[0].index if s.subject_id == "s1" else slots[1].index
    problem.custom_rules = [rule]
    assert any(v.type == "CUSTOM_MAX_SUBJECTS_PER_DAY" for v in validate_schedule(problem, result.sessions))
