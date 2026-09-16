from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class TimetableGenerateRequest(BaseModel):
    constraint_profile_id: Optional[str] = None
    num_alternatives: int = Field(default=1, ge=1, le=5)
    year_ids: Optional[List[str]] = None
    section_ids: Optional[List[str]] = None

class TimetableRunResponse(BaseModel):
    id: int
    constraint_profile_id: Optional[str] = None
    status: str
    solver_output: Optional[Dict[str, Any]] = None
    llm_explanation: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    is_published: bool = False
    published_at: Optional[datetime] = None
    parent_run_id: Optional[int] = None
    change_summary: Optional[str] = None

    class Config:
        from_attributes = True

class EntryIdentifier(BaseModel):
    """Identifies one existing scheduled class within a run, to be edited."""
    day: str
    period: int
    subject_id: str
    section_id: Optional[str] = None
    batch_id: Optional[str] = None

class EditEntryRequest(BaseModel):
    target: EntryIdentifier
    new_day: str
    new_period: int
    new_room_id: Optional[str] = None  # if omitted, keep the same room
    new_teacher_id: Optional[str] = None  # if omitted, keep the same teacher
    auto_resolve: bool = False  # if True and the requested slot conflicts, apply the first suggested alternative instead
    reason: Optional[str] = None

class ConflictDetail(BaseModel):
    type: str  # TEACHER_CLASH, ROOM_CLASH, SECTION_CLASH, BATCH_CLASH, LUNCH_BREAK, ROOM_CAPACITY
    message: str

class SuggestedSlot(BaseModel):
    day: str
    period: int

class EditEntryResponse(BaseModel):
    status: str  # "applied" or "conflict"
    conflicts: List[ConflictDetail] = []
    suggested_slots: List[SuggestedSlot] = []
    new_run: Optional[TimetableRunResponse] = None

class PublishRequest(BaseModel):
    pass

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
