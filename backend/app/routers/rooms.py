from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Room
from app.schemas import RoomCreate, RoomResponse

router = APIRouter(prefix="/api/rooms", tags=["Rooms"])

@router.post("/", response_model=RoomResponse)
def create_room(room: RoomCreate, db: Session = Depends(get_db)):
    db_room = Room(**room.model_dump())
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    return db_room

@router.get("/", response_model=List[RoomResponse])
def list_rooms(db: Session = Depends(get_db)):
    return db.query(Room).all()

@router.get("/{room_id}", response_model=RoomResponse)
def get_room(room_id: str, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room

@router.delete("/{room_id}")
def delete_room(room_id: str, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    db.delete(room)
    db.commit()
    return {"message": "Room deleted"}