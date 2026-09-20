from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Institution, User
from app.schemas import InstitutionCreate, InstitutionResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/institutions", tags=["Institutions"])


@router.post("/", response_model=InstitutionResponse)
def create_institution(payload: InstitutionCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(Institution).filter(Institution.id == payload.id).first():
        raise HTTPException(status_code=409, detail="An institution with this id already exists")
    record = Institution(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[InstitutionResponse])
def list_institutions(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Institution).all()


@router.get("/{institution_id}", response_model=InstitutionResponse)
def get_institution(institution_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    record = db.query(Institution).filter(Institution.id == institution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Institution not found")
    return record


@router.delete("/{institution_id}")
def delete_institution(institution_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(Institution).filter(Institution.id == institution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Institution not found")
    db.delete(record)
    db.commit()
    return {"message": "Institution deleted"}
