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
    # Candidates that are NOT ConstraintRules and so can't live in
    # parsed_constraints: a lab rotation is its own record (several lab
    # subjects for one section, with a different batch in each), and a
    # teacher count is an edit to a Subject. Both are still only
    # candidates - the admin reviews and saves them, exactly as with rules.
    lab_rotations: List[Dict[str, Any]] = []
    subject_teacher_counts: List[Dict[str, Any]] = []
