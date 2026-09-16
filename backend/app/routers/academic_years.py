from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import AcademicYear, User
from app.schemas import AcademicYearCreate, AcademicYearResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/years", tags=["Academic Years"])

@router.post("/", response_model=AcademicYearResponse)
def create_academic_year(year: AcademicYearCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    db_year = AcademicYear(**year.model_dump())
    db.add(db_year)
    db.commit()
    db.refresh(db_year)
    return db_year

@router.get("/", response_model=List[AcademicYearResponse])
def list_academic_years(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(AcademicYear).all()

@router.get("/{year_id}", response_model=AcademicYearResponse)
def get_academic_year(year_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    year = db.query(AcademicYear).filter(AcademicYear.id == year_id).first()
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")
    return year

@router.put("/{year_id}", response_model=AcademicYearResponse)
def update_academic_year(year_id: str, year: AcademicYearCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(AcademicYear).filter(AcademicYear.id == year_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Academic year not found")
    for key, value in year.model_dump(exclude={"id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record

@router.delete("/{year_id}")
def delete_academic_year(year_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    year = db.query(AcademicYear).filter(AcademicYear.id == year_id).first()
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")
    db.delete(year)
    db.commit()
    return {"message": "Academic year deleted"}
