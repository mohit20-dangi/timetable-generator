from pydantic import BaseModel


class TimeSlotCreate(BaseModel):
    id: str
    day: str
    period_index: int
    start_time: str  # "HH:MM"
    end_time: str


class TimeSlotResponse(TimeSlotCreate):
    pass
