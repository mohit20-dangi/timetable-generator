from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import AcademicTerm, User
from app.schemas import AcademicTermCreate, AcademicTermResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/academic-terms", tags=["Academic Terms"])


@router.post("/", response_model=AcademicTermResponse)
def create_term(payload: AcademicTermCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if payload.start_date >= payload.end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")
    if db.query(AcademicTerm).filter(AcademicTerm.id == payload.id).first():
        raise HTTPException(status_code=409, detail="A term with this id already exists")
    record = AcademicTerm(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    response = AcademicTermResponse.model_validate(record)
    response.teaching_weeks = record.teaching_weeks
    return response


@router.get("/", response_model=List[AcademicTermResponse])
def list_terms(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    records = db.query(AcademicTerm).all()
    result = []
    for record in records:
        response = AcademicTermResponse.model_validate(record)
        response.teaching_weeks = record.teaching_weeks
        result.append(response)
    return result


@router.get("/{term_id}", response_model=AcademicTermResponse)
def get_term(term_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    record = db.query(AcademicTerm).filter(AcademicTerm.id == term_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Academic term not found")
    response = AcademicTermResponse.model_validate(record)
    response.teaching_weeks = record.teaching_weeks
    return response


@router.delete("/{term_id}")
def delete_term(term_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(AcademicTerm).filter(AcademicTerm.id == term_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Academic term not found")
    db.delete(record)
    db.commit()
    return {"message": "Academic term deleted"}
