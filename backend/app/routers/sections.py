from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from typing import List
from app.db import get_database
from app.repositories import Repository
from app.models import SectionCreate, SectionResponse, SectionSubjectAdd, LabBatchCreate
from app.auth.dependencies import get_current_admin
from app.services.bulk_upload import parse_upload_file, bulk_create, csv_template, parse_int

router = APIRouter(prefix="/api/sections", tags=["Sections"])


def _repo(db: Database) -> Repository:
    return Repository(db, "sections")


@router.post("/", response_model=SectionResponse)
def create_section(
    section: SectionCreate,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    try:
        data = section.model_dump()
        data["subjects"] = []
        data["lab_batches"] = []
        return _repo(db).create(data)
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Section with this ID already exists")


@router.get("/", response_model=List[SectionResponse])
def list_sections(
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    return _repo(db).list_all()


@router.get("/bulk/template", response_class=PlainTextResponse)
def download_sections_template(_admin: dict = Depends(get_current_admin)):
    return csv_template(
        ["id", "year_id", "name", "strength"],
        ["y1_a", "y1", "Section A", "60"],
    )


@router.post("/bulk")
async def bulk_upload_sections(
    file: UploadFile,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    rows = parse_upload_file(await file.read(), file.filename or "")

    def row_to_doc(row: dict) -> dict:
        payload = SectionCreate(
            id=str(row["id"]).strip(),
            year_id=str(row["year_id"]).strip(),
            name=str(row["name"]).strip(),
            strength=parse_int(row.get("strength"), 60),
        )
        doc = payload.model_dump()
        doc["subjects"] = []
        doc["lab_batches"] = []
        return doc

    return bulk_create(rows, row_to_doc, _repo(db))


@router.get("/{section_id}", response_model=SectionResponse)
def get_section(
    section_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    section = _repo(db).get(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


@router.get("/year/{year_id}", response_model=List[SectionResponse])
def get_sections_by_year(
    year_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    return _repo(db).list_all({"year_id": year_id})


@router.delete("/{section_id}")
def delete_section(
    section_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    if not _repo(db).delete(section_id):
        raise HTTPException(status_code=404, detail="Section not found")
    return {"message": "Section deleted"}


# --- Section <-> Subject links (embedded on the section document) ---

@router.post("/{section_id}/subjects", response_model=SectionResponse)
def add_section_subject(
    section_id: str,
    link: SectionSubjectAdd,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    section = _repo(db).get(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    subjects = [s for s in section["subjects"] if s["subject_id"] != link.subject_id]
    subjects.append(link.model_dump())
    return _repo(db).update(section_id, {"subjects": subjects})


@router.delete("/{section_id}/subjects/{subject_id}", response_model=SectionResponse)
def remove_section_subject(
    section_id: str,
    subject_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    section = _repo(db).get(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    subjects = [s for s in section["subjects"] if s["subject_id"] != subject_id]
    return _repo(db).update(section_id, {"subjects": subjects})


# --- Lab batches (embedded on the section document) ---

@router.post("/{section_id}/lab-batches", response_model=SectionResponse)
def create_lab_batch(
    section_id: str,
    batch: LabBatchCreate,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    section = _repo(db).get(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    if any(b["id"] == batch.id for b in section["lab_batches"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lab batch with this ID already exists")
    lab_batches = section["lab_batches"] + [batch.model_dump()]
    return _repo(db).update(section_id, {"lab_batches": lab_batches})


@router.delete("/{section_id}/lab-batches/{batch_id}", response_model=SectionResponse)
def delete_lab_batch(
    section_id: str,
    batch_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    section = _repo(db).get(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    lab_batches = [b for b in section["lab_batches"] if b["id"] != batch_id]
    return _repo(db).update(section_id, {"lab_batches": lab_batches})
