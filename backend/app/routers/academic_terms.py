from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import AcademicTerm, User
from app.schemas import AcademicTermCreate, AcademicTermResponse
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import get_scoped_or_404, scoped, target_department

router = APIRouter(prefix="/api/academic-terms", tags=["Academic Terms"])


@router.post("/", response_model=AcademicTermResponse)
def create_term(payload: AcademicTermCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if payload.start_date >= payload.end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")
    if db.query(AcademicTerm).filter(AcademicTerm.id == payload.id).first():
        raise HTTPException(status_code=409, detail="A term with this id already exists")
    data = payload.model_dump()
    data["department_id"] = target_department(admin, data.get("department_id"))
    record = AcademicTerm(**data)
    db.add(record)
    db.commit()
    db.refresh(record)
    response = AcademicTermResponse.model_validate(record)
    response.teaching_weeks = record.teaching_weeks
    return response


@router.get("/", response_model=List[AcademicTermResponse])
def list_terms(department_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    records = scoped(db.query(AcademicTerm), AcademicTerm, user, department_id).all()
    result = []
    for record in records:
        response = AcademicTermResponse.model_validate(record)
        response.teaching_weeks = record.teaching_weeks
        result.append(response)
    return result


@router.get("/{term_id}", response_model=AcademicTermResponse)
def get_term(term_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = get_scoped_or_404(db, AcademicTerm, term_id, user, "Academic term")
    response = AcademicTermResponse.model_validate(record)
    response.teaching_weeks = record.teaching_weeks
    return response


@router.delete("/{term_id}")
def delete_term(term_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, AcademicTerm, term_id, admin, "Academic term")
    db.delete(record)
    db.commit()
    return {"message": "Academic term deleted"}
