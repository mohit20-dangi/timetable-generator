from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from typing import List
from app.db import get_database
from app.repositories import Repository
from app.models import AcademicYearCreate, AcademicYearResponse
from app.auth.dependencies import get_current_admin
from app.services.bulk_upload import parse_upload_file, bulk_create, csv_template

router = APIRouter(prefix="/api/years", tags=["Academic Years"])


def _repo(db: Database) -> Repository:
    return Repository(db, "academic_years")


@router.post("/", response_model=AcademicYearResponse)
def create_academic_year(
    year: AcademicYearCreate,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    try:
        return _repo(db).create(year.model_dump())
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Academic year with this ID already exists")


@router.get("/", response_model=List[AcademicYearResponse])
def list_academic_years(
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    return _repo(db).list_all()


@router.get("/bulk/template", response_class=PlainTextResponse)
def download_years_template(_admin: dict = Depends(get_current_admin)):
    return csv_template(
        ["id", "name", "lunch_start", "lunch_end"],
        ["y1", "1st Year", "13:00", "14:00"],
    )


@router.post("/bulk")
async def bulk_upload_years(
    file: UploadFile,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    rows = parse_upload_file(await file.read(), file.filename or "")

    def row_to_doc(row: dict) -> dict:
        payload = AcademicYearCreate(
            id=str(row["id"]).strip(),
            name=str(row["name"]).strip(),
            lunch_start=str(row["lunch_start"]).strip() if row.get("lunch_start") else None,
            lunch_end=str(row["lunch_end"]).strip() if row.get("lunch_end") else None,
        )
        return payload.model_dump()

    return bulk_create(rows, row_to_doc, _repo(db))


@router.get("/{year_id}", response_model=AcademicYearResponse)
def get_academic_year(
    year_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    year = _repo(db).get(year_id)
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")
    return year


@router.delete("/{year_id}")
def delete_academic_year(
    year_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    if not _repo(db).delete(year_id):
        raise HTTPException(status_code=404, detail="Academic year not found")
    # Cascade: sections belonging to this year are now orphaned data, not just
    # dangling foreign keys (Mongo has no FK enforcement), so clean them up too.
    db.sections.delete_many({"year_id": year_id})
    return {"message": "Academic year deleted"}
