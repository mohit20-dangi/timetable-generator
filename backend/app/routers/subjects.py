from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Subject, User
from app.schemas import SubjectCreate, SubjectResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/subjects", tags=["Subjects"])

@router.post("/", response_model=SubjectResponse)
def create_subject(subject: SubjectCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    db_subject = Subject(**subject.model_dump())
    db.add(db_subject)
    db.commit()
    db.refresh(db_subject)
    return db_subject

@router.get("/", response_model=List[SubjectResponse])
def list_subjects(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Subject).all()

@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(subject_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject

@router.put("/{subject_id}", response_model=SubjectResponse)
def update_subject(subject_id: str, subject: SubjectCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(Subject).filter(Subject.id == subject_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Subject not found")
    for key, value in subject.model_dump(exclude={"id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record

@router.delete("/{subject_id}")
def delete_subject(subject_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    db.delete(subject)
    db.commit()
    return {"message": "Subject deleted"}
