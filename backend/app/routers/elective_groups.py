from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import ElectiveGroup, Subject, Room, TeacherSubject, TimeSlot, User
from app.schemas import (
    ElectiveGroupCreate, ElectiveGroupResponse,
    ElectivePreflightResponse, ElectivePreflightIssue,
)
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import assert_can_manage, get_scoped_or_404, scoped, target_department
from app.services.department_calendar import department_time_slots


def _room_available_at(room: Room, day: str, start, end) -> bool:
    """`room.availability` windows mean "the room may only be used during
    these windows" (see Room model / Phase 1.2) - an empty list means no
    restriction at all."""
    windows = room.availability or []
    if not windows:
        return True
    for window in windows:
        if window.get("day") != day:
            continue
        if str(window.get("start", "")) <= str(start) and str(end) <= str(window.get("end", "")):
            return True
    return False


def _max_rooms_free_together(rooms: List[Room], slots: List[TimeSlot]) -> int:
    """The real question isn't "how many suitable rooms exist" but "how
    many are free together at the SAME hour" - a basket needs one common
    slot with enough rooms, not a headcount scattered across the week."""
    if not slots:
        # No bell schedule configured yet - fall back to a simple count so
        # the check still gives a useful (if less precise) answer.
        return len(rooms)
    best = 0
    for slot in slots:
        free = sum(1 for room in rooms if _room_available_at(room, slot.day, slot.start_time, slot.end_time))
        best = max(best, free)
    return best

router = APIRouter(prefix="/api/elective-groups", tags=["Elective Groups"])


def _assert_offered_in_department(db: Session, admin: User, subject_ids) -> None:
    for subject_id in subject_ids or []:
        subject = db.get(Subject, subject_id)
        if subject is None:
            raise HTTPException(status_code=400, detail=f"Unknown subject '{subject_id}'")
        assert_can_manage(admin, subject.department_id)


@router.post("/", response_model=ElectiveGroupResponse)
def create_elective_group(payload: ElectiveGroupCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if db.query(ElectiveGroup).filter(ElectiveGroup.id == payload.id).first():
        raise HTTPException(status_code=409, detail="An elective group with this id already exists")
    data = payload.model_dump()
    data["department_id"] = target_department(admin, data.get("department_id"))
    _assert_offered_in_department(db, admin, data.get("offered_subject_ids"))
    record = ElectiveGroup(**data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[ElectiveGroupResponse])
def list_elective_groups(department_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return scoped(db.query(ElectiveGroup), ElectiveGroup, user, department_id).all()


@router.put("/{group_id}", response_model=ElectiveGroupResponse)
def update_elective_group(group_id: str, payload: ElectiveGroupCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, ElectiveGroup, group_id, admin, "Elective group")
    _assert_offered_in_department(db, admin, payload.offered_subject_ids)
    for key, value in payload.model_dump(exclude={"id", "department_id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{group_id}")
def delete_elective_group(group_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, ElectiveGroup, group_id, admin, "Elective group")
    db.delete(record)
    db.commit()
    return {"message": "Elective group deleted"}


@router.get("/{group_id}/preflight", response_model=ElectivePreflightResponse)
def preflight_elective_group(group_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Checks, in plain language, whether the offered options in this
    basket can actually be co-scheduled: are there enough rooms free in
    some common slot, and enough qualified teachers, for every offered
    option to run at once? See the elective-basket design note in
    ElectiveGroup's docstring - this is what turns "the solver went
    infeasible" into "you've offered 5 options but only have 3 rooms"
    before the admin ever clicks Generate.
    """
    group = get_scoped_or_404(db, ElectiveGroup, group_id, user, "Elective group")

    offered = group.offered_subject_ids or []
    issues: List[ElectivePreflightIssue] = []

    if len(offered) < 2:
        return ElectivePreflightResponse(
            feasible=True, offered_count=len(offered),
            rooms_available_in_common_slot=0, qualified_teachers=0, issues=[],
        )

    subjects = db.query(Subject).filter(Subject.id.in_(offered)).all()
    room_types_needed = {s.requires_room_type for s in subjects if s.requires_room_type} or {"lecture"}
    # A room is usable by this basket if it's owned by the offering
    # department, is a shared institution-wide room (department_id is
    # NULL), or has been explicitly lent to this department.
    candidate_rooms = (
        db.query(Room)
        .filter((Room.type.in_(room_types_needed)) | (Room.type == "lecture"))
        .all()
    )
    usable_rooms = [
        room for room in candidate_rooms
        if room.department_id is None
        or room.department_id == group.department_id
        or group.department_id in (room.shared_with_departments or [])
    ]
    bell_schedule = department_time_slots(db, group.department_id)
    rooms_available = _max_rooms_free_together(usable_rooms, bell_schedule)
    qualified_teacher_ids = set()
    for row in db.query(TeacherSubject).filter(TeacherSubject.subject_id.in_(offered)).all():
        qualified_teacher_ids.add(row.teacher_id)

    if group.must_be_parallel and rooms_available < len(offered):
        issues.append(ElectivePreflightIssue(
            severity="blocking",
            message=f"There aren't enough rooms to run these together: {len(offered)} options, {rooms_available} suitable rooms free at the same hour.",
            kind="rooms",
        ))
    if len(qualified_teacher_ids) < len(offered):
        issues.append(ElectivePreflightIssue(
            severity="blocking",
            message=f"There aren't enough qualified teachers to run these together: {len(offered)} options, {len(qualified_teacher_ids)} teachers qualified across them.",
            kind="teachers",
        ))

    return ElectivePreflightResponse(
        feasible=not any(i.severity == "blocking" for i in issues),
        offered_count=len(offered),
        rooms_available_in_common_slot=rooms_available,
        qualified_teachers=len(qualified_teacher_ids),
        issues=issues,
    )
