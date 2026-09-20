from pydantic import BaseModel
from typing import Optional


class SectionBase(BaseModel):
    name: str
    strength: int = 60


class SectionCreate(SectionBase):
    id: str
    year_id: str


class SectionResponse(SectionBase):
    id: str
    year_id: str

    class Config:
        from_attributes = True
