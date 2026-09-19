from pydantic import BaseModel
from typing import Any, Dict


class ConstraintProfileCreate(BaseModel):
    id: str
    name: str
    soft_constraint_weights: Dict[str, Any] = {}


class ConstraintProfileResponse(ConstraintProfileCreate):
    pass
