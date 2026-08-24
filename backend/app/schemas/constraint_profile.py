from pydantic import BaseModel
from typing import Dict

class ConstraintProfileBase(BaseModel):
    name: str
    soft_constraint_weights: dict = {}

class ConstraintProfileCreate(ConstraintProfileBase):
    id: str

class ConstraintProfileResponse(ConstraintProfileBase):
    id: str
    
    class Config:
        from_attributes = True