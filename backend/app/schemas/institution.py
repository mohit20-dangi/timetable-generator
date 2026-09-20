from pydantic import BaseModel
from typing import Optional


class InstitutionBase(BaseModel):
    name: str
    city: Optional[str] = None
    timezone: str = "Asia/Kolkata"


class InstitutionCreate(InstitutionBase):
    id: str


class InstitutionResponse(InstitutionBase):
    id: str

    class Config:
        from_attributes = True
