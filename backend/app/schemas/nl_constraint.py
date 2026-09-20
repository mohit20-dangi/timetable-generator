from pydantic import BaseModel
from typing import Optional, Dict, Any, List


class NLConstraintParseRequest(BaseModel):
    text: str
    department_id: Optional[str] = None


class NLConstraintParseResponse(BaseModel):
    parsed_constraints: Dict[str, Any]
    raw_response: str
    ambiguities: List[str] = []
    unsupported_requests: List[str] = []
