from pydantic import BaseModel
from typing import Optional


class SubjectTypeBase(BaseModel):
    name: str
    default_block_size: int = 1
    default_room_type: Optional[str] = None
    colour_hex: str = "E5E7EB"


class SubjectTypeCreate(SubjectTypeBase):
    id: str


class SubjectTypeResponse(SubjectTypeBase):
    id: str
    is_builtin: bool

    class Config:
        from_attributes = True
