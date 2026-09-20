from pydantic import BaseModel
from typing import Optional


class DepartmentBase(BaseModel):
    name: str
    code: Optional[str] = None


class DepartmentCreate(DepartmentBase):
    id: str
    institution_id: str


class DepartmentResponse(DepartmentBase):
    id: str
    institution_id: str

    class Config:
        from_attributes = True
