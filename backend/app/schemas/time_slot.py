from pydantic import BaseModel, model_validator
from datetime import time

from app.solver.calendar import DAY_ORDER

VALID_DAYS = set(DAY_ORDER)


class TimeSlotBase(BaseModel):
    day: str
    period_index: int
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _validate(self):
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


class TimeSlotResponse(TimeSlotBase):
    id: str

    class Config:
        from_attributes = True
