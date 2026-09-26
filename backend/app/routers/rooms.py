from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Room, Reservation, Subject, GeneratedEntry, TimetableRun, User
from app.schemas import RoomCreate, RoomResponse
from app.schemas.room import VALID_ROOM_TYPES
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/rooms", tags=["Rooms"])


@router.post("/", response_model=RoomResponse)
def create_room(room: RoomCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if room.type not in VALID_ROOM_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {sorted(VALID_ROOM_TYPES)}")
    if db.query(Room).filter(Room.id == room.id).first():
        raise HTTPException(status_code=409, detail="A room with this id already exists")
    db_room = Room(**room.model_dump())
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    return db_room


@router.get("/", response_model=List[RoomResponse])
def list_rooms(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Room).all()


@router.get("/{room_id}", response_model=RoomResponse)
def get_room(room_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.put("/{room_id}", response_model=RoomResponse)
def update_room(room_id: str, room: RoomCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(Room).filter(Room.id == room_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Room not found")
    for key, value in room.model_dump(exclude={"id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{room_id}")
def delete_room(
    room_id: str, dry_run: bool = False, db: Session = Depends(get_db), _admin: User = Depends(require_admin),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    published = (
        db.query(GeneratedEntry)
        .join(TimetableRun, TimetableRun.id == GeneratedEntry.timetable_run_id)
        .filter(GeneratedEntry.room_id == room_id, TimetableRun.is_published.is_(True))
        .first()
    )
    blocked_reason = (
        "This room is used in a published timetable and cannot be deleted while it is live."
        if published else None
    )

    reservation_count = db.query(Reservation).filter(
        Reservation.resource_type == "room", Reservation.resource_id == room_id
    ).count()

    other_rooms_of_type = db.query(Room).filter(Room.type == room.type, Room.id != room_id).count()
    affected_subjects = (
        [s.id for s in db.query(Subject).filter(Subject.requires_room_type == room.type).all()]
        if other_rooms_of_type == 0 else []
    )
    counts = {"reservations": reservation_count}
    warning = (
        f"{len(affected_subjects)} subject(s) would be left with no eligible room."
        if affected_subjects else None
    )

    if dry_run:
        return {
            "deletes": counts, "warning": warning, "blocked_reason": blocked_reason,
            "affected_subjects": affected_subjects,
        }
    if blocked_reason:
        raise HTTPException(status_code=409, detail=blocked_reason)

    db.query(Reservation).filter(Reservation.resource_type == "room", Reservation.resource_id == room_id).delete()
    db.delete(room)
    db.commit()
    return {"message": "Room deleted", "deleted": counts, "warning": warning, "affected_subjects": affected_subjects}
