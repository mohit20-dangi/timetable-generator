from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Section
from app.schemas import SectionCreate, SectionResponse

router = APIRouter(prefix="/api/sections", tags=["Sections"])

@router.post("/", response_model=SectionResponse)
def create_section(section: SectionCreate, db: Session = Depends(get_db)):
    db_section = Section(**section.model_dump())
    db.add(db_section)
    db.commit()
    db.refresh(db_section)
    return db_section

@router.get("/", response_model=List[SectionResponse])
def list_sections(db: Session = Depends(get_db)):
    return db.query(Section).all()

@router.get("/{section_id}", response_model=SectionResponse)
def get_section(section_id: str, db: Session = Depends(get_db)):
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    return section

@router.get("/year/{year_id}", response_model=List[SectionResponse])
def get_sections_by_year(year_id: str, db: Session = Depends(get_db)):
    return db.query(Section).filter(Section.year_id == year_id).all()

@router.delete("/{section_id}")
def delete_section(section_id: str, db: Session = Depends(get_db)):
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    db.delete(section)
    db.commit()
    return {"message": "Section deleted"}