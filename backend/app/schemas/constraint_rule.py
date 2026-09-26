from pydantic import BaseModel, model_validator
from typing import Optional
from datetime import time

VALID_RULE_TYPES = {
    "teacher_unavailable", "room_unavailable", "section_unavailable",
    "teacher_preferred", "max_daily_override", "batch_scheduling_mode", "custom",
}
VALID_TARGET_TYPES = {"teacher", "room", "section", "subject"}
VALID_PRIORITIES = {"hard", "soft"}
VALID_BATCH_MODES = {"independent", "parallel", "sequential", "merged"}


class ConstraintRuleBase(BaseModel):
    rule_type: str
    target_type: str
    target_id: str
    day: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    priority: str = "hard"
    weight: int = 0
    # Only meaningful (and required) when rule_type == "batch_scheduling_mode":
    # overrides that subject's Subject.batch_scheduling_mode, optionally
    # confined to the day/start_time/end_time window above.
    batch_mode: Optional[str] = None
    description: Optional[str] = None
    source: str = "manual"
    raw_instruction: Optional[str] = None
    is_active: bool = True

    @model_validator(mode="after")
    def _validate(self):
        if self.rule_type not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type must be one of {sorted(VALID_RULE_TYPES)}")
        if self.target_type not in VALID_TARGET_TYPES:
            raise ValueError(f"target_type must be one of {sorted(VALID_TARGET_TYPES)}")
        if self.priority not in VALID_PRIORITIES:
            raise ValueError(f"priority must be one of {sorted(VALID_PRIORITIES)}")
        if self.rule_type == "batch_scheduling_mode":
            if self.target_type != "subject":
                raise ValueError("batch_scheduling_mode rules must target a subject")
            if self.batch_mode not in VALID_BATCH_MODES:
                raise ValueError(f"batch_mode must be one of {sorted(VALID_BATCH_MODES)}")
        return self


class ConstraintRuleCreate(ConstraintRuleBase):
    id: str
    department_id: str


class ConstraintRuleResponse(ConstraintRuleBase):
    id: str
    department_id: str

    class Config:
        from_attributes = True
