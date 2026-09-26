from pydantic import BaseModel
from typing import Optional


class NLMoveParseRequest(BaseModel):
    text: str
    subject_id: str
    current_day: str
    current_period: int


class NLMoveParseResponse(BaseModel):
    # None means the model couldn't confidently resolve one slot from the
    # catalog it was given - the admin still picks manually in that case,
    # same as if they'd never used the AI box at all.
    new_day: Optional[str] = None
    new_period: Optional[int] = None
    note: str = ""
