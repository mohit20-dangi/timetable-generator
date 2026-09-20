from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Department, Institution, User
from app.schemas import DepartmentCreate, DepartmentResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/departments", tags=["Departments"])


@router.post("/", response_model=DepartmentResponse)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if not db.query(Institution).filter(Institution.id == payload.institution_id).first():
        raise HTTPException(status_code=400, detail="institution_id does not exist")
    if db.query(Department).filter(Department.id == payload.id).first():
        raise HTTPException(status_code=409, detail="A department with this id already exists")
    record = Department(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[DepartmentResponse])
def list_departments(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Department).all()


@router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(department_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    record = db.query(Department).filter(Department.id == department_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Department not found")
    return record


@router.delete("/{department_id}")
def delete_department(department_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(Department).filter(Department.id == department_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Department not found")
    db.delete(record)
    db.commit()
    return {"message": "Department deleted"}
