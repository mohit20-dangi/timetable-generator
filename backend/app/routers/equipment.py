from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Equipment, Subject, Room, User
from app.schemas import EquipmentCreate, EquipmentResponse
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import get_scoped_or_404, list_department, target_department

router = APIRouter(prefix="/api/equipment", tags=["Equipment"])

def _visible(query, model, user: User, department_id=None):
    """A department sees its own entries plus the shared ones (department
    NULL: the built-in subject types, and anything from before departments
    were separated). Only its own are editable - shared ones belong to the
    superadmin."""
    department_id = list_department(user, department_id)
    if department_id is None:
        return query
    return query.filter(or_(model.department_id == department_id, model.department_id.is_(None)))


@router.post("/", response_model=EquipmentResponse)
def create_equipment(payload: EquipmentCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if db.query(Equipment).filter(Equipment.id == payload.id).first():
        raise HTTPException(status_code=409, detail="This equipment id is already taken - pick another")
    data = payload.model_dump()
    data["department_id"] = target_department(admin, data.get("department_id"))
    record = Equipment(**data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[EquipmentResponse])
def list_equipment(department_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _visible(db.query(Equipment), Equipment, user, department_id).all()


@router.delete("/{equipment_id}")
def delete_equipment(equipment_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, Equipment, equipment_id, admin, "Equipment")
    subjects_using = [s.id for s in db.query(Subject).all() if equipment_id in (s.requires_equipment or [])]
    rooms_using = [r.id for r in db.query(Room).all() if equipment_id in (r.equipment or [])]
    if subjects_using or rooms_using:
        raise HTTPException(
            status_code=409,
            detail=f"In use by {len(subjects_using)} subject(s) and {len(rooms_using)} room(s) - remove it from those first.",
        )
    db.delete(record)
    db.commit()
    return {"message": "Equipment deleted"}
