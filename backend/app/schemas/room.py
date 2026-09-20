from pydantic import BaseModel, Field
from typing import Optional, List, Any

VALID_ROOM_TYPES = {"lecture", "lab", "seminar"}


class RoomBase(BaseModel):
    name: str
    type: str
    capacity: int = 60
    equipment: List[str] = Field(default_factory=list)
    department_id: Optional[str] = None
    shared_with_departments: List[str] = Field(default_factory=list)
    availability: List[Any] = Field(default_factory=list)


class RoomCreate(RoomBase):
    id: str


class RoomResponse(RoomBase):
    id: str

    class Config:
        from_attributes = True
