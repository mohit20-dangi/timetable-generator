from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import ElectiveGroup, Subject, Room, TeacherSubject, User
from app.schemas import (
    ElectiveGroupCreate, ElectiveGroupResponse,
    ElectivePreflightResponse, ElectivePreflightIssue,
)
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/elective-groups", tags=["Elective Groups"])


@router.post("/", response_model=ElectiveGroupResponse)
def create_elective_group(payload: ElectiveGroupCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(ElectiveGroup).filter(ElectiveGroup.id == payload.id).first():
        raise HTTPException(status_code=409, detail="An elective group with this id already exists")
    record = ElectiveGroup(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[ElectiveGroupResponse])
def list_elective_groups(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(ElectiveGroup).all()


@router.put("/{group_id}", response_model=ElectiveGroupResponse)
def update_elective_group(group_id: str, payload: ElectiveGroupCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(ElectiveGroup).filter(ElectiveGroup.id == group_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Elective group not found")
    for key, value in payload.model_dump(exclude={"id", "department_id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{group_id}")
def delete_elective_group(group_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(ElectiveGroup).filter(ElectiveGroup.id == group_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Elective group not found")
    db.delete(record)
    db.commit()
    return {"message": "Elective group deleted"}


@router.get("/{group_id}/preflight", response_model=ElectivePreflightResponse)
def preflight_elective_group(group_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """Checks, in plain language, whether the offered options in this
    basket can actually be co-scheduled: are there enough rooms free in
    some common slot, and enough qualified teachers, for every offered
    option to run at once? See the elective-basket design note in
    ElectiveGroup's docstring - this is what turns "the solver went
    infeasible" into "you've offered 5 options but only have 3 rooms"
    before the admin ever clicks Generate.
    """
    group = db.query(ElectiveGroup).filter(ElectiveGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Elective group not found")

    offered = group.offered_subject_ids or []
    issues: List[ElectivePreflightIssue] = []

    if len(offered) < 2:
        return ElectivePreflightResponse(
            feasible=True, offered_count=len(offered),
            rooms_available_in_common_slot=0, qualified_teachers=0, issues=[],
        )

    subjects = db.query(Subject).filter(Subject.id.in_(offered)).all()
    room_types_needed = {s.requires_room_type for s in subjects if s.requires_room_type} or {"lecture"}
    rooms_available = (
        db.query(Room)
        .filter((Room.type.in_(room_types_needed)) | (Room.type == "lecture"))
        .count()
    )
    qualified_teacher_ids = set()
    for row in db.query(TeacherSubject).filter(TeacherSubject.subject_id.in_(offered)).all():
        qualified_teacher_ids.add(row.teacher_id)

    if group.must_be_parallel and rooms_available < len(offered):
        issues.append(ElectivePreflightIssue(
            severity="blocking",
            message=(
                f"You've offered {len(offered)} options, but only {rooms_available} suitable "
                "rooms exist. Either offer fewer options, add rooms, or split the basket into "
                "more than one timeslot."
            ),
        ))
    if len(qualified_teacher_ids) < len(offered):
        issues.append(ElectivePreflightIssue(
            severity="blocking",
            message=(
                f"You've offered {len(offered)} options, but only {len(qualified_teacher_ids)} "
                "teachers are qualified across all of them combined. Each option running in "
                "parallel needs its own teacher."
            ),
        ))

    return ElectivePreflightResponse(
        feasible=not any(i.severity == "blocking" for i in issues),
        offered_count=len(offered),
        rooms_available_in_common_slot=rooms_available,
        qualified_teachers=len(qualified_teacher_ids),
        issues=issues,
    )
