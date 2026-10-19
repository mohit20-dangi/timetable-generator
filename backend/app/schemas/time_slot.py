from typing import List, Optional
from pydantic import BaseModel, model_validator
from datetime import time

from app.solver.calendar import DAY_ORDER

VALID_DAYS = set(DAY_ORDER)


class TimeSlotBase(BaseModel):
    day: str
    period_index: int
    start_time: time
    end_time: time
    slot_kind: str = "regular"

    @model_validator(mode="after")
    def _validate(self):
        if self.slot_kind not in ("regular", "remedial"):
            raise ValueError("slot_kind must be 'regular' or 'remedial'")
        # A day outside this set silently sorts to the end of the week
        # (calendar.py's DAY_ORDER.index() fallback) instead of raising -
        # catch the typo ("Monday" instead of "Mon") here, at the boundary.
        if self.day not in VALID_DAYS:
            raise ValueError(f"day must be one of {sorted(VALID_DAYS, key=DAY_ORDER.index)}, got '{self.day}'")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class TimeSlotCreate(TimeSlotBase):
    id: str
    # Blank = the creating user's own department.
    department_id: Optional[str] = None


class TimeSlotResponse(TimeSlotBase):
    id: str
    department_id: Optional[str] = None

    class Config:
        from_attributes = True


class TimeSlotUpdate(TimeSlotBase):
    """Edit one period's time or kind; the server renumbers the day."""


class BellSchedulePeriod(BaseModel):
    """One period of a bell schedule being saved. No id or period_index: the
    server numbers periods (regular first, then remedial) so the client can't
    produce a numbering the solver's calendar would misread."""
    day: str
    start_time: time
    end_time: time
    slot_kind: str = "regular"

    @model_validator(mode="after")
    def _validate(self):
        TimeSlotBase(period_index=1, **self.model_dump())
        return self


class BellScheduleReplace(BaseModel):
    department_id: Optional[str] = None
    periods: List[BellSchedulePeriod]
