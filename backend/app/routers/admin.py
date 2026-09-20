from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import (
    Section, LabBatch, AcademicYear, Subject, SectionSubject, TeacherSubject,
    Teacher, Room, ConstraintRule, ConstraintProfile, TimeSlot, TimetableRun,
    GeneratedEntry, Prerequisite, ElectiveGroup, Reservation, User,
)
from app.auth.dependencies import require_admin

router = APIRouter(prefix="/api/admin/data", tags=["Admin"])

VALID_SCOPES = {"sections", "years", "subjects", "teachers", "rooms", "constraints", "all"}


@router.post("/reset/{scope}")
def reset_data(scope: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {sorted(VALID_SCOPES)}")

    if scope in ("sections", "years", "all"):
        db.query(GeneratedEntry).delete()
        db.query(TimetableRun).delete()
        db.query(Reservation).delete()
        db.query(LabBatch).delete()
        db.query(SectionSubject).delete()
        db.query(Section).delete()
    if scope in ("years", "all"):
        db.query(AcademicYear).delete()
    if scope in ("subjects", "all"):
        db.query(Prerequisite).delete()
        db.query(TeacherSubject).delete()
        db.query(SectionSubject).delete()
        db.query(ElectiveGroup).delete()
        db.query(Subject).delete()
    if scope in ("teachers", "all"):
        db.query(TeacherSubject).delete()
        db.query(Teacher).delete()
    if scope in ("rooms", "all"):
        db.query(Room).delete()
    if scope in ("constraints", "all"):
        db.query(ConstraintRule).delete()
        db.query(ConstraintProfile).delete()
        db.query(TimeSlot).delete()
        db.query(GeneratedEntry).delete()
        db.query(TimetableRun).delete()
        db.query(Reservation).delete()

    db.commit()
    return {"message": f"Reset completed for scope '{scope}'."}
