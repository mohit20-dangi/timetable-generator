from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class AcademicTermBase(BaseModel):
    name: str
    start_date: date
    end_date: date
    working_days: List[str] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    holidays: List[str] = []


class AcademicTermCreate(AcademicTermBase):
    id: str
    department_id: str


class AcademicTermResponse(AcademicTermBase):
    id: str
    department_id: str
    teaching_weeks: Optional[int] = None

    class Config:
        from_attributes = True
