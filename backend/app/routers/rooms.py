from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Room, Reservation, Subject, GeneratedEntry, TimetableRun, User
from app.schemas import RoomCreate, RoomResponse
from app.schemas.room import VALID_ROOM_TYPES
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import get_scoped_or_404, is_superadmin, list_department, target_department

router = APIRouter(prefix="/api/rooms", tags=["Rooms"])


def _visible_rooms(db: Session, department_id):
    """A department sees its own rooms plus rooms another department (or
    the superadmin, for department NULL) has shared with it - the same set
    the solver may book. Only its own rooms are editable."""
    query = db.query(Room)
    if department_id is None:
        return query.all()
    own_or_central = query.filter(or_(Room.department_id == department_id, Room.department_id.is_(None))).all()
    shared = [
        r for r in query.filter(Room.department_id != department_id).all()
        if department_id in (r.shared_with_departments or [])
    ]
    return own_or_central + shared


@router.post("/", response_model=RoomResponse)
def create_room(room: RoomCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if room.type not in VALID_ROOM_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {sorted(VALID_ROOM_TYPES)}")
    if db.query(Room).filter(Room.id == room.id).first():
        raise HTTPException(status_code=409, detail="A room with this id already exists")
    data = room.model_dump()
    # A blank department means "central, every department" only when the
    # superadmin says so; a department admin's room is always their own.
    if not (is_superadmin(admin) and not data.get("department_id")):
        data["department_id"] = target_department(admin, data.get("department_id"))
    db_room = Room(**data)
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    return db_room


@router.get("/", response_model=List[RoomResponse])
def list_rooms(department_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _visible_rooms(db, list_department(user, department_id))


@router.get("/{room_id}", response_model=RoomResponse)
def get_room(room_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    room = next((r for r in _visible_rooms(db, list_department(user)) if r.id == room_id), None)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.put("/{room_id}", response_model=RoomResponse)
def update_room(room_id: str, room: RoomCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, Room, room_id, admin, "Room")
    data = room.model_dump(exclude={"id"})
    if not (is_superadmin(admin) and not data.get("department_id")):
        data["department_id"] = target_department(admin, data.get("department_id"))
    for key, value in data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{room_id}")
def delete_room(
    room_id: str, dry_run: bool = False, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    room = get_scoped_or_404(db, Room, room_id, admin, "Room")

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
