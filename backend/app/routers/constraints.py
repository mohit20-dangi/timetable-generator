from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import SectionSubject, LabBatch, Prerequisite, TimeSlot, ConstraintProfile
from app.schemas import (
    SectionSubjectCreate, LabBatchCreate, LabBatchResponse,
    PrerequisiteCreate, TimeSlotCreate, TimeSlotResponse,
    ConstraintProfileCreate, ConstraintProfileResponse
)

router = APIRouter(prefix="/api/constraints", tags=["Constraints"])

# Section-Subject mappings
@router.post("/section-subjects")
def add_section_subject(ss: SectionSubjectCreate, db: Session = Depends(get_db)):
    db_ss = SectionSubject(**ss.model_dump())
    db.add(db_ss)
    db.commit()
    return {"message": "Section-Subject mapping added"}

@router.get("/section-subjects/{section_id}")
def get_section_subjects(section_id: str, db: Session = Depends(get_db)):
    return db.query(SectionSubject).filter(SectionSubject.section_id == section_id).all()

@router.delete("/section-subjects/{section_id}/{subject_id}")
def remove_section_subject(section_id: str, subject_id: str, db: Session = Depends(get_db)):
    ss = db.query(SectionSubject).filter(
        SectionSubject.section_id == section_id,
        SectionSubject.subject_id == subject_id
    ).first()
    if not ss:
        raise HTTPException(status_code=404, detail="Mapping not found")
    db.delete(ss)
    db.commit()
    return {"message": "Section-Subject mapping removed"}

# Lab Batches
@router.post("/lab-batches", response_model=LabBatchResponse)
def create_lab_batch(batch: LabBatchCreate, db: Session = Depends(get_db)):
    db_batch = LabBatch(**batch.model_dump())
    db.add(db_batch)
    db.commit()
    db.refresh(db_batch)
    return db_batch

@router.get("/lab-batches/{section_id}", response_model=List[LabBatchResponse])
def get_lab_batches(section_id: str, db: Session = Depends(get_db)):
    return db.query(LabBatch).filter(LabBatch.section_id == section_id).all()

@router.delete("/lab-batches/{batch_id}")
def delete_lab_batch(batch_id: str, db: Session = Depends(get_db)):
    batch = db.query(LabBatch).filter(LabBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Lab batch not found")
    db.delete(batch)
    db.commit()
    return {"message": "Lab batch deleted"}

# Prerequisites
@router.post("/prerequisites")
def add_prerequisite(prereq: PrerequisiteCreate, db: Session = Depends(get_db)):
    db_prereq = Prerequisite(**prereq.model_dump())
    db.add(db_prereq)
    db.commit()
    return {"message": "Prerequisite added"}

@router.get("/prerequisites")
def list_prerequisites(db: Session = Depends(get_db)):
    return db.query(Prerequisite).all()

@router.delete("/prerequisites/{subject_id}/{requires_subject_id}")
def remove_prerequisite(subject_id: str, requires_subject_id: str, db: Session = Depends(get_db)):
    prereq = db.query(Prerequisite).filter(
        Prerequisite.subject_id == subject_id,
        Prerequisite.requires_subject_id == requires_subject_id
    ).first()
    if not prereq:
        raise HTTPException(status_code=404, detail="Prerequisite not found")
    db.delete(prereq)
    db.commit()
    return {"message": "Prerequisite removed"}

# Time Slots
@router.post("/time-slots", response_model=TimeSlotResponse)
def create_time_slot(ts: TimeSlotCreate, db: Session = Depends(get_db)):
    db_ts = TimeSlot(**ts.model_dump())
    db.add(db_ts)
    db.commit()
    db.refresh(db_ts)
    return db_ts

@router.get("/time-slots", response_model=List[TimeSlotResponse])
def list_time_slots(db: Session = Depends(get_db)):
    return db.query(TimeSlot).all()

@router.delete("/time-slots/{slot_id}")
def delete_time_slot(slot_id: str, db: Session = Depends(get_db)):
    ts = db.query(TimeSlot).filter(TimeSlot.id == slot_id).first()
    if not ts:
        raise HTTPException(status_code=404, detail="Time slot not found")
    db.delete(ts)
    db.commit()
    return {"message": "Time slot deleted"}

# Constraint Profiles
@router.post("/profiles", response_model=ConstraintProfileResponse)
def create_constraint_profile(profile: ConstraintProfileCreate, db: Session = Depends(get_db)):
    db_profile = ConstraintProfile(**profile.model_dump())
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.get("/profiles", response_model=List[ConstraintProfileResponse])
def list_constraint_profiles(db: Session = Depends(get_db)):
    return db.query(ConstraintProfile).all()

@router.get("/profiles/{profile_id}", response_model=ConstraintProfileResponse)
def get_constraint_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(ConstraintProfile).filter(ConstraintProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Constraint profile not found")
    return profile

@router.delete("/profiles/{profile_id}")
def delete_constraint_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(ConstraintProfile).filter(ConstraintProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Constraint profile not found")
    db.delete(profile)
    db.commit()
    return {"message": "Constraint profile deleted"}