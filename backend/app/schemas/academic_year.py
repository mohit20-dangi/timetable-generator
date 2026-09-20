from pydantic import BaseModel
from typing import Optional
from datetime import time


class AcademicYearBase(BaseModel):
    name: str
    num_sections: int = 1
    lunch_start: Optional[time] = None
    lunch_end: Optional[time] = None


class AcademicYearCreate(AcademicYearBase):
    id: str
    department_id: Optional[str] = None


class AcademicYearResponse(AcademicYearBase):
    id: str
    department_id: Optional[str] = None

    class Config:
        from_attributes = True
