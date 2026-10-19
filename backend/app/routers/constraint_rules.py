from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db import get_db
from app.models import ConstraintRule, User
from app.schemas import ConstraintRuleCreate, ConstraintRuleResponse
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import get_scoped_or_404, scoped, target_department

router = APIRouter(prefix="/api/constraint-rules", tags=["Constraint Rules"])


@router.post("/", response_model=ConstraintRuleResponse)
def create_rule(payload: ConstraintRuleCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if db.query(ConstraintRule).filter(ConstraintRule.id == payload.id).first():
        raise HTTPException(status_code=409, detail="A rule with this id already exists")
    data = payload.model_dump()
    data["department_id"] = target_department(admin, data.get("department_id"))
    record = ConstraintRule(**data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[ConstraintRuleResponse])
def list_rules(
    department_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return scoped(db.query(ConstraintRule), ConstraintRule, user, department_id).all()


@router.put("/{rule_id}", response_model=ConstraintRuleResponse)
def update_rule(rule_id: str, payload: ConstraintRuleCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, ConstraintRule, rule_id, admin, "Rule")
    for key, value in payload.model_dump(exclude={"id", "department_id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, ConstraintRule, rule_id, admin, "Rule")
    db.delete(record)
    db.commit()
    return {"message": "Rule deleted"}
