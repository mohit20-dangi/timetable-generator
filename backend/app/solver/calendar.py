"""Turns raw (day, period_index, start_time, end_time) rows into the
integer slot-index axis the solver operates on, and answers the two
questions every duration>1 demand needs: "which slot indices could a
D-period block legally start at", given day boundaries and a lunch window.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.solver.types import Slot

DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _minutes(hh_mm) -> int:
    """Accept either a datetime.time or an 'HH:MM'/'HH:MM:SS' string."""
    if hasattr(hh_mm, "hour"):
        return hh_mm.hour * 60 + hh_mm.minute
    parts = str(hh_mm).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def build_slot_calendar(raw_slots: List[dict]) -> List[Slot]:
    """raw_slots: [{"day","period_index","start_time","end_time"}, ...].
    Returns Slots sorted day-major (in DAY_ORDER) then by period_index,
    with a stable 0-based `index` - the axis every other solver structure
    is keyed on."""
    def sort_key(row):
        day_rank = DAY_ORDER.index(row["day"]) if row["day"] in DAY_ORDER else 99
        return (day_rank, row["period_index"])

    ordered = sorted(raw_slots, key=sort_key)
    slots: List[Slot] = []
    for i, row in enumerate(ordered):
        slots.append(Slot(
            index=i,
            day=row["day"],
            period_index=row["period_index"],
            start_minutes=_minutes(row["start_time"]),
            end_minutes=_minutes(row["end_time"]),
        ))
    return slots


def contiguous_day_runs(slots: List[Slot]) -> List[List[int]]:
    """Groups slot indices into maximal same-day runs where each slot's
    end_minutes equals the next slot's start_minutes (i.e. genuinely
    back-to-back, not merely "same day with a gap"). A block can only
    legally start such that its whole span lies inside one such run."""
    runs: List[List[int]] = []
    current: List[int] = []
    prev: Optional[Slot] = None
    for slot in slots:
        if prev is not None and slot.day == prev.day and slot.start_minutes == prev.end_minutes:
            current.append(slot.index)
        else:
            if current:
                runs.append(current)
            current = [slot.index]
        prev = slot
    if current:
        runs.append(current)
    return runs


def valid_starts_for_duration(
    slots: List[Slot],
    duration: int,
    lunch_windows: Optional[Dict[str, Tuple[int, int]]] = None,
) -> List[int]:
    """All slot indices at which a `duration`-period contiguous block could
    legally start: the whole block must lie in one same-day back-to-back
    run, and must not overlap that day's lunch window (start_minutes,
    end_minutes), if `lunch_windows` (day -> window) has one for that day.
    Per-day (Phase 2.5) rather than one window applied to every day, so a
    day can run a class straight through what's lunch on every other day.
    """
    by_index = {s.index: s for s in slots}
    valid: List[int] = []
    for run in contiguous_day_runs(slots):
        for i in range(0, len(run) - duration + 1):
            window = run[i:i + duration]
            first, last = by_index[window[0]], by_index[window[-1]]
            day_lunch = (lunch_windows or {}).get(first.day)
            if day_lunch:
                lunch_start, lunch_end = day_lunch
                if first.start_minutes < lunch_end and lunch_start < last.end_minutes:
                    continue
            valid.append(window[0])
    return valid


def occupied_indices(start_slot_index: int, duration: int, slots_by_index: dict) -> List[int]:
    """The slots a block starting at `start_slot_index` actually occupies,
    found by walking forward through the same-day contiguous run. Assumes
    `start_slot_index` came from valid_starts_for_duration, so the run of
    `duration` slots is guaranteed to exist and be contiguous."""
    result = [start_slot_index]
    current = slots_by_index[start_slot_index]
    idx = start_slot_index
    while len(result) < duration:
        idx += 1
        nxt = slots_by_index.get(idx)
        if nxt is None or nxt.day != current.day or nxt.start_minutes != current.end_minutes:
            break
        result.append(idx)
        current = nxt
    return result
