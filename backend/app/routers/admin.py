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

# Child-first delete order per scope. "timetables" is its own explicit scope
# precisely so that resetting configuration (sections/years/subjects/
# teachers/rooms/constraints) can never destroy timetable history - only
# resetting "timetables" (or "all") touches TimetableRun/GeneratedEntry/
# Reservation. TimeSlot (the bell schedule, not a constraint) is only
# touched by "all", never by "constraints".
SCOPE_TABLES = {
    "sections": [
        ("lab_batches", LabBatch),
        ("section_subjects", SectionSubject),
        ("sections", Section),
    ],
    "years": [
        ("lab_batches", LabBatch),
        ("section_subjects", SectionSubject),
        ("sections", Section),
        ("academic_years", AcademicYear),
    ],
    "subjects": [
        ("prerequisites", Prerequisite),
        ("teacher_subjects", TeacherSubject),
        ("section_subjects", SectionSubject),
        ("elective_groups", ElectiveGroup),
        ("subjects", Subject),
    ],
    "teachers": [
        ("teacher_subjects", TeacherSubject),
        ("teachers", Teacher),
    ],
    "rooms": [
        ("rooms", Room),
    ],
    "constraints": [
        ("constraint_rules", ConstraintRule),
        ("constraint_profiles", ConstraintProfile),
    ],
    "timetables": [
        ("generated_entries", GeneratedEntry),
        ("timetable_runs", TimetableRun),
        ("reservations", Reservation),
    ],
    "all": [
        ("lab_batches", LabBatch),
        ("section_subjects", SectionSubject),
        ("sections", Section),
        ("academic_years", AcademicYear),
        ("prerequisites", Prerequisite),
        ("teacher_subjects", TeacherSubject),
        ("elective_groups", ElectiveGroup),
        ("subjects", Subject),
        ("teachers", Teacher),
        ("rooms", Room),
        ("constraint_rules", ConstraintRule),
        ("constraint_profiles", ConstraintProfile),
        ("time_slots", TimeSlot),
    ],
}

VALID_SCOPES = set(SCOPE_TABLES)


@router.get("/reset/{scope}/preview")
def preview_reset(scope: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {sorted(VALID_SCOPES)}")

    deletes = {label: db.query(model).count() for label, model in SCOPE_TABLES[scope]}
    keeps = {} if scope == "timetables" else {"timetables": db.query(TimetableRun).count()}
    return {"deletes": deletes, "keeps": keeps}


@router.post("/reset/{scope}")
def reset_data(scope: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {sorted(VALID_SCOPES)}")

    for _label, model in SCOPE_TABLES[scope]:
        db.query(model).delete()
    db.commit()
    return {"message": f"Reset completed for scope '{scope}'."}
