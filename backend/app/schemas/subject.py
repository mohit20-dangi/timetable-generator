from pydantic import BaseModel, Field, model_validator
from typing import Optional, List

VALID_TYPES = {"theory", "lab", "tutorial"}
VALID_DELIVERY_MODES = {"IN_PERSON", "MOOC_NPTEL", "SELF_STUDY", "INDUSTRY"}


class SubjectBase(BaseModel):
    name: str
    type: str
    department_id: Optional[str] = None
    category: Optional[str] = None
    delivery_mode: str = "IN_PERSON"
    scheme_hours_per_week: Optional[int] = None
    weekly_hours: int = 0
    needs_continuous_block: bool = False
    block_size: int = 1
    max_per_day: int = 1
    requires_room_type: Optional[str] = None
    requires_equipment: List[str] = Field(default_factory=list)
    linked_group_id: Optional[str] = None
    elective_group_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate(self):
        if self.type not in VALID_TYPES:
            raise ValueError(f"type must be one of {sorted(VALID_TYPES)}")
        if self.delivery_mode not in VALID_DELIVERY_MODES:
            raise ValueError(f"delivery_mode must be one of {sorted(VALID_DELIVERY_MODES)}")
        if self.delivery_mode == "IN_PERSON" and self.weekly_hours <= 0:
            raise ValueError("IN_PERSON subjects must have weekly_hours > 0 to be schedulable")
        if self.block_size < 1:
            raise ValueError("block_size must be at least 1")
        if self.max_per_day < 1:
            raise ValueError("max_per_day must be at least 1")
        return self


class SubjectCreate(SubjectBase):
    id: str


class SubjectResponse(SubjectBase):
    id: str

    class Config:
        from_attributes = True
