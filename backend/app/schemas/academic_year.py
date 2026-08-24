from pydantic import BaseModel
from datetime import time
from typing import Optional

class AcademicYearBase(BaseModel):
    name: str
    num_sections: int = 1
    lunch_start: Optional[time] = None
    lunch_end: Optional[time] = None

class AcademicYearCreate(AcademicYearBase):
    id: str

class AcademicYearResponse(AcademicYearBase):
    id: str
    
    class Config:
        from_attributes = True