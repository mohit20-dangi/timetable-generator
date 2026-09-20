from pydantic import BaseModel
from typing import Optional, List, Any, Dict


class AgentPlanRequest(BaseModel):
    department_id: str
    instruction: str


class ProposedAction(BaseModel):
    action_type: str  # update_teacher_limits | create_constraint_rule
    description: str  # plain-English summary shown to the admin for approval
    payload: Dict[str, Any]  # exact data needed to apply this action


class AgentPlanResponse(BaseModel):
    summary: str
    actions: List[ProposedAction]


class AgentApplyRequest(BaseModel):
    department_id: str
    instruction: str  # kept for the audit log, so "why" is never lost
    actions: List[ProposedAction]


class AgentApplyResponse(BaseModel):
    applied: int
    audit_log_ids: List[int]
