from pydantic import BaseModel
from typing import Any, Dict, List


class TimetableAIPlanRequest(BaseModel):
    instruction: str


class TimetableAIAction(BaseModel):
    action_type: str  # "exclude_subject" | "change_weekly_hours"
    description: str
    payload: Dict[str, Any]


class TimetableAIPlanResponse(BaseModel):
    summary: str
    actions: List[TimetableAIAction]


class TimetableAIApplyRequest(BaseModel):
    # The admin's reviewed (possibly trimmed/edited) action list - never
    # applied straight from the model's own plan response, exactly like
    # app/services/ai_agent.py's apply step.
    actions: List[TimetableAIAction]
