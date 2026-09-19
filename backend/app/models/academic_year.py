from pydantic import BaseModel
from typing import Optional


class AcademicYearCreate(BaseModel):
    id: str
    name: str
    lunch_start: Optional[str] = None  # "HH:MM"
    lunch_end: Optional[str] = None


class AcademicYearResponse(AcademicYearCreate):
    pass
