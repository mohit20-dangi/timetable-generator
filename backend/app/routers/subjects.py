from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from typing import List
from app.db import get_database
from app.repositories import Repository
from app.models import SubjectCreate, SubjectResponse
from app.auth.dependencies import get_current_admin
from app.services.bulk_upload import parse_upload_file, bulk_create, csv_template, split_list, parse_bool, parse_int

router = APIRouter(prefix="/api/subjects", tags=["Subjects"])


def _repo(db: Database) -> Repository:
    return Repository(db, "subjects")


@router.post("/", response_model=SubjectResponse)
def create_subject(
    subject: SubjectCreate,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    try:
        return _repo(db).create(subject.model_dump())
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Subject with this ID already exists")


@router.get("/", response_model=List[SubjectResponse])
def list_subjects(
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    return _repo(db).list_all()


@router.get("/bulk/template", response_class=PlainTextResponse)
def download_subjects_template(_admin: dict = Depends(get_current_admin)):
    return csv_template(
        ["id", "name", "type", "weekly_hours", "needs_continuous_block", "block_size",
         "requires_room_type", "requires_equipment", "prerequisite_ids"],
        ["cs101", "Data Structures", "theory", "4", "false", "1", "", "", ""],
    )


@router.post("/bulk")
async def bulk_upload_subjects(
    file: UploadFile,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    rows = parse_upload_file(await file.read(), file.filename or "")

    def row_to_doc(row: dict) -> dict:
        payload = SubjectCreate(
            id=str(row["id"]).strip(),
            name=str(row["name"]).strip(),
            type=str(row["type"]).strip(),
            weekly_hours=parse_int(row.get("weekly_hours"), 0),
            needs_continuous_block=parse_bool(row.get("needs_continuous_block")),
            block_size=parse_int(row.get("block_size"), 1),
            requires_room_type=str(row["requires_room_type"]).strip() if row.get("requires_room_type") else None,
            requires_equipment=split_list(row.get("requires_equipment")),
            prerequisite_ids=split_list(row.get("prerequisite_ids")),
        )
        return payload.model_dump()

    return bulk_create(rows, row_to_doc, _repo(db))


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(
    subject_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    subject = _repo(db).get(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject


@router.delete("/{subject_id}")
def delete_subject(
    subject_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    if not _repo(db).delete(subject_id):
        raise HTTPException(status_code=404, detail="Subject not found")
    # Cascade cleanup: pull this subject out of anywhere it was referenced,
    # instead of leaving dangling ids (previously left orphaned link rows).
    db.teachers.update_many({}, {"$pull": {"subject_ids": subject_id}})
    db.sections.update_many({}, {"$pull": {"subjects": {"subject_id": subject_id}}})
    db.subjects.update_many({}, {"$pull": {"prerequisite_ids": subject_id}})
    return {"message": "Subject deleted"}


@router.post("/{subject_id}/prerequisites/{requires_subject_id}", response_model=SubjectResponse)
def add_prerequisite(
    subject_id: str,
    requires_subject_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    subject = _repo(db).get(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    if not _repo(db).exists(requires_subject_id):
        raise HTTPException(status_code=404, detail="Prerequisite subject not found")
    prereq_ids = list(dict.fromkeys(subject["prerequisite_ids"] + [requires_subject_id]))
    return _repo(db).update(subject_id, {"prerequisite_ids": prereq_ids})


@router.delete("/{subject_id}/prerequisites/{requires_subject_id}", response_model=SubjectResponse)
def remove_prerequisite(
    subject_id: str,
    requires_subject_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    subject = _repo(db).get(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    prereq_ids = [s for s in subject["prerequisite_ids"] if s != requires_subject_id]
    return _repo(db).update(subject_id, {"prerequisite_ids": prereq_ids})
