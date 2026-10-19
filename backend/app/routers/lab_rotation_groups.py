"""CRUD + preflight for lab rotations (see app/models/lab_rotation_group.py).

The preflight is the point of this router as much as the CRUD is: a
rotation is set up precisely BECAUSE the straightforward arrangement ran
out of lab teachers, so telling the admin "that rotation doesn't fit
either, and here's which part" before they click Generate is worth more
than another INFEASIBLE afterwards.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    LabRotationGroup, LabBatch, Room, Section, SectionSubject, Subject,
    TeacherSubject, User,
)
from app.schemas import (
    LabRotationGroupCreate, LabRotationGroupResponse,
    LabRotationPreflightResponse, LabRotationPreflightIssue,
)
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import assert_can_manage, get_scoped_or_404, scoped, target_department
from app.services.department_calendar import department_time_slots

router = APIRouter(prefix="/api/lab-rotations", tags=["Lab Rotations"])


def _sessions_per_week(subject: Subject) -> int:
    """How many separate meetings of this subject a batch has in a week -
    one "round" of the rotation each. Mirrors data_loader's derivation so
    the preflight counts the same rounds the solver will."""
    periods = max(1, subject.periods_per_session or 1)
    if subject.sessions_per_week is not None:
        return max(0, subject.sessions_per_week)
    return max(0, (subject.weekly_hours or 0) // periods)


def _validate_payload(db: Session, admin: User, payload: LabRotationGroupCreate, department_id: str) -> None:
    section = db.get(Section, payload.section_id)
    if section is None:
        raise HTTPException(status_code=400, detail=f"Unknown section '{payload.section_id}'")
    mapped = {
        row.subject_id for row in
        db.query(SectionSubject).filter(SectionSubject.section_id == payload.section_id).all()
    }
    for subject_id in payload.subject_ids:
        subject = db.get(Subject, subject_id)
        if subject is None:
            raise HTTPException(status_code=400, detail=f"Unknown subject '{subject_id}'")
        assert_can_manage(admin, subject.department_id or department_id)
        if subject.type != "lab":
            raise HTTPException(
                status_code=400,
                detail=f"'{subject.name}' is not a lab subject - only labs, which split a section "
                       "into batches, can rotate.",
            )
        if subject_id not in mapped:
            raise HTTPException(
                status_code=400,
                detail=f"Section '{payload.section_id}' does not take '{subject.name}' - add it to "
                       "the section's subjects first.",
            )

    lengths = {max(1, db.get(Subject, sid).periods_per_session or 1) for sid in payload.subject_ids}
    if len(lengths) > 1:
        raise HTTPException(
            status_code=400,
            detail="Every lab in a rotation must have the same periods per session - a round is one "
                   f"shared block of time, and these are {sorted(lengths)} periods long.",
        )

    # A lab can only be in one rotation per section: two rotations both
    # claiming it would each try to decide when it runs.
    others = (
        db.query(LabRotationGroup)
        .filter(
            LabRotationGroup.section_id == payload.section_id,
            LabRotationGroup.id != payload.id,
            LabRotationGroup.is_active.is_(True),
        )
        .all()
    )
    taken = {sid: g.name for g in others for sid in (g.subject_ids or [])}
    overlap = sorted(set(payload.subject_ids) & set(taken))
    if overlap:
        raise HTTPException(
            status_code=409,
            detail=f"Subject(s) {', '.join(overlap)} are already in the rotation "
                   f"'{taken[overlap[0]]}' for this section.",
        )


@router.post("/", response_model=LabRotationGroupResponse)
def create_lab_rotation(
    payload: LabRotationGroupCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    if db.query(LabRotationGroup).filter(LabRotationGroup.id == payload.id).first():
        raise HTTPException(status_code=409, detail="A lab rotation with this id already exists")
    department_id = target_department(admin, payload.department_id)
    _validate_payload(db, admin, payload, department_id)
    data = payload.model_dump()
    data["department_id"] = department_id
    record = LabRotationGroup(**data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[LabRotationGroupResponse])
def list_lab_rotations(
    department_id: str | None = None,
    section_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = scoped(db.query(LabRotationGroup), LabRotationGroup, user, department_id)
    if section_id:
        query = query.filter(LabRotationGroup.section_id == section_id)
    return query.all()


@router.put("/{rotation_id}", response_model=LabRotationGroupResponse)
def update_lab_rotation(
    rotation_id: str,
    payload: LabRotationGroupCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    record = get_scoped_or_404(db, LabRotationGroup, rotation_id, admin, "Lab rotation")
    _validate_payload(db, admin, payload, record.department_id)
    for key, value in payload.model_dump(exclude={"id", "department_id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{rotation_id}")
def delete_lab_rotation(
    rotation_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    record = get_scoped_or_404(db, LabRotationGroup, rotation_id, admin, "Lab rotation")
    db.delete(record)
    db.commit()
    return {"message": "Lab rotation deleted"}


@router.get("/{rotation_id}/preflight", response_model=LabRotationPreflightResponse)
def preflight_lab_rotation(
    rotation_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    rotation = get_scoped_or_404(db, LabRotationGroup, rotation_id, user, "Lab rotation")
    issues: List[LabRotationPreflightIssue] = []

    batches = db.query(LabBatch).filter(LabBatch.section_id == rotation.section_id).all()
    subjects = [db.get(Subject, sid) for sid in (rotation.subject_ids or [])]
    subjects = [s for s in subjects if s is not None]
    rounds = sum(_sessions_per_week(s) for s in subjects)

    if len(batches) < 2:
        issues.append(LabRotationPreflightIssue(
            severity="blocking", kind="batches",
            message=f"Section {rotation.section_id} has {len(batches)} lab batch(es). A rotation "
                    "moves batches between labs, so it needs at least two.",
        ))

    # The core arithmetic: one round holds one batch per lab, so there must
    # be at least as many lab sessions a week as there are batches.
    if batches and rounds < len(batches):
        issues.append(LabRotationPreflightIssue(
            severity="blocking", kind="subjects",
            message=f"This rotation has {rounds} lab session(s) a week but {len(batches)} batches, "
                    "so at least two batches would have to be in the same lab at once. Add another "
                    "lab to the rotation, or give its labs more sessions per week.",
        ))

    # Each lab runs once at a time, so one qualified teacher per lab is
    # enough - which is the whole reason to rotate. Only complain when even
    # that minimum isn't met.
    for subject in subjects:
        qualified = {
            row.teacher_id for row in
            db.query(TeacherSubject).filter(TeacherSubject.subject_id == subject.id).all()
        }
        needed = max(1, subject.teachers_required or 1)
        if len(qualified) < needed:
            issues.append(LabRotationPreflightIssue(
                severity="blocking", kind="teachers",
                message=f"{subject.name} needs {needed} qualified teacher(s) at a time but has "
                        f"{len(qualified)}. In a rotation it only ever runs with one batch at a "
                        "time, so this is the minimum - qualify another teacher for it.",
            ))

    # Rooms: a round runs every lab in the group simultaneously, so the
    # group's busiest round needs that many suitable rooms at once.
    concurrent = min(len(batches), len(subjects)) if batches and subjects else 0
    room_types = {s.requires_room_type for s in subjects if s.requires_room_type} or {"lab"}
    usable = [
        room for room in db.query(Room).filter(Room.type.in_(room_types)).all()
        if room.department_id is None
        or room.department_id == rotation.department_id
        or rotation.department_id in (room.shared_with_departments or [])
    ]
    biggest_batch = max((b.strength for b in batches), default=0)
    big_enough = [r for r in usable if r.capacity >= biggest_batch]
    if concurrent and len(big_enough) < concurrent:
        issues.append(LabRotationPreflightIssue(
            severity="blocking", kind="rooms",
            message=f"{concurrent} labs run at the same time in each round, but only "
                    f"{len(big_enough)} room(s) of type {sorted(room_types)} seat the largest batch "
                    f"({biggest_batch} students). Add a room, or take a lab out of the rotation.",
        ))

    if rotation.day and rotation.start_time is not None and rotation.end_time is not None:
        periods_per_round = max(1, (subjects[0].periods_per_session or 1) if subjects else 1)
        slots = [
            slot for slot in department_time_slots(db, rotation.department_id)
            if slot.day == rotation.day
            and str(slot.start_time) >= str(rotation.start_time)
            and str(slot.end_time) <= str(rotation.end_time)
        ]
        capacity = len(slots) // periods_per_round
        if rounds and capacity < rounds:
            issues.append(LabRotationPreflightIssue(
                severity="blocking", kind="window",
                message=f"The window {rotation.day} {rotation.start_time}-{rotation.end_time} fits "
                        f"{capacity} round(s) of {periods_per_round} period(s), but this rotation "
                        f"needs {rounds}. Widen the window, or leave it unpinned and let the solver "
                        "place the rounds.",
            ))

    return LabRotationPreflightResponse(
        feasible=not any(i.severity == "blocking" for i in issues),
        batch_count=len(batches), round_count=rounds, issues=issues,
    )
