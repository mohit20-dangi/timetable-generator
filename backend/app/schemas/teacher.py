from pydantic import BaseModel
from typing import Optional, List

class TeacherBase(BaseModel):
    name: str
    department: Optional[str] = None
    max_continuous_classes: int = 3
    max_daily_classes: int = 5
    availability: List[dict] = []
    preferred_slots: List[dict] = []  # [{"day": "Mon", "slots": [{"start": "09:00", "end": "11:00"}, {"start": "13:00", "end": "15:00"}]}]
    is_guest_from_other_dept: bool = False

class TeacherCreate(TeacherBase):
    id: str

class TeacherResponse(TeacherBase):
    id: str
    
    class Config:
        from_attributes = True