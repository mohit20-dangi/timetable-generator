from pydantic import BaseModel
from typing import Optional


class EquipmentBase(BaseModel):
    name: str


class EquipmentCreate(EquipmentBase):
    id: str
    # Blank = the creating user's own department.
    department_id: Optional[str] = None


class EquipmentResponse(EquipmentBase):
    id: str
    department_id: Optional[str] = None

    class Config:
        from_attributes = True
