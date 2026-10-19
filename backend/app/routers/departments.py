from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import (
    AcademicTerm, AcademicYear, ConstraintProfile, ConstraintRule, Department, ElectiveGroup, Equipment,
    Institution, Room, Subject, SubjectType, Teacher, TimeSlot, TimetableRun, User,
)
from app.schemas import DepartmentCreate, DepartmentResponse, DepartmentUpdate
from app.auth.dependencies import get_current_user, require_dept_admin, require_superadmin
from app.auth.scope import assert_can_manage, is_superadmin

router = APIRouter(prefix="/api/departments", tags=["Departments"])

# A department can only be deleted once nothing belongs to it any more -
# silently orphaning (or cascading away) a department's whole setup is not
# something one click should do.
OWNED_BY_DEPARTMENT = [
    ("academic years", AcademicYear), ("subjects", Subject), ("teachers", Teacher), ("rooms", Room),
    ("elective groups", ElectiveGroup), ("timetables", TimetableRun), ("users", User),
    ("time slots", TimeSlot), ("terms", AcademicTerm), ("scheduling rules", ConstraintRule),
    ("constraint profiles", ConstraintProfile), ("subject types", SubjectType), ("equipment", Equipment),
]


def _legacy_institution_id(db: Session):
    """Databases created before institutions were removed still have a
    NOT NULL departments.institution_id column; give new departments the
    existing institution there. A fresh database has a nullable column and
    no institution, so this is None."""
    columns = {c["name"]: c for c in inspect(db.bind).get_columns("departments")}
    if columns.get("institution_id", {}).get("nullable", True):
        return None
    institution = db.query(Institution).first()
    if institution is None:
        institution = Institution(id="default", name="Default")
        db.add(institution)
        db.flush()
    return institution.id


@router.post("/", response_model=DepartmentResponse)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), _admin: User = Depends(require_superadmin)):
    if db.query(Department).filter(Department.id == payload.id).first():
        raise HTTPException(status_code=409, detail="A department with this id already exists")
    record = Department(**payload.model_dump(), institution_id=_legacy_institution_id(db))
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[DepartmentResponse])
def list_departments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Department).order_by(Department.name)
    if not is_superadmin(user):
        query = query.filter(Department.id == user.department_id)
    return query.all()


@router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(department_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = db.query(Department).filter(Department.id == department_id).first()
    if not record or (not is_superadmin(user) and user.department_id != department_id):
        raise HTTPException(status_code=404, detail="Department not found")
    return record


@router.put("/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: str, payload: DepartmentUpdate, db: Session = Depends(get_db),
    user: User = Depends(require_dept_admin),
):
    record = db.query(Department).filter(Department.id == department_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_can_manage(user, department_id)
    record.name = payload.name
    record.code = payload.code
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{department_id}")
def delete_department(department_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_superadmin)):
    record = db.query(Department).filter(Department.id == department_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Department not found")
    in_use = [
        f"{db.query(model).filter(model.department_id == department_id).count()} {label}"
        for label, model in OWNED_BY_DEPARTMENT
        if db.query(model).filter(model.department_id == department_id).count()
    ]
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=f"This department still has {', '.join(in_use)}. Delete or move them first "
                   "(Danger zone can clear a department's setup data).",
        )
    db.delete(record)
    db.commit()
    return {"message": "Department deleted"}
