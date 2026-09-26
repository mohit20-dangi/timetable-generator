from pydantic import BaseModel, Field, model_validator
from typing import Optional, List

VALID_DELIVERY_MODES = {"IN_PERSON", "MOOC_NPTEL", "SELF_STUDY", "INDUSTRY"}
VALID_BATCH_SCHEDULING_MODES = {"independent", "parallel", "sequential", "merged"}


class SubjectBase(BaseModel):
    name: str
    # Short printed code for exports (e.g. "CO4_PDQA") - Phase 4.1. None
    # means "derive from the id", not "no code"; the router does the
    # deriving since `id` isn't part of this base schema.
    code: Optional[str] = None
    type: str  # validated against the subject_types catalog by the router, not here
    department_id: Optional[str] = None
    category: Optional[str] = None
    delivery_mode: str = "IN_PERSON"

    lecture_hours: int = 0
    tutorial_hours: int = 0
    practical_hours: int = 0

    scheme_hours_per_week: Optional[int] = None
    # None means "derive from L+T+P" (Phase 2.3) rather than "zero" - an
    # admin who explicitly wants 0 contact hours passes 0, not None.
    weekly_hours: Optional[int] = None

    sessions_per_week: Optional[int] = None  # None means "derive from weekly_hours / periods_per_session"
    periods_per_session: int = 1
    back_to_back: bool = True
    # independent (default, only soft-nudged) | parallel (same start, hard,
    # separate rooms/teachers) | sequential (hard, never overlap) | merged
    # (hard, same start+room+teacher - taught as one combined class). See
    # Subject.batch_scheduling_mode's docstring.
    batch_scheduling_mode: str = "independent"

    max_per_day: int = 1
    requires_room_type: Optional[str] = None
    requires_equipment: List[str] = Field(default_factory=list)
    linked_group_id: Optional[str] = None
    elective_group_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate(self):
        if self.delivery_mode not in VALID_DELIVERY_MODES:
            raise ValueError(f"delivery_mode must be one of {sorted(VALID_DELIVERY_MODES)}")
        if self.batch_scheduling_mode not in VALID_BATCH_SCHEDULING_MODES:
            raise ValueError(f"batch_scheduling_mode must be one of {sorted(VALID_BATCH_SCHEDULING_MODES)}")
        if self.periods_per_session < 1:
            raise ValueError("periods_per_session must be at least 1")
        if self.max_per_day < 1:
            raise ValueError("max_per_day must be at least 1")

        if self.weekly_hours is None:
            if self.delivery_mode == "IN_PERSON":
                self.weekly_hours = self.lecture_hours + self.tutorial_hours + self.practical_hours
            else:
                self.weekly_hours = 0
        if self.weekly_hours < 0:
            raise ValueError("weekly_hours cannot be negative")
        if self.delivery_mode == "IN_PERSON" and self.weekly_hours <= 0:
            raise ValueError("IN_PERSON subjects must have contact hours > 0 to be schedulable")

        if self.sessions_per_week is None:
            self.sessions_per_week = self.weekly_hours // self.periods_per_session
        if self.sessions_per_week < 0:
            raise ValueError("sessions_per_week cannot be negative")
        return self


class SubjectCreate(SubjectBase):
    id: str


class SubjectResponse(SubjectBase):
    id: str

    class Config:
        from_attributes = True
