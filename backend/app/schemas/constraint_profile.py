from pydantic import BaseModel
from typing import Optional


class ConstraintProfileBase(BaseModel):
    name: str
    department_id: Optional[str] = None
    soft_constraint_weights: dict = {}


class ConstraintProfileCreate(ConstraintProfileBase):
    id: str


class ConstraintProfileResponse(ConstraintProfileBase):
    id: str

    class Config:
        from_attributes = True
