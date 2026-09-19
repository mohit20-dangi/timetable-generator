from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from typing import List
from app.db import get_database
from app.repositories import Repository
from app.models import RoomCreate, RoomResponse
from app.auth.dependencies import get_current_admin
from app.services.bulk_upload import parse_upload_file, bulk_create, csv_template, split_list, parse_int

router = APIRouter(prefix="/api/rooms", tags=["Rooms"])


def _repo(db: Database) -> Repository:
    return Repository(db, "rooms")


@router.post("/", response_model=RoomResponse)
def create_room(
    room: RoomCreate,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    try:
        return _repo(db).create(room.model_dump())
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Room with this ID already exists")


@router.get("/", response_model=List[RoomResponse])
def list_rooms(
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    return _repo(db).list_all()


@router.get("/bulk/template", response_class=PlainTextResponse)
def download_rooms_template(_admin: dict = Depends(get_current_admin)):
    return csv_template(
        ["id", "name", "type", "capacity", "equipment", "shared_with_departments"],
        ["lh101", "LH-101", "lecture", "60", "projector; computers", "CSE; IT"],
    )


@router.post("/bulk")
async def bulk_upload_rooms(
    file: UploadFile,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    rows = parse_upload_file(await file.read(), file.filename or "")

    def row_to_doc(row: dict) -> dict:
        payload = RoomCreate(
            id=str(row["id"]).strip(),
            name=str(row["name"]).strip(),
            type=str(row["type"]).strip(),
            capacity=parse_int(row.get("capacity"), 60),
            equipment=split_list(row.get("equipment")),
            shared_with_departments=split_list(row.get("shared_with_departments")),
        )
        return payload.model_dump()

    return bulk_create(rows, row_to_doc, _repo(db))


@router.get("/{room_id}", response_model=RoomResponse)
def get_room(
    room_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    room = _repo(db).get(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.delete("/{room_id}")
def delete_room(
    room_id: str,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    if not _repo(db).delete(room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    return {"message": "Room deleted"}
