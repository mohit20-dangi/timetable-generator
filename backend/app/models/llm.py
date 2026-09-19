from pydantic import BaseModel
from typing import Dict, Any


class NLConstraintParseRequest(BaseModel):
    text: str


class NLConstraintParseResponse(BaseModel):
    parsed_constraints: Dict[str, Any]
    raw_response: str
