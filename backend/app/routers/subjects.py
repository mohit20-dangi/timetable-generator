from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Subject
from app.schemas import SubjectCreate, SubjectResponse

router = APIRouter(prefix="/api/subjects", tags=["Subjects"])

@router.post("/", response_model=SubjectResponse)
def create_subject(subject: SubjectCreate, db: Session = Depends(get_db)):
    db_subject = Subject(**subject.model_dump())
    db.add(db_subject)
    db.commit()
    db.refresh(db_subject)
    return db_subject

@router.get("/", response_model=List[SubjectResponse])
def list_subjects(db: Session = Depends(get_db)):
    return db.query(Subject).all()

@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(subject_id: str, db: Session = Depends(get_db)):
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject

@router.delete("/{subject_id}")
def delete_subject(subject_id: str, db: Session = Depends(get_db)):
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    db.delete(subject)
    db.commit()
    return {"message": "Subject deleted"}