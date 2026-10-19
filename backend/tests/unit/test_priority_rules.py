"""The teacher-comfort / week-shape priorities (app/solver/priority_rules.py).
Each test makes the undesirable layout the ONLY thing pulling the other way
(every rule is soft), so a passing assertion means the rule itself did it."""
from datetime import time as dtime

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.engine import solve_with_alternatives
from app.solver.types import ProblemData, RoomInfo, SessionDemand, TeacherInfo

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def _slots(periods=6):
    raw = []
    for day in DAYS:
        for period in range(1, periods + 1):
            start = 9 * 60 + (period - 1) * 50
            raw.append({
                "day": day, "period_index": period,
                "start_time": dtime(start // 60, start % 60),
                "end_time": dtime((start + 50) // 60, (start + 50) % 60),
            })
    return build_slot_calendar(raw)


def _demand(slots, subject, i, section="s1", kind="theory", max_per_day=2, duration=1):
    return SessionDemand(
        id=f"{subject}:{section}:{i}", subject_id=subject, subject_name=subject, kind=kind,
        audience_type="section", audience_id=section, parent_section_id=section,
        session_index=i, duration=duration, room_type=None, equipment=[],
        eligible_room_ids=["R1", "R2"], eligible_teacher_ids=["t1"],
        valid_start_slot_indices=valid_starts_for_duration(slots, duration),
        max_per_day=max_per_day,
    )


def _solve(slots, demands, weights, params=None, teacher=None):
    problem = ProblemData(
        slots=slots,
        rooms={"R1": RoomInfo("R1", "lecture", 60), "R2": RoomInfo("R2", "lecture", 60)},
        teachers={"t1": teacher or TeacherInfo(id="t1", max_continuous_classes=6, max_daily_classes=6)},
        demands=demands, soft_weights=weights,
    )
    if params:
        problem.rule_params.update(params)
    result = solve_with_alternatives(problem, max_seconds=30, num_workers=4, num_alternatives=1)[0]
    assert result.status in ("OPTIMAL", "FEASIBLE"), result.diagnostics
    return result


def _by_day(slots, result):
    by_index = {s.index: s for s in slots}
    days = {}
    for session in result.sessions:
        slot = by_index[session.start_slot_index]
        days.setdefault(slot.day, []).append(slot.period_index)
    return {d: sorted(p) for d, p in days.items()}


def _longest_run(periods):
    best = run = 0
    prev = None
    for p in periods:
        run = run + 1 if prev is not None and p == prev + 1 else 1
        best = max(best, run)
        prev = p
    return best


def test_limit_consecutive_teaching_uses_the_admin_number():
    slots = _slots()
    demands = [_demand(slots, "maths", i) for i in range(8)]
    for limit in (2, 3):
        result = _solve(
            slots, demands, {"limit_consecutive_teaching": 20},
            params={"max_consecutive_teaching": limit},
        )
        runs = [_longest_run(p) for p in _by_day(slots, result).values()]
        assert max(runs) <= limit, (limit, _by_day(slots, result))


def test_cap_teacher_daily_periods():
    slots = _slots()
    demands = [_demand(slots, "maths", i) for i in range(8)]
    result = _solve(
        slots, demands, {"cap_teacher_daily_periods": 20}, params={"max_teacher_periods_per_day": 2},
    )
    assert max(len(p) for p in _by_day(slots, result).values()) <= 2


def test_teacher_gets_a_lighter_day():
    slots = _slots()
    demands = [_demand(slots, "maths", i, max_per_day=6) for i in range(12)]
    result = _solve(slots, demands, {"teacher_lighter_day": 20})
    by_day = _by_day(slots, result)
    assert min(len(by_day.get(d, [])) for d in DAYS) <= 2


def test_subject_not_repeated_on_same_day_when_avoidable():
    slots = _slots()
    demands = [_demand(slots, "maths", i, max_per_day=3) for i in range(5)]
    result = _solve(slots, demands, {"no_repeat_subject_same_day": 20})
    assert all(len(p) == 1 for p in _by_day(slots, result).values())


def test_subject_spread_avoids_adjacent_days():
    slots = _slots()
    demands = [_demand(slots, "maths", i) for i in range(3)]
    result = _solve(slots, demands, {"spread_subject_across_week": 20})
    used = sorted(DAYS.index(d) for d in _by_day(slots, result))
    assert all(b - a > 1 for a, b in zip(used, used[1:])), used  # Mon/Wed/Fri


def test_heavy_subject_lands_in_the_morning():
    slots = _slots(periods=6)
    demands = [_demand(slots, "maths", i) for i in range(4)]
    result = _solve(slots, demands, {"heavy_subjects_early": 20})
    assert all(p <= 3 for periods in _by_day(slots, result).values() for p in periods)


def test_no_day_of_only_labs_when_theory_exists():
    slots = _slots()
    demands = [_demand(slots, "maths", i) for i in range(4)]
    demands += [_demand(slots, "physics_lab", i, kind="lab", duration=2, max_per_day=1) for i in range(2)]
    result = _solve(slots, demands, {"balanced_theory_lab_days": 20})
    by_index = {s.index: s for s in slots}
    kind_by_subject = {d.subject_id: d.kind for d in demands}
    per_day = {}
    for session in result.sessions:
        per_day.setdefault(by_index[session.start_slot_index].day, set()).add(kind_by_subject[session.subject_id])
    assert all("theory" in kinds for kinds in per_day.values()), per_day
