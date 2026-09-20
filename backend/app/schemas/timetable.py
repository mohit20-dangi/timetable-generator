from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

VALID_SCOPE_MODES = {"fit_into_existing", "fresh"}


class TimetableGenerateRequest(BaseModel):
    department_id: str
    constraint_profile_id: Optional[str] = None
    num_alternatives: int = Field(default=1, ge=1, le=5)
    year_ids: Optional[List[str]] = None
    section_ids: Optional[List[str]] = None
    # "fit_into_existing" (default, safe): everything outside this scope is
    # frozen as unavailability, so the new schedule can never clash with
    # what's already published. "fresh": scope is solved in isolation -
    # faster and higher quality for the scope alone, but the caller accepts
    # the risk of colliding with other departments/years/sections.
    scope_mode: str = "fit_into_existing"

    @model_validator(mode="after")
    def _validate_scope(self):
        if self.scope_mode not in VALID_SCOPE_MODES:
            raise ValueError(f"scope_mode must be one of {sorted(VALID_SCOPE_MODES)}")
        return self


class TimetableRunResponse(BaseModel):
    id: int
    department_id: Optional[str] = None
    constraint_profile_id: Optional[str] = None
    status: str
    scope_mode: Optional[str] = None
    year_ids: Optional[List[str]] = None
    section_ids: Optional[List[str]] = None
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
    alternative_rank: int = 1
    session_group: Optional[str] = None
    day: str
    period: int
    section_id: Optional[str] = None
    batch_id: Optional[str] = None
    subject_id: str
    teacher_id: str
    room_id: str

    class Config:
        from_attributes = True


class ValidationIssue(BaseModel):
    type: str
    message: str


class ValidationResponse(BaseModel):
    valid: bool
    issues: List[ValidationIssue] = []


class AlternativeSummary(BaseModel):
    rank: int
    objective_value: float
    diversity_from_previous: int = 0


class AlternativesResponse(BaseModel):
    alternatives: List[AlternativeSummary]


class AlternativeDetailResponse(BaseModel):
    rank: int
    objective_value: float
    entries: List[TimetableEntryResponse]
