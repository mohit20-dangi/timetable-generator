from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Section, AcademicYear, LabBatch, SectionSubject, TimetableRun, User
from app.schemas import SectionCreate, SectionResponse
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/sections", tags=["Sections"])


@router.post("/", response_model=SectionResponse)
def create_section(section: SectionCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    year = db.query(AcademicYear).filter(AcademicYear.id == section.year_id).first()
    if not year:
        raise HTTPException(status_code=400, detail="year_id does not exist")
    if db.query(Section).filter(Section.id == section.id).first():
        raise HTTPException(status_code=409, detail="A section with this id already exists")
    # Phase 2.7: num_sections is a target, not just a display number - once
    # reached, adding another section needs a deliberate increase to the
    # target first, not a silent extra section nobody planned resourcing for.
    existing_count = db.query(Section).filter(Section.year_id == section.year_id).count()
    if existing_count >= year.num_sections:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{year.name} already has {existing_count} of {year.num_sections} planned sections. "
                "Increase the year's section target before adding another."
            ),
        )
    db_section = Section(**section.model_dump())
    db.add(db_section)
    db.commit()
    db.refresh(db_section)
    return db_section


@router.get("/", response_model=List[SectionResponse])
def list_sections(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Section).all()


@router.get("/year/{year_id}", response_model=List[SectionResponse])
def get_sections_by_year(year_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Section).filter(Section.year_id == year_id).all()


@router.get("/{section_id}", response_model=SectionResponse)
def get_section(section_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


@router.put("/{section_id}", response_model=SectionResponse)
def update_section(section_id: str, section: SectionCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(Section).filter(Section.id == section_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Section not found")
    for key, value in section.model_dump(exclude={"id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{section_id}")
def delete_section(
    section_id: str, dry_run: bool = False, db: Session = Depends(get_db), _admin: User = Depends(require_admin),
):
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")

    counts = {
        "lab_batches": db.query(LabBatch).filter(LabBatch.section_id == section_id).count(),
        "section_subjects": db.query(SectionSubject).filter(SectionSubject.section_id == section_id).count(),
    }

    if dry_run:
        return {"deletes": counts, "keeps": {"timetables": db.query(TimetableRun).count()}}

    db.query(LabBatch).filter(LabBatch.section_id == section_id).delete()
    db.query(SectionSubject).filter(SectionSubject.section_id == section_id).delete()
    db.delete(section)
    db.commit()
    return {"message": "Section deleted", "deleted": counts}
