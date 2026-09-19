from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime


class TimetableGenerateRequest(BaseModel):
    constraint_profile_id: Optional[str] = None


class TimetableEntry(BaseModel):
    day: str
    period: int
    section_id: Optional[str] = None
    batch_id: Optional[str] = None
    subject_id: str
    teacher_id: str
    room_id: str


class TimetableRunResponse(BaseModel):
    id: int
    constraint_profile_id: Optional[str] = None
    status: str  # pending, solving, completed, failed
    entries: List[TimetableEntry] = []
    llm_explanation: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
