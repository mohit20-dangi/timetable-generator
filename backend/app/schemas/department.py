from pydantic import BaseModel
from typing import Optional


class DepartmentBase(BaseModel):
    name: str
    code: Optional[str] = None


class DepartmentCreate(DepartmentBase):
    id: str


class DepartmentUpdate(DepartmentBase):
    pass


class DepartmentResponse(DepartmentBase):
    id: str

    class Config:
        from_attributes = True
