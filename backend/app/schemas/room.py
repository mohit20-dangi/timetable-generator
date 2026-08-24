from pydantic import BaseModel
from typing import Optional, List

class RoomBase(BaseModel):
    name: str
    type: str  # lecture, lab, seminar
    capacity: int = 60
    equipment: List[str] = []
    shared_with_departments: List[str] = []
    availability: List[dict] = []  # [{"day": "Mon", "start": "08:00", "end": "18:00"}]

class RoomCreate(RoomBase):
    id: str

class RoomResponse(RoomBase):
    id: str
    
    class Config:
        from_attributes = True