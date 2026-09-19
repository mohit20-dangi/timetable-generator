from pydantic import BaseModel
from typing import List, Optional


class SubjectCreate(BaseModel):
    id: str
    name: str
    type: str  # theory, lab, tutorial
    weekly_hours: int = 0
    needs_continuous_block: bool = False
    block_size: int = 1
    requires_room_type: Optional[str] = None  # lecture, lab, seminar
    requires_equipment: List[str] = []
    prerequisite_ids: List[str] = []


class SubjectResponse(SubjectCreate):
    pass
