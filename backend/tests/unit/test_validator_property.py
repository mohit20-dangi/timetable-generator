"""The single property that matters most in this whole project: for any
randomly generated instance the solver reports feasible, the independent
validator (app/solver/validator.py, written without sharing code with
model_builder.py) finds ZERO hard-constraint violations. If this ever
fails, either the model builder is under-constraining the search (a real
bug that would ship a broken timetable) or the validator disagrees with it
about what a hard constraint means (also a bug, just a different one) -
either way, this is the test that catches it.
"""
from datetime import time as dtime

from hypothesis import given, settings as hyp_settings, strategies as st, HealthCheck

from app.solver.calendar import build_slot_calendar, valid_starts_for_duration
from app.solver.types import ProblemData, RoomInfo, TeacherInfo, SessionDemand
from app.solver.engine import solve_with_alternatives
from app.solver.validator import validate_schedule


def _calendar(num_days=3, periods_per_day=4):
    raw = []
    for d in range(num_days):
        day = ["Mon", "Tue", "Wed", "Thu", "Fri"][d]
        for period in range(1, periods_per_day + 1):
            start_min = 9 * 60 + (period - 1) * 50
            raw.append({
                "day": day, "period_index": period,
                "start_time": dtime(start_min // 60, start_min % 60),
                "end_time": dtime((start_min + 50) // 60, (start_min + 50) % 60),
            })
    return build_slot_calendar(raw)


@st.composite
def small_problem(draw):
    """Generates a small-but-varied ProblemData: a handful of sections,
    subjects with random duration/max_per_day, a couple of shared teachers
    and rooms - enough combinatorial pressure to exercise every hard
    constraint without the search taking more than a second or two."""
    slots = _calendar()
    num_rooms = draw(st.integers(min_value=1, max_value=3))
    num_teachers = draw(st.integers(min_value=1, max_value=3))
    num_sections = draw(st.integers(min_value=1, max_value=2))
    num_subjects_per_section = draw(st.integers(min_value=1, max_value=3))

    rooms = {f"R{i}": RoomInfo(id=f"R{i}", type="lecture", capacity=100) for i in range(num_rooms)}
    teachers = {f"T{i}": TeacherInfo(id=f"T{i}", max_daily_classes=8, max_weekly_hours=40) for i in range(num_teachers)}

    demands = []
    for s in range(num_sections):
        section_id = f"S{s}"
        for subj in range(num_subjects_per_section):
            subject_id = f"S{s}_subj{subj}"
            duration = draw(st.integers(min_value=1, max_value=2))
            num_sessions = draw(st.integers(min_value=1, max_value=2))
            max_per_day = draw(st.integers(min_value=1, max_value=2))
            eligible_teachers = draw(st.lists(st.sampled_from(list(teachers.keys())), min_size=1, max_size=num_teachers, unique=True))
            eligible_rooms = list(rooms.keys())
            valid_starts = valid_starts_for_duration(slots, duration)
            if not valid_starts:
                continue
            for i in range(num_sessions):
                demands.append(SessionDemand(
                    id=f"{subject_id}:{section_id}:{i}", subject_id=subject_id, subject_name=subject_id,
                    kind="theory", audience_type="section", audience_id=section_id,
                    parent_section_id=section_id, session_index=i, duration=duration,
                    room_type=None, equipment=[], eligible_room_ids=eligible_rooms,
                    eligible_teacher_ids=eligible_teachers, valid_start_slot_indices=valid_starts,
                    max_per_day=max_per_day,
                ))

    return ProblemData(slots=slots, rooms=rooms, teachers=teachers, demands=demands)


@given(problem=small_problem())
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
def test_feasible_schedules_are_always_valid(problem):
    if not problem.demands:
        return
    results = solve_with_alternatives(problem, max_seconds=5, num_workers=2, num_alternatives=1)
    result = results[0]
    if result.status not in ("OPTIMAL", "FEASIBLE"):
        return  # infeasible instances are not this property's concern
    violations = validate_schedule(problem, result.sessions)
    assert violations == [], [f"{v.type}: {v.message}" for v in violations]
