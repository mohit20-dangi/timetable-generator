from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import SubjectType, Subject, User
from app.schemas import SubjectTypeCreate, SubjectTypeResponse
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import get_scoped_or_404, list_department, target_department

router = APIRouter(prefix="/api/subject-types", tags=["Subject Types"])

def _visible(query, model, user: User, department_id=None):
    """A department sees its own entries plus the shared ones (department
    NULL: the built-in subject types, and anything from before departments
    were separated). Only its own are editable - shared ones belong to the
    superadmin."""
    department_id = list_department(user, department_id)
    if department_id is None:
        return query
    return query.filter(or_(model.department_id == department_id, model.department_id.is_(None)))


@router.post("/", response_model=SubjectTypeResponse)
def create_subject_type(payload: SubjectTypeCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if db.query(SubjectType).filter(SubjectType.id == payload.id).first():
        raise HTTPException(status_code=409, detail="This subject type id is already taken - pick another")
    data = payload.model_dump()
    data["department_id"] = target_department(admin, data.get("department_id"))
    record = SubjectType(**data, is_builtin=False)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[SubjectTypeResponse])
def list_subject_types(department_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _visible(db.query(SubjectType), SubjectType, user, department_id).all()


@router.put("/{type_id}", response_model=SubjectTypeResponse)
def update_subject_type(type_id: str, payload: SubjectTypeCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, SubjectType, type_id, admin, "Subject type")
    for key, value in payload.model_dump(exclude={"id", "department_id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{type_id}")
def delete_subject_type(type_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, SubjectType, type_id, admin, "Subject type")
    if record.is_builtin:
        raise HTTPException(status_code=409, detail="Built-in subject types (theory, lab, tutorial) cannot be deleted")
    in_use = db.query(Subject).filter(Subject.type == type_id).count()
    if in_use:
        raise HTTPException(status_code=409, detail=f"{in_use} subject(s) still use this type")
    db.delete(record)
    db.commit()
    return {"message": "Subject type deleted"}
