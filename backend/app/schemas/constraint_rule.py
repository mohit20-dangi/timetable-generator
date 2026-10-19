from pydantic import BaseModel, model_validator
from typing import Optional, Dict, Any
from datetime import time

VALID_RULE_TYPES = {
    "teacher_unavailable", "room_unavailable", "section_unavailable",
    "teacher_preferred", "max_daily_override", "batch_scheduling_mode", "custom",
    # Admin-defined preference templates - see app/solver/custom_rules.py.
    "subject_time_window", "max_subjects_per_day", "teacher_max_days_per_week",
}
# rule_type -> the target_type it must use ("section" also accepts "*" = every section).
CUSTOM_RULE_TARGETS = {
    "subject_time_window": "subject",
    "max_subjects_per_day": "section",
    "teacher_max_days_per_week": "teacher",
}
VALID_TARGET_TYPES = {"teacher", "room", "section", "subject"}
VALID_PRIORITIES = {"hard", "soft"}
# "Unavailable" means never, so it is always hard. "Prefers" is always a soft
# nudge (its strength is the teacher_preferred_slots importance level).
FIXED_PRIORITY_RULE_TYPES = {
    "teacher_unavailable": "hard",
    "room_unavailable": "hard",
    "teacher_preferred": "soft",
}
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
    params: Optional[Dict[str, Any]] = None
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
        # The priority of these types isn't the admin's choice, so it is
        # corrected rather than rejected - an old row saved as "soft"
        # unavailable (or an AI-proposed one) must still load.
        if self.rule_type in FIXED_PRIORITY_RULE_TYPES:
            self.priority = FIXED_PRIORITY_RULE_TYPES[self.rule_type]
            self.weight = 0
        if self.rule_type == "batch_scheduling_mode":
            if self.target_type != "subject":
                raise ValueError("batch_scheduling_mode rules must target a subject")
            if self.batch_mode not in VALID_BATCH_MODES:
                raise ValueError(f"batch_mode must be one of {sorted(VALID_BATCH_MODES)}")
        if self.rule_type in CUSTOM_RULE_TARGETS:
            expected = CUSTOM_RULE_TARGETS[self.rule_type]
            if self.target_type != expected:
                raise ValueError(f"{self.rule_type} rules must target a {expected}")
            params = self.params or {}
            if self.rule_type == "subject_time_window":
                if params.get("mode", "within") not in ("within", "avoid"):
                    raise ValueError("params.mode must be 'within' or 'avoid'")
                if self.start_time is None or self.end_time is None:
                    raise ValueError("subject_time_window needs start_time and end_time")
                if self.start_time >= self.end_time:
                    raise ValueError("start_time must be before end_time")
            else:
                limit = params.get("max")
                if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                    raise ValueError("params.max must be a whole number of at least 1")
            if self.priority == "soft" and self.weight <= 0:
                raise ValueError("a soft rule needs a weight above 0 (otherwise it has no effect)")
        return self


class ConstraintRuleCreate(ConstraintRuleBase):
    id: str
    department_id: str


class ConstraintRuleResponse(ConstraintRuleBase):
    id: str
    department_id: str

    class Config:
        from_attributes = True
