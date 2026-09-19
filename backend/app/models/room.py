from pydantic import BaseModel
from typing import List


class RoomAvailabilitySlot(BaseModel):
    day: str
    start: str
    end: str


class RoomCreate(BaseModel):
    id: str
    name: str
    type: str  # lecture, lab, seminar
    capacity: int = 60
    equipment: List[str] = []
    shared_with_departments: List[str] = []
    availability: List[RoomAvailabilitySlot] = []


class RoomResponse(RoomCreate):
    pass
