from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db import get_db
from app.models import AcademicYear, Section, LabBatch, SectionSubject, TimetableRun, User
from app.schemas import AcademicYearCreate, AcademicYearResponse, SectionResponse
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import get_scoped_or_404, scoped, target_department

router = APIRouter(prefix="/api/years", tags=["Academic Years"])

@router.post("/", response_model=AcademicYearResponse)
def create_academic_year(year: AcademicYearCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if db.query(AcademicYear).filter(AcademicYear.id == year.id).first():
        raise HTTPException(status_code=409, detail="An academic year with this id already exists")
    data = year.model_dump()
    data["department_id"] = target_department(admin, data.get("department_id"))
    db_year = AcademicYear(**data)
    db.add(db_year)
    db.commit()
    db.refresh(db_year)
    return db_year

@router.get("/", response_model=List[AcademicYearResponse])
def list_academic_years(
    department_id: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return scoped(db.query(AcademicYear), AcademicYear, user, department_id).all()

@router.get("/{year_id}", response_model=AcademicYearResponse)
def get_academic_year(year_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_scoped_or_404(db, AcademicYear, year_id, user, "Academic year")

@router.put("/{year_id}", response_model=AcademicYearResponse)
def update_academic_year(year_id: str, year: AcademicYearCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, AcademicYear, year_id, admin, "Academic year")
    data = year.model_dump(exclude={"id"})
    data["department_id"] = target_department(admin, data.get("department_id"))
    for key, value in data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record

@router.post("/{year_id}/create-remaining-sections", response_model=List[SectionResponse])
def create_remaining_sections(year_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    """Phase 2.7: fills the gap between how many sections exist and the
    year's num_sections target, named A, B, C... continuing past whatever
    letters are already taken, at the year's default strength."""
    year = get_scoped_or_404(db, AcademicYear, year_id, admin, "Academic year")

    existing = db.query(Section).filter(Section.year_id == year_id).all()
    to_create = year.num_sections - len(existing)
    if to_create <= 0:
        raise HTTPException(status_code=400, detail=f"{year.name} already has all {year.num_sections} planned sections")

    used_ids = {s.id for s in existing}
    used_letters = {s.name.strip()[-1].upper() for s in existing if s.name.strip()}
    created: List[Section] = []
    letters = iter("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    for letter in letters:
        if len(created) >= to_create:
            break
        if letter in used_letters:
            continue
        section_id = f"{year_id}_{letter.lower()}"
        if section_id in used_ids:
            continue
        section = Section(id=section_id, year_id=year_id, name=f"Section {letter}", strength=year.default_section_strength)
        db.add(section)
        created.append(section)
        used_ids.add(section_id)
        used_letters.add(letter)
    if len(created) < to_create:
        raise HTTPException(status_code=409, detail="Ran out of section letters (A-Z) before reaching the target")

    db.commit()
    for section in created:
        db.refresh(section)
    return created


@router.delete("/{year_id}")
def delete_academic_year(
    year_id: str, dry_run: bool = False, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    year = get_scoped_or_404(db, AcademicYear, year_id, admin, "Academic year")

    section_ids = [s.id for s in db.query(Section).filter(Section.year_id == year_id).all()]
    batch_count = (
        db.query(LabBatch).filter(LabBatch.section_id.in_(section_ids)).count() if section_ids else 0
    )
    section_subject_count = (
        db.query(SectionSubject).filter(SectionSubject.section_id.in_(section_ids)).count() if section_ids else 0
    )
    counts = {"sections": len(section_ids), "lab_batches": batch_count, "section_subjects": section_subject_count}

    if dry_run:
        keeps = db.query(TimetableRun).filter(TimetableRun.department_id == year.department_id).count()
        return {"deletes": counts, "keeps": {"timetables": keeps}}

    if section_ids:
        db.query(LabBatch).filter(LabBatch.section_id.in_(section_ids)).delete(synchronize_session=False)
        db.query(SectionSubject).filter(SectionSubject.section_id.in_(section_ids)).delete(synchronize_session=False)
        # Keep student logins, just unassign them - see delete_section.
        db.query(User).filter(User.section_id.in_(section_ids)).update(
            {User.section_id: None}, synchronize_session=False
        )
        db.query(Section).filter(Section.id.in_(section_ids)).delete(synchronize_session=False)
    db.delete(year)
    db.commit()
    return {"message": "Academic year deleted", "deleted": counts}
