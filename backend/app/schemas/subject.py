from pydantic import BaseModel
from typing import Optional, List

class SubjectBase(BaseModel):
    name: str
    type: str  # theory, lab, tutorial
    weekly_hours: int = 0
    needs_continuous_block: bool = False
    block_size: int = 1
    requires_room_type: Optional[str] = None
    requires_equipment: List[str] = []

class SubjectCreate(SubjectBase):
    id: str

class SubjectResponse(SubjectBase):
    id: str
    
    class Config:
        from_attributes = True