from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from typing import List
from app.db import get_database
from app.repositories import Repository
from app.models import (
    TimeSlotCreate, TimeSlotResponse,
    ConstraintProfileCreate, ConstraintProfileResponse,
)
from app.auth.dependencies import get_current_admin

router = APIRouter(prefix="/api/constraints", tags=["Constraints"])


# --- Time Slots ---

@router.post("/time-slots", response_model=TimeSlotResponse)
def create_time_slot(
    ts: TimeSlotCreate,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    try:
        return Repository(db, "time_slots").create(ts.model_dump())
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Time slot with this ID already exists")


@router.get("/time-slots", response_model=List[TimeSlotResponse])
def list_time_slots(
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    return Repository(db, "time_slots").list_all()


@router.delete("/time-slots/{slot_id}")
def delete_time_slot(
    slot_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    if not Repository(db, "time_slots").delete(slot_id):
        raise HTTPException(status_code=404, detail="Time slot not found")
    return {"message": "Time slot deleted"}


# --- Constraint Profiles ---

@router.post("/profiles", response_model=ConstraintProfileResponse)
def create_constraint_profile(
    profile: ConstraintProfileCreate,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    try:
        return Repository(db, "constraint_profiles").create(profile.model_dump())
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Constraint profile with this ID already exists")


@router.get("/profiles", response_model=List[ConstraintProfileResponse])
def list_constraint_profiles(
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    return Repository(db, "constraint_profiles").list_all()


@router.get("/profiles/{profile_id}", response_model=ConstraintProfileResponse)
def get_constraint_profile(
    profile_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    profile = Repository(db, "constraint_profiles").get(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Constraint profile not found")
    return profile


@router.delete("/profiles/{profile_id}")
def delete_constraint_profile(
    profile_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    if not Repository(db, "constraint_profiles").delete(profile_id):
        raise HTTPException(status_code=404, detail="Constraint profile not found")
    return {"message": "Constraint profile deleted"}
