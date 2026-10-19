"""Which bell schedule (time slots) a department runs on.

Each department keeps its own periods. Slots with no department are the
schedule from before departments were separated; a department that hasn't
set up its own periods yet keeps running on those, so an existing install
doesn't lose its timetable the moment it upgrades. The first time such a
department changes its schedule, the shared periods are copied into it
(ensure_own_time_slots) so the change applies to a full schedule, not to a
one-period one.
"""
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import TimeSlot


REGULAR_SLOT = "regular"
REMEDIAL_SLOT = "remedial"
SLOT_KINDS = (REGULAR_SLOT, REMEDIAL_SLOT)


def _of_kind(query, kind: Optional[str]):
    """Rows from before slot_kind existed read as regular."""
    if kind is None:
        return query
    if kind == REGULAR_SLOT:
        return query.filter(or_(TimeSlot.slot_kind == REGULAR_SLOT, TimeSlot.slot_kind.is_(None)))
    return query.filter(TimeSlot.slot_kind == kind)


def department_time_slots(db: Session, department_id: Optional[str], kind: Optional[str] = REGULAR_SLOT) -> List[TimeSlot]:
    """`kind` limits the result to regular or remedial periods; None returns
    both. Defaults to regular so every caller that predates remedial slots
    keeps seeing exactly the main bell schedule."""
    if department_id:
        own = _of_kind(db.query(TimeSlot).filter(TimeSlot.department_id == department_id), kind).all()
        if own:
            return own
        if kind == REMEDIAL_SLOT:
            return []  # remedial periods are never inherited from the shared schedule
        if kind is None:
            own_any = db.query(TimeSlot).filter(TimeSlot.department_id == department_id).all()
            if own_any:
                return own_any
    return _of_kind(db.query(TimeSlot).filter(TimeSlot.department_id.is_(None)), kind).all()


def ensure_own_time_slots(db: Session, department_id: str) -> Dict[str, str]:
    """Gives the department its own copy of the shared schedule if it has no
    periods of its own yet. Returns {shared slot id: the department's copy's
    id} (empty when nothing needed copying)."""
    if _of_kind(db.query(TimeSlot).filter(TimeSlot.department_id == department_id), REGULAR_SLOT).first():
        return {}
    copies: Dict[str, str] = {}
    for slot in _of_kind(db.query(TimeSlot).filter(TimeSlot.department_id.is_(None)), REGULAR_SLOT).all():
        copy_id = f"{department_id}_{slot.id}"
        db.add(TimeSlot(
            id=copy_id, day=slot.day, period_index=slot.period_index,
            start_time=slot.start_time, end_time=slot.end_time, department_id=department_id,
            slot_kind=slot.slot_kind or REGULAR_SLOT,
        ))
        copies[slot.id] = copy_id
    db.flush()
    return copies


def slot_id(department_id: Optional[str], day: str, period_index: int) -> str:
    """Deterministic, so saving an unchanged schedule reproduces its ids."""
    return f"{department_id or 'shared'}_{day}_{period_index}"


def number_schedule(periods: List[dict]) -> List[dict]:
    """Assigns period_index per day: regular periods 1..N in clock order, then
    remedial N+1... in clock order. The solver keys its calendar on
    (day, period_index) across both kinds, so the two kinds must never share
    a number; the UI labels them separately."""
    from app.solver.calendar import DAY_ORDER

    numbered: List[dict] = []
    for day in sorted({p["day"] for p in periods}, key=DAY_ORDER.index):
        of_day = [p for p in periods if p["day"] == day]
        ordered = (
            sorted((p for p in of_day if (p.get("slot_kind") or REGULAR_SLOT) == REGULAR_SLOT), key=lambda p: p["start_time"])
            + sorted((p for p in of_day if p.get("slot_kind") == REMEDIAL_SLOT), key=lambda p: p["start_time"])
        )
        for i, p in enumerate(ordered, start=1):
            numbered.append({**p, "period_index": i})
    return numbered
