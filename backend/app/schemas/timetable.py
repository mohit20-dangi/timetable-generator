from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class TimetableGenerateRequest(BaseModel):
    constraint_profile_id: Optional[str] = None

class TimetableRunResponse(BaseModel):
    id: int
    constraint_profile_id: Optional[str] = None
    status: str
    solver_output: Optional[Dict[str, Any]] = None
    llm_explanation: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class TimetableEntryResponse(BaseModel):
    id: int
    timetable_run_id: int
    day: str
    period: int
    section_id: Optional[str] = None
    batch_id: Optional[str] = None
    subject_id: str
    teacher_id: str
    room_id: str
    
    class Config:
        from_attributes = True