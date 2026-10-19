from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import (
    Section, LabBatch, AcademicYear, Subject, SectionSubject, TeacherSubject,
    Teacher, Room, ConstraintRule, ConstraintProfile, TimeSlot, TimetableRun,
    GeneratedEntry, Prerequisite, ElectiveGroup, Reservation, FirstYearTile, User,
)
from app.auth.dependencies import require_dept_admin
from app.auth.scope import department_criterion, list_department

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
        ("first_year_tiles", FirstYearTile),
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


def _rows(db: Session, model, department_id: Optional[str]):
    """Rows of `model` a reset touches: one department's, or every
    department's when department_id is None (superadmin only - see
    list_department)."""
    query = db.query(model)
    return query if department_id is None else query.filter(department_criterion(model, department_id))


def _check_scope(scope: str) -> None:
    if scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {sorted(VALID_SCOPES)}")


@router.get("/reset/{scope}/preview")
def preview_reset(
    scope: str, department_id: Optional[str] = None,
    db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    _check_scope(scope)
    department_id = list_department(admin, department_id)
    deletes = {label: _rows(db, model, department_id).count() for label, model in SCOPE_TABLES[scope]}
    keeps = {} if scope == "timetables" else {"timetables": _rows(db, TimetableRun, department_id).count()}
    return {"deletes": deletes, "keeps": keeps}


@router.post("/reset/{scope}")
def reset_data(
    scope: str, department_id: Optional[str] = None,
    db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    """A department admin resets their own department only; the superadmin
    resets one department (department_id) or, without it, all of them."""
    _check_scope(scope)
    department_id = list_department(admin, department_id)
    models = [model for _label, model in SCOPE_TABLES[scope]]
    # Logins point at their section/teacher; keep the accounts but unlink
    # them (a teacher login with no teacher is also disabled), or the
    # delete fails on a foreign key.
    if Section in models:
        section_ids = [s.id for s in _rows(db, Section, department_id).all()]
        db.query(User).filter(User.section_id.in_(section_ids)).update(
            {User.section_id: None}, synchronize_session=False
        )
    if Teacher in models:
        teacher_ids = [t.id for t in _rows(db, Teacher, department_id).all()]
        db.query(User).filter(User.teacher_id.in_(teacher_ids)).update(
            {User.teacher_id: None, User.is_active: False}, synchronize_session=False
        )
    for model in models:
        _rows(db, model, department_id).delete(synchronize_session=False)
    db.commit()
    return {"message": f"Reset completed for scope '{scope}'."}
