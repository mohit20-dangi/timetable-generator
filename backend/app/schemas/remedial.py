from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.solver.calendar import DAY_ORDER


class RemedialSettings(BaseModel):
    """Admin-chosen constraints for one remedial run. Every number is here so
    nothing about how remedial classes are placed is hardcoded."""
    # Per section, across every subject: aim for this many remedial periods a
    # day, never exceed the hard limit ("one a day, two if there's no way").
    preferred_max_per_day: int = Field(1, ge=1, le=8)
    hard_max_per_day: int = Field(2, ge=1, le=8)
    # Free periods inside the main timetable's bell schedule may be used, in
    # addition to the department's remedial-only slots (after hours, Saturday).
    use_free_regular_slots: bool = True
    # A teacher's remedial load, on top of the main timetable (which is frozen).
    teacher_max_remedial_per_day: int = Field(2, ge=1, le=8)
    teacher_max_remedial_per_week: int = Field(6, ge=1, le=40)
    # Soft preferences: penalty per violation.
    weight_mid_day_gap: int = Field(10, ge=0, le=1000)
    weight_non_regular_teacher: int = Field(8, ge=0, le=1000)
    weight_over_preferred_per_day: int = Field(20, ge=0, le=1000)
    max_seconds: int = Field(60, ge=5, le=600)

    @model_validator(mode="after")
    def _limits_agree(self):
        if self.preferred_max_per_day > self.hard_max_per_day:
            raise ValueError("preferred_max_per_day cannot exceed hard_max_per_day")
        return self


class RemedialGroupBase(BaseModel):
    name: str
    subject_id: str
    section_ids: List[str] = Field(min_length=1)
    strength: int = Field(ge=1)
    periods_per_week: int = Field(1, ge=1, le=40)
    periods_per_session: int = Field(1, ge=1, le=6)
    teacher_id: Optional[str] = None
    allowed_days: Optional[List[str]] = None
    is_active: bool = True

    @model_validator(mode="after")
    def _validate(self):
        bad = [d for d in (self.allowed_days or []) if d not in DAY_ORDER]
        if bad:
            raise ValueError(f"allowed_days must be from {DAY_ORDER}, got {bad}")
        if self.periods_per_session > self.periods_per_week:
            raise ValueError("periods_per_session cannot exceed periods_per_week")
        return self


class RemedialGroupCreate(RemedialGroupBase):
    id: str
    department_id: Optional[str] = None


class RemedialGroupResponse(RemedialGroupBase):
    id: str
    department_id: str

    class Config:
        from_attributes = True


class RemedialRunCreate(BaseModel):
    department_id: Optional[str] = None
    settings: RemedialSettings = RemedialSettings()


class RemedialRunResponse(BaseModel):
    id: int
    department_id: str
    status: str
    settings: Optional[Dict[str, Any]] = None
    solver_output: Optional[Dict[str, Any]] = None
    explanation: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    is_published: bool = False

    class Config:
        from_attributes = True


class RemedialEntryResponse(BaseModel):
    id: int
    session_group: Optional[str] = None
    day: str
    period: int
    group_id: Optional[str] = None
    subject_id: Optional[str] = None
    teacher_id: Optional[str] = None
    room_id: Optional[str] = None
    in_remedial_slot: bool = False

    class Config:
        from_attributes = True
