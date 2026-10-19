from datetime import time
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

VALID_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


class LabRotationGroupBase(BaseModel):
    name: str
    section_id: str
    # The labs that rotate. Two is the minimum that means anything: with one
    # subject there is nothing to swap into, and the group would silently
    # behave like no rotation at all.
    subject_ids: List[str] = Field(default_factory=list)
    # Optional pinned window, all-or-nothing: "Monday 14:00-16:00". Without
    # it the solver puts the rounds wherever they fit best.
    day: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_active: bool = True

    @model_validator(mode="after")
    def _validate(self):
        if len(self.subject_ids) < 2:
            raise ValueError("A lab rotation needs at least two lab subjects to rotate between")
        if len(set(self.subject_ids)) != len(self.subject_ids):
            raise ValueError("subject_ids contains the same subject more than once")
        if self.day is not None and self.day not in VALID_DAYS:
            raise ValueError(f"day must be one of {sorted(VALID_DAYS)}")
        window = [self.day, self.start_time, self.end_time]
        if any(v is not None for v in window) and any(v is None for v in window):
            raise ValueError(
                "A pinned window needs all of day, start_time and end_time - or none of them, "
                "to let the solver place the rotation itself"
            )
        if self.start_time is not None and self.end_time is not None and self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self


class LabRotationGroupCreate(LabRotationGroupBase):
    id: str
    department_id: Optional[str] = None


class LabRotationGroupResponse(LabRotationGroupBase):
    id: str
    department_id: str
    source: str = "manual"
    raw_instruction: Optional[str] = None

    class Config:
        from_attributes = True


class LabRotationPreflightIssue(BaseModel):
    severity: str  # blocking | warning
    message: str
    kind: Optional[str] = None  # subjects | batches | teachers | rooms | window


class LabRotationPreflightResponse(BaseModel):
    """Answers "will this rotation actually work?" before the admin ever
    clicks Generate - the same arithmetic the solver would hit, reported in
    plain language instead of as an INFEASIBLE."""
    feasible: bool
    batch_count: int
    round_count: int          # total lab sessions a week across the group
    issues: List[LabRotationPreflightIssue]
