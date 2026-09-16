from pydantic import BaseModel
from datetime import time

class TimeSlotBase(BaseModel):
    day: str
    period_index: int
    start_time: time
    end_time: time

class TimeSlotCreate(TimeSlotBase):
    id: str

class TimeSlotResponse(TimeSlotBase):
    id: str
    
    class Config:
        from_attributes = True