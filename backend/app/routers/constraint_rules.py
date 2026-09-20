from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db import get_db
from app.models import ConstraintRule, User
from app.schemas import ConstraintRuleCreate, ConstraintRuleResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/constraint-rules", tags=["Constraint Rules"])


@router.post("/", response_model=ConstraintRuleResponse)
def create_rule(payload: ConstraintRuleCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(ConstraintRule).filter(ConstraintRule.id == payload.id).first():
        raise HTTPException(status_code=409, detail="A rule with this id already exists")
    record = ConstraintRule(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[ConstraintRuleResponse])
def list_rules(
    department_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = db.query(ConstraintRule)
    if department_id:
        query = query.filter(ConstraintRule.department_id == department_id)
    return query.all()


@router.put("/{rule_id}", response_model=ConstraintRuleResponse)
def update_rule(rule_id: str, payload: ConstraintRuleCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(ConstraintRule).filter(ConstraintRule.id == rule_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Rule not found")
    for key, value in payload.model_dump(exclude={"id", "department_id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(ConstraintRule).filter(ConstraintRule.id == rule_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(record)
    db.commit()
    return {"message": "Rule deleted"}
