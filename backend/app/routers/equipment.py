from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Equipment, Subject, Room, User
from app.schemas import EquipmentCreate, EquipmentResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/equipment", tags=["Equipment"])


@router.post("/", response_model=EquipmentResponse)
def create_equipment(payload: EquipmentCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(Equipment).filter(Equipment.id == payload.id).first():
        raise HTTPException(status_code=409, detail="This equipment is already in the catalog")
    record = Equipment(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[EquipmentResponse])
def list_equipment(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Equipment).all()


@router.delete("/{equipment_id}")
def delete_equipment(equipment_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Equipment not found")
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
