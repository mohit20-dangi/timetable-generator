from pydantic import BaseModel
from typing import List, Optional


class AvailabilitySlot(BaseModel):
    day: str
    start: str
    end: str


class PreferredSlotInterval(BaseModel):
    start: str
    end: str


class PreferredSlot(BaseModel):
    day: str
    slots: List[PreferredSlotInterval] = []


class TeacherCreate(BaseModel):
    id: str
    name: str
    department: Optional[str] = None
    subject_ids: List[str] = []
    max_continuous_classes: int = 3
    max_daily_classes: int = 5
    availability: List[AvailabilitySlot] = []
    preferred_slots: List[PreferredSlot] = []
    is_guest_from_other_dept: bool = False


class TeacherResponse(TeacherCreate):
    pass
