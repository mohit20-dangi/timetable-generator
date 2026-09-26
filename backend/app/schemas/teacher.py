from pydantic import BaseModel, Field
from typing import Optional, List, Any


class TeacherBase(BaseModel):
    name: str
    # Short printed initials for exports (e.g. "MCH") - Phase 4.1. None
    # means "derive from the name", not "no initials".
    initials: Optional[str] = None
    department_id: Optional[str] = None
    max_continuous_classes: int = 3
    max_daily_classes: int = 6
    max_weekly_hours: int = 24
    availability: List[Any] = Field(default_factory=list)
    preferred_slots: List[Any] = Field(default_factory=list)
    is_guest_from_other_dept: bool = False


class TeacherCreate(TeacherBase):
    id: str
    subjects: Optional[List[str]] = None  # subject ids to qualify this teacher for


class TeacherResponse(TeacherBase):
    id: str

    class Config:
        from_attributes = True
