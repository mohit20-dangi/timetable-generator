from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import SubjectType, Subject, User
from app.schemas import SubjectTypeCreate, SubjectTypeResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/subject-types", tags=["Subject Types"])


@router.post("/", response_model=SubjectTypeResponse)
def create_subject_type(payload: SubjectTypeCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(SubjectType).filter(SubjectType.id == payload.id).first():
        raise HTTPException(status_code=409, detail="A subject type with this id already exists")
    record = SubjectType(**payload.model_dump(), is_builtin=False)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[SubjectTypeResponse])
def list_subject_types(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(SubjectType).all()


@router.put("/{type_id}", response_model=SubjectTypeResponse)
def update_subject_type(type_id: str, payload: SubjectTypeCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(SubjectType).filter(SubjectType.id == type_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Subject type not found")
    for key, value in payload.model_dump(exclude={"id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{type_id}")
def delete_subject_type(type_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(SubjectType).filter(SubjectType.id == type_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Subject type not found")
    if record.is_builtin:
        raise HTTPException(status_code=409, detail="Built-in subject types (theory, lab, tutorial) cannot be deleted")
    in_use = db.query(Subject).filter(Subject.type == type_id).count()
    if in_use:
        raise HTTPException(status_code=409, detail=f"{in_use} subject(s) still use this type")
    db.delete(record)
    db.commit()
    return {"message": "Subject type deleted"}
