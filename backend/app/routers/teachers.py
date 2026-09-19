from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from typing import List
from pydantic import BaseModel
from app.db import get_database
from app.repositories import Repository
from app.models import TeacherCreate, TeacherResponse
from app.auth.dependencies import get_current_admin
from app.services.bulk_upload import parse_upload_file, bulk_create, csv_template, split_list, parse_bool, parse_int

router = APIRouter(prefix="/api/teachers", tags=["Teachers"])


class TeacherSubjectAdd(BaseModel):
    subject_id: str


def _repo(db: Database) -> Repository:
    return Repository(db, "teachers")


@router.post("/", response_model=TeacherResponse)
def create_teacher(
    teacher: TeacherCreate,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    try:
        return _repo(db).create(teacher.model_dump())
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Teacher with this ID already exists")


@router.get("/", response_model=List[TeacherResponse])
def list_teachers(
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    return _repo(db).list_all()


@router.get("/bulk/template", response_class=PlainTextResponse)
def download_teachers_template(_admin: dict = Depends(get_current_admin)):
    return csv_template(
        ["id", "name", "department", "subject_ids", "max_continuous_classes",
         "max_daily_classes", "is_guest_from_other_dept"],
        ["t1", "Prof. Sharma", "CSE", "cs101; cs102", "3", "5", "false"],
    )


@router.post("/bulk")
async def bulk_upload_teachers(
    file: UploadFile,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    rows = parse_upload_file(await file.read(), file.filename or "")

    def row_to_doc(row: dict) -> dict:
        payload = TeacherCreate(
            id=str(row["id"]).strip(),
            name=str(row["name"]).strip(),
            department=str(row["department"]).strip() if row.get("department") else None,
            subject_ids=split_list(row.get("subject_ids")),
            max_continuous_classes=parse_int(row.get("max_continuous_classes"), 3),
            max_daily_classes=parse_int(row.get("max_daily_classes"), 5),
            is_guest_from_other_dept=parse_bool(row.get("is_guest_from_other_dept")),
        )
        return payload.model_dump()

    return bulk_create(rows, row_to_doc, _repo(db))


@router.get("/{teacher_id}", response_model=TeacherResponse)
def get_teacher(
    teacher_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    teacher = _repo(db).get(teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return teacher


@router.post("/{teacher_id}/subjects", response_model=TeacherResponse)
def add_teacher_subject(
    teacher_id: str,
    ts: TeacherSubjectAdd,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    teacher = _repo(db).get(teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    subject_ids = list(dict.fromkeys(teacher["subject_ids"] + [ts.subject_id]))
    return _repo(db).update(teacher_id, {"subject_ids": subject_ids})


@router.delete("/{teacher_id}/subjects/{subject_id}", response_model=TeacherResponse)
def remove_teacher_subject(
    teacher_id: str,
    subject_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    teacher = _repo(db).get(teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    subject_ids = [s for s in teacher["subject_ids"] if s != subject_id]
    return _repo(db).update(teacher_id, {"subject_ids": subject_ids})


@router.delete("/{teacher_id}")
def delete_teacher(
    teacher_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    if not _repo(db).delete(teacher_id):
        raise HTTPException(status_code=404, detail="Teacher not found")
    return {"message": "Teacher deleted"}
