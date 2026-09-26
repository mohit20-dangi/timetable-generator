from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import AcademicYear, Section, LabBatch, SectionSubject, TimetableRun, User
from app.schemas import AcademicYearCreate, AcademicYearResponse, SectionResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/years", tags=["Academic Years"])

@router.post("/", response_model=AcademicYearResponse)
def create_academic_year(year: AcademicYearCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(AcademicYear).filter(AcademicYear.id == year.id).first():
        raise HTTPException(status_code=409, detail="An academic year with this id already exists")
    db_year = AcademicYear(**year.model_dump())
    db.add(db_year)
    db.commit()
    db.refresh(db_year)
    return db_year

@router.get("/", response_model=List[AcademicYearResponse])
def list_academic_years(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(AcademicYear).all()

@router.get("/{year_id}", response_model=AcademicYearResponse)
def get_academic_year(year_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    year = db.query(AcademicYear).filter(AcademicYear.id == year_id).first()
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")
    return year

@router.put("/{year_id}", response_model=AcademicYearResponse)
def update_academic_year(year_id: str, year: AcademicYearCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(AcademicYear).filter(AcademicYear.id == year_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Academic year not found")
    for key, value in year.model_dump(exclude={"id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record

@router.post("/{year_id}/create-remaining-sections", response_model=List[SectionResponse])
def create_remaining_sections(year_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Phase 2.7: fills the gap between how many sections exist and the
    year's num_sections target, named A, B, C... continuing past whatever
    letters are already taken, at the year's default strength."""
    year = db.query(AcademicYear).filter(AcademicYear.id == year_id).first()
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")

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
    year_id: str, dry_run: bool = False, db: Session = Depends(get_db), _admin: User = Depends(require_admin),
):
    year = db.query(AcademicYear).filter(AcademicYear.id == year_id).first()
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")

    section_ids = [s.id for s in db.query(Section).filter(Section.year_id == year_id).all()]
    batch_count = (
        db.query(LabBatch).filter(LabBatch.section_id.in_(section_ids)).count() if section_ids else 0
    )
    section_subject_count = (
        db.query(SectionSubject).filter(SectionSubject.section_id.in_(section_ids)).count() if section_ids else 0
    )
    counts = {"sections": len(section_ids), "lab_batches": batch_count, "section_subjects": section_subject_count}

    if dry_run:
        return {"deletes": counts, "keeps": {"timetables": db.query(TimetableRun).count()}}

    if section_ids:
        db.query(LabBatch).filter(LabBatch.section_id.in_(section_ids)).delete(synchronize_session=False)
        db.query(SectionSubject).filter(SectionSubject.section_id.in_(section_ids)).delete(synchronize_session=False)
        db.query(Section).filter(Section.id.in_(section_ids)).delete(synchronize_session=False)
    db.delete(year)
    db.commit()
    return {"message": "Academic year deleted", "deleted": counts}
