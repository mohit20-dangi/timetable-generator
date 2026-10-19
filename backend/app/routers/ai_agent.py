from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Teacher, ConstraintRule, AuditLog, User
from app.schemas.ai_agent import AgentPlanRequest, AgentPlanResponse, AgentApplyRequest, AgentApplyResponse, ProposedAction
from app.auth.dependencies import require_dept_admin
from app.auth.scope import assert_can_manage, target_department
from app.services.ai_agent import run_agent_plan

router = APIRouter(prefix="/api/ai/agent", tags=["AI Assistant"])


@router.post("/plan", response_model=AgentPlanResponse)
def plan(request: AgentPlanRequest, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    """Proposes changes for the instruction, but changes NOTHING. See
    app/services/ai_agent.py's module docstring for why this split exists."""
    try:
        result = run_agent_plan(db, target_department(admin, request.department_id), request.instruction)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        # Bad key, unreachable provider, model that doesn't support tool
        # calls, malformed tool arguments... say which, instead of a bare 500.
        raise HTTPException(
            status_code=502,
            detail=f"The AI request failed ({type(e).__name__}: {e}). Nothing was changed.",
        ) from e
    return AgentPlanResponse(summary=result["summary"], actions=[ProposedAction(**a) for a in result["actions"]])


@router.post("/apply", response_model=AgentApplyResponse)
def apply(request: AgentApplyRequest, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    """Applies an admin-approved (and possibly edited) action list. Never
    called by the model - only by the admin clicking 'Apply' in the UI
    after reviewing the plan."""
    audit_ids = []
    skipped = []
    for action in request.actions:
        if action.action_type == "update_teacher_limits":
            teacher = db.query(Teacher).filter(Teacher.id == action.payload["teacher_id"]).first()
            if not teacher:
                skipped.append(f"{action.description}: teacher '{action.payload['teacher_id']}' no longer exists.")
                continue
            assert_can_manage(admin, teacher.department_id)
            before = {action.payload["field"]: getattr(teacher, action.payload["field"])}
            setattr(teacher, action.payload["field"], action.payload["new_value"])
            after = {action.payload["field"]: action.payload["new_value"]}
            log = AuditLog(
                actor_user_id=admin.id, action="ai_update_teacher_limits", entity_type="teacher",
                entity_id=teacher.id, before=before, after=after, reason=request.instruction,
            )
            db.add(log)
            db.flush()
            audit_ids.append(log.id)

        elif action.action_type == "create_constraint_rule":
            payload = dict(action.payload)
            payload["department_id"] = target_department(admin, payload.get("department_id"))
            if db.query(ConstraintRule).filter(ConstraintRule.id == payload["id"]).first():
                skipped.append(f"{action.description}: a rule with id '{payload['id']}' already exists (was this already applied?).")
                continue
            rule = ConstraintRule(**{k: v for k, v in payload.items() if k in ConstraintRule.__table__.columns.keys()})
            db.add(rule)
            log = AuditLog(
                actor_user_id=admin.id, action="ai_create_constraint_rule", entity_type="constraint_rule",
                entity_id=payload["id"], before=None, after=payload, reason=request.instruction,
            )
            db.add(log)
            db.flush()
            audit_ids.append(log.id)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Saving the changes failed ({type(e).__name__}: {e}). Nothing was changed.",
        ) from e
    return AgentApplyResponse(applied=len(audit_ids), audit_log_ids=audit_ids, skipped=skipped)
