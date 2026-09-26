from datetime import time as dtime
from app.solver.calendar import build_slot_calendar, contiguous_day_runs, valid_starts_for_duration


def _slots():
    raw = [
        {"day": "Mon", "period_index": 1, "start_time": dtime(9, 0), "end_time": dtime(9, 50)},
        {"day": "Mon", "period_index": 2, "start_time": dtime(9, 50), "end_time": dtime(10, 40)},
        # a gap here (recess) - period 3 does NOT start right after period 2
        {"day": "Mon", "period_index": 3, "start_time": dtime(11, 0), "end_time": dtime(11, 50)},
        {"day": "Tue", "period_index": 1, "start_time": dtime(9, 0), "end_time": dtime(9, 50)},
    ]
    return build_slot_calendar(raw)


def test_slots_are_indexed_day_major_then_period():
    slots = _slots()
    assert [s.index for s in slots] == [0, 1, 2, 3]
    assert slots[0].day == "Mon" and slots[0].period_index == 1
    assert slots[3].day == "Tue"


def test_contiguous_runs_break_at_a_gap():
    slots = _slots()
    runs = contiguous_day_runs(slots)
    # Mon P1-P2 are back-to-back; Mon P3 starts after a gap, so it's its
    # own run; Tue P1 is a new day, also its own run.
    assert runs == [[0, 1], [2], [3]]


def test_duration_1_block_can_start_anywhere():
    slots = _slots()
    starts = valid_starts_for_duration(slots, 1)
    assert set(starts) == {0, 1, 2, 3}


def test_duration_2_block_cannot_start_where_no_contiguous_run_exists():
    slots = _slots()
    starts = valid_starts_for_duration(slots, 2)
    # Only Mon P1->P2 forms a genuine 2-period contiguous run.
    assert starts == [0]


def test_lunch_window_excludes_overlapping_starts():
    slots = _slots()
    # Lunch from 09:30-10:00 overlaps period 1 (09:00-09:50, since 9:00<10:00 and 9:30<9:50).
    # Per-day (Phase 2.5): Tue carries no lunch window, so its slot is untouched.
    starts = valid_starts_for_duration(slots, 1, lunch_windows={"Mon": (9 * 60 + 30, 10 * 60)})
    assert 0 not in starts  # Mon P1 overlaps lunch
    assert 2 in starts  # Mon P3 (11:00) does not
    assert 3 in starts  # Tue P1 has no lunch window at all
