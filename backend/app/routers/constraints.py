from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import time
from app.db import get_db
from app.models import (
    SectionSubject, LabBatch, Prerequisite, TimeSlot, ConstraintProfile,
    Section, Subject, Room, TeacherSubject, GeneratedEntry, TimetableRun, User,
)
from app.schemas import (
    SectionSubjectCreate, LabBatchCreate, LabBatchResponse,
    PrerequisiteCreate, TimeSlotCreate, TimeSlotResponse, TimeSlotUpdate, BellScheduleReplace,
    ConstraintProfileCreate, ConstraintProfileResponse,
    BatchPreflightResponse, BatchPreflightIssue,
)
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import (
    assert_can_manage, department_of, get_scoped_or_404, list_department, scoped, target_department,
)
from app.services.department_calendar import (
    department_time_slots, ensure_own_time_slots, number_schedule, slot_id,
)
from app.routers.elective_groups import _max_rooms_free_together

router = APIRouter(prefix="/api/constraints", tags=["Constraints"])


class SectionSubjectAttendance(BaseModel):
    attends_with_section_id: Optional[str] = None
    attends_with_batch_id: Optional[str] = None


SCHEDULE_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def _validate_attendance(db, section_id, subject_id, host_section_id, host_batch_id) -> None:
    """A section may attend another section's class for a subject only when
    that class really exists: same department, the host teaches the subject
    itself (attendance never chains), and a lab batch belongs to the host."""
    if host_section_id is None:
        if host_batch_id is not None:
            raise HTTPException(status_code=400, detail="attends_with_batch_id needs attends_with_section_id")
        return
    if host_section_id == section_id:
        raise HTTPException(status_code=400, detail="A section cannot attend its own class")
    section = db.get(Section, section_id)
    host = db.get(Section, host_section_id)
    if not host:
        raise HTTPException(status_code=400, detail="attends_with_section_id does not exist")
    if department_of(db, section) != department_of(db, host):
        raise HTTPException(status_code=400, detail="The host section must be in the same department")
    host_row = db.query(SectionSubject).filter(
        SectionSubject.section_id == host_section_id, SectionSubject.subject_id == subject_id
    ).first()
    if not host_row:
        raise HTTPException(
            status_code=400,
            detail=f"Section {host.name} does not take this subject, so there is no class to attend",
        )
    if host_row.attends_with_section_id:
        raise HTTPException(
            status_code=400,
            detail=f"Section {host.name} itself attends this subject with another section; pick that section instead",
        )
    if host_batch_id is not None:
        batch = db.get(LabBatch, host_batch_id)
        if not batch or batch.section_id != host_section_id:
            raise HTTPException(status_code=400, detail="attends_with_batch_id is not a batch of the host section")


# Section-Subject mappings
@router.get("/section-subjects")
def list_all_section_subjects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return scoped(db.query(SectionSubject), SectionSubject, user).all()

@router.post("/section-subjects")
def add_section_subject(ss: SectionSubjectCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    section = db.query(Section).filter(Section.id == ss.section_id).first()
    if not section:
        raise HTTPException(status_code=400, detail="section_id does not exist")
    subject = db.query(Subject).filter(Subject.id == ss.subject_id).first()
    if not subject:
        raise HTTPException(status_code=400, detail="subject_id does not exist")
    assert_can_manage(admin, department_of(db, section))
    assert_can_manage(admin, subject.department_id)
    if db.query(SectionSubject).filter(
        SectionSubject.section_id == ss.section_id, SectionSubject.subject_id == ss.subject_id
    ).first():
        raise HTTPException(status_code=409, detail="This subject is already assigned to this section")
    _validate_attendance(db, ss.section_id, ss.subject_id, ss.attends_with_section_id, ss.attends_with_batch_id)
    db_ss = SectionSubject(**ss.model_dump())
    db.add(db_ss)
    db.commit()
    return {"message": "Section-Subject mapping added"}


@router.put("/section-subjects/{section_id}/{subject_id}/attends-with")
def set_section_subject_attendance(
    section_id: str, subject_id: str, payload: SectionSubjectAttendance,
    db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    """Makes a section take a subject by sitting in another section's class
    (or stops doing so when both ids are null) - how a repeater section is
    merged into the regular classes."""
    get_scoped_or_404(db, Section, section_id, admin, "Section")
    ss = db.query(SectionSubject).filter(
        SectionSubject.section_id == section_id, SectionSubject.subject_id == subject_id
    ).first()
    if not ss:
        raise HTTPException(status_code=404, detail="Mapping not found")
    _validate_attendance(db, section_id, subject_id, payload.attends_with_section_id, payload.attends_with_batch_id)
    ss.attends_with_section_id = payload.attends_with_section_id
    ss.attends_with_batch_id = payload.attends_with_batch_id
    db.commit()
    return {"message": "Attendance updated"}

@router.get("/section-subjects/{section_id}")
def get_section_subjects(section_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_scoped_or_404(db, Section, section_id, user, "Section")
    return db.query(SectionSubject).filter(SectionSubject.section_id == section_id).all()

@router.delete("/section-subjects/{section_id}/{subject_id}")
def remove_section_subject(section_id: str, subject_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    get_scoped_or_404(db, Section, section_id, admin, "Section")
    ss = db.query(SectionSubject).filter(
        SectionSubject.section_id == section_id,
        SectionSubject.subject_id == subject_id
    ).first()
    if not ss:
        raise HTTPException(status_code=404, detail="Mapping not found")
    db.delete(ss)
    db.commit()
    return {"message": "Section-Subject mapping removed"}

# Lab Batches
@router.post("/lab-batches", response_model=LabBatchResponse)
def create_lab_batch(batch: LabBatchCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    section = db.query(Section).filter(Section.id == batch.section_id).first()
    if not section:
        raise HTTPException(status_code=400, detail="section_id does not exist")
    assert_can_manage(admin, department_of(db, section))
    if db.query(LabBatch).filter(LabBatch.id == batch.id).first():
        raise HTTPException(status_code=409, detail="A lab batch with this id already exists")
    # Phase 2.8: batches are real sub-groups of the section's students, so
    # their strengths can't add up to more than the section itself - being
    # under is fine (real batches are uneven; the admin enters approximations).
    existing_total = sum(
        b.strength for b in db.query(LabBatch).filter(LabBatch.section_id == batch.section_id).all()
    )
    if existing_total + batch.strength > section.strength:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This batch would bring {section.name}'s batch strengths to "
                f"{existing_total + batch.strength}, more than the section's {section.strength} students."
            ),
        )
    db_batch = LabBatch(**batch.model_dump())
    db.add(db_batch)
    db.commit()
    db.refresh(db_batch)
    return db_batch

@router.get("/lab-batches", response_model=List[LabBatchResponse])
def list_all_lab_batches(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return scoped(db.query(LabBatch), LabBatch, user).all()

@router.get("/lab-batches/{section_id}", response_model=List[LabBatchResponse])
def get_lab_batches(section_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_scoped_or_404(db, Section, section_id, user, "Section")
    return db.query(LabBatch).filter(LabBatch.section_id == section_id).all()

@router.delete("/lab-batches/{batch_id}")
def delete_lab_batch(
    batch_id: str, dry_run: bool = False, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    batch = get_scoped_or_404(db, LabBatch, batch_id, admin, "Lab batch")

    published = (
        db.query(GeneratedEntry)
        .join(TimetableRun, TimetableRun.id == GeneratedEntry.timetable_run_id)
        .filter(GeneratedEntry.batch_id == batch_id, TimetableRun.is_published.is_(True))
        .first()
    )
    blocked_reason = (
        "This lab batch is used in a published timetable and cannot be deleted while it is live."
        if published else None
    )

    if dry_run:
        return {"deletes": {}, "blocked_reason": blocked_reason}
    if blocked_reason:
        raise HTTPException(status_code=409, detail=blocked_reason)

    db.delete(batch)
    db.commit()
    return {"message": "Lab batch deleted"}


@router.get("/lab-batches/{section_id}/preflight", response_model=BatchPreflightResponse)
def preflight_lab_batches(
    section_id: str, subject_id: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Phase 2.9: checks, in plain language, whether this subject's lab
    batches can actually run under their configured batch_scheduling_mode
    before the admin clicks Generate - same purpose as the elective-group
    preflight check (see elective_groups.py), for parallel/merged batches."""
    section = get_scoped_or_404(db, Section, section_id, user, "Section")
    subject = get_scoped_or_404(db, Subject, subject_id, user, "Subject")

    batches = db.query(LabBatch).filter(LabBatch.section_id == section_id).all()
    mode = subject.batch_scheduling_mode or "independent"
    batch_count = len(batches)
    combined_strength = sum(b.strength for b in batches)

    if batch_count < 2:
        return BatchPreflightResponse(
            feasible=True, mode=mode, batch_count=batch_count,
            combined_strength=combined_strength,
            rooms_available_in_common_slot=0, qualified_teachers=0, issues=[],
        )

    issues: List[BatchPreflightIssue] = []
    room_types_needed = {subject.requires_room_type} if subject.requires_room_type else {"lab", "lecture"}
    candidate_rooms = db.query(Room).filter(Room.type.in_(room_types_needed)).all()
    usable_rooms = [
        r for r in candidate_rooms
        if r.department_id is None
        or r.department_id == subject.department_id
        or subject.department_id in (r.shared_with_departments or [])
    ]
    bell_schedule = department_time_slots(db, department_of(db, section))
    qualified_teacher_ids = {
        row.teacher_id for row in
        db.query(TeacherSubject).filter(TeacherSubject.subject_id == subject_id).all()
    }
    qualified_teachers = len(qualified_teacher_ids)

    if mode == "merged":
        # Only ONE room is ever occupied at once (the batches are taught
        # together), so the question isn't "free in a common slot" but
        # "does any eligible room seat everyone combined".
        rooms_available = sum(1 for r in usable_rooms if r.capacity >= combined_strength)
        if rooms_available < 1:
            issues.append(BatchPreflightIssue(
                severity="blocking",
                message=(
                    f"No eligible room seats all {batch_count} batches together "
                    f"({combined_strength} students combined)."
                ),
                kind="rooms",
            ))
        if qualified_teachers < 1:
            issues.append(BatchPreflightIssue(
                severity="blocking", message=f"No teacher is qualified to teach {subject.name}.",
                kind="teachers",
            ))
    elif mode == "parallel":
        rooms_available = _max_rooms_free_together(usable_rooms, bell_schedule)
        if rooms_available < batch_count:
            issues.append(BatchPreflightIssue(
                severity="blocking",
                message=(
                    f"There aren't enough rooms to run all {batch_count} batches at the same hour: "
                    f"only {rooms_available} suitable rooms free together."
                ),
                kind="rooms",
            ))
        if qualified_teachers < batch_count:
            issues.append(BatchPreflightIssue(
                severity="blocking",
                message=(
                    f"There aren't enough qualified teachers to run all {batch_count} batches at "
                    f"once: {qualified_teachers} teacher(s) qualified for {subject.name}."
                ),
                kind="teachers",
            ))
    else:
        # independent / sequential: batches never need to occupy a room at
        # the same instant, so the batch count itself isn't a bottleneck -
        # only "does anyone qualify to teach this at all" is checked.
        rooms_available = _max_rooms_free_together(usable_rooms, bell_schedule)
        if qualified_teachers < 1:
            issues.append(BatchPreflightIssue(
                severity="blocking", message=f"No teacher is qualified to teach {subject.name}.",
                kind="teachers",
            ))

    return BatchPreflightResponse(
        feasible=not any(i.severity == "blocking" for i in issues),
        mode=mode, batch_count=batch_count, combined_strength=combined_strength,
        rooms_available_in_common_slot=rooms_available, qualified_teachers=qualified_teachers,
        issues=issues,
    )

# Prerequisites
@router.post("/prerequisites")
def add_prerequisite(prereq: PrerequisiteCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    for field in ("subject_id", "requires_subject_id"):
        subject = db.query(Subject).filter(Subject.id == getattr(prereq, field)).first()
        if not subject:
            raise HTTPException(status_code=400, detail=f"{field} does not exist")
        assert_can_manage(admin, subject.department_id)
    if db.query(Prerequisite).filter(
        Prerequisite.subject_id == prereq.subject_id,
        Prerequisite.requires_subject_id == prereq.requires_subject_id,
    ).first():
        raise HTTPException(status_code=409, detail="This prerequisite already exists")
    db_prereq = Prerequisite(**prereq.model_dump())
    db.add(db_prereq)
    db.commit()
    return {"message": "Prerequisite added"}

@router.get("/prerequisites")
def list_prerequisites(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return scoped(db.query(Prerequisite), Prerequisite, user).all()

@router.delete("/prerequisites/{subject_id}/{requires_subject_id}")
def remove_prerequisite(subject_id: str, requires_subject_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    get_scoped_or_404(db, Subject, subject_id, admin, "Subject")
    prereq = db.query(Prerequisite).filter(
        Prerequisite.subject_id == subject_id,
        Prerequisite.requires_subject_id == requires_subject_id
    ).first()
    if not prereq:
        raise HTTPException(status_code=404, detail="Prerequisite not found")
    db.delete(prereq)
    db.commit()
    return {"message": "Prerequisite removed"}

# Time Slots
_DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}


def _clock(t: time) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'PM' if t.hour >= 12 else 'AM'}"


def _assert_valid_schedule(periods: list) -> None:
    """Periods on one day (both kinds) must not overlap: the solver's calendar
    would treat two slots at the same wall time as separate indices and could
    book a teacher into both."""
    by_day: dict = {}
    for p in periods:
        if p["end_time"] <= p["start_time"]:
            raise HTTPException(status_code=400, detail=f"{_DAY_NAMES.get(p['day'], p['day'])}: {_clock(p['start_time'])} - {_clock(p['end_time'])} ends before it starts")
        by_day.setdefault(p["day"], []).append(p)
    for day, rows in by_day.items():
        rows = sorted(rows, key=lambda p: p["start_time"])
        for a, b in zip(rows, rows[1:]):
            if b["start_time"] < a["end_time"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"{_DAY_NAMES.get(day, day)}: {_clock(a['start_time'])} - {_clock(a['end_time'])} overlaps {_clock(b['start_time'])} - {_clock(b['end_time'])}",
                )


def _save_numbered(db: Session, department_id, periods: list) -> list:
    rows = [
        TimeSlot(
            id=slot_id(department_id, p["day"], p["period_index"]), day=p["day"], period_index=p["period_index"],
            start_time=p["start_time"], end_time=p["end_time"], department_id=department_id, slot_kind=p["slot_kind"],
        )
        for p in number_schedule(periods)
    ]
    db.add_all(rows)
    return rows


@router.put("/time-slots", response_model=List[TimeSlotResponse])
def replace_time_slots(body: BellScheduleReplace, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    """Atomically replaces the department's whole bell schedule. The server
    numbers the periods; a rejected payload leaves the old schedule intact."""
    department_id = target_department(admin, body.department_id)
    periods = [p.model_dump() for p in body.periods]
    _assert_valid_schedule(periods)
    db.query(TimeSlot).filter(TimeSlot.department_id == department_id).delete(synchronize_session="fetch")
    rows = _save_numbered(db, department_id, periods)
    db.commit()
    day_rank = {d: i for i, d in enumerate(SCHEDULE_DAYS)}
    return sorted(rows, key=lambda r: (day_rank[r.day], r.period_index))


@router.put("/time-slots/{slot_id_}", response_model=TimeSlotResponse)
def update_time_slot(slot_id_: str, body: TimeSlotUpdate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    ts = db.get(TimeSlot, slot_id_)
    department_id = list_department(admin)
    if ts is not None and ts.department_id is None and department_id:
        copies = ensure_own_time_slots(db, department_id)
        ts = db.get(TimeSlot, copies.get(slot_id_, slot_id_))
    if ts is None:
        raise HTTPException(status_code=404, detail="Time slot not found")
    assert_can_manage(admin, ts.department_id)
    owner = ts.department_id
    old_day = ts.day
    others = [
        {"day": o.day, "start_time": o.start_time, "end_time": o.end_time, "slot_kind": o.slot_kind or "regular"}
        for o in db.query(TimeSlot).filter(TimeSlot.department_id == owner, TimeSlot.id != ts.id, TimeSlot.day.in_({old_day, body.day})).all()
    ]
    edited = {"day": body.day, "start_time": body.start_time, "end_time": body.end_time, "slot_kind": body.slot_kind}
    _assert_valid_schedule([p for p in others + [edited] if p["day"] == body.day])
    db.query(TimeSlot).filter(TimeSlot.department_id == owner, TimeSlot.day.in_({old_day, body.day})).delete(synchronize_session="fetch")
    rows = _save_numbered(db, owner, others + [edited])
    db.commit()
    return next(r for r in rows if (r.day, r.start_time, r.end_time, r.slot_kind) == (body.day, body.start_time, body.end_time, body.slot_kind))


@router.post("/time-slots", response_model=TimeSlotResponse)
def create_time_slot(ts: TimeSlotCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    department_id = target_department(admin, ts.department_id)
    if department_id:
        ensure_own_time_slots(db, department_id)
    if ts.day not in SCHEDULE_DAYS:
        raise HTTPException(status_code=400, detail=f"day must be one of {SCHEDULE_DAYS}")
    if ts.period_index < 1:
        raise HTTPException(status_code=400, detail="period_index must be at least 1")
    if ts.start_time >= ts.end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")
    if db.query(TimeSlot).filter(TimeSlot.id == ts.id).first():
        raise HTTPException(status_code=409, detail="A time slot with this id already exists")
    if db.query(TimeSlot).filter(
        TimeSlot.day == ts.day,
        TimeSlot.period_index == ts.period_index,
        TimeSlot.department_id == department_id,
    ).first():
        raise HTTPException(status_code=409, detail="That day and period already has a time slot")
    db_ts = TimeSlot(**{**ts.model_dump(), "department_id": department_id})
    db.add(db_ts)
    db.commit()
    db.refresh(db_ts)
    return db_ts

@router.get("/time-slots", response_model=List[TimeSlotResponse])
def list_time_slots(
    department_id: str | None = None, kind: str = "regular",
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """The bell schedule the department actually runs on (its own periods,
    or the pre-separation shared ones until it sets up its own). `kind` is
    "regular" (the main timetable's periods, the default so existing screens
    are unchanged), "remedial" or "all"."""
    if kind not in ("regular", "remedial", "all"):
        raise HTTPException(status_code=400, detail="kind must be regular, remedial or all")
    slot_kind = None if kind == "all" else kind
    department_id = list_department(user, department_id)
    if department_id is None:
        slots = db.query(TimeSlot).all()
        return [s for s in slots if slot_kind is None or (s.slot_kind or "regular") == slot_kind]
    return department_time_slots(db, department_id, kind=slot_kind)

@router.delete("/time-slots/{slot_id}")
def delete_time_slot(slot_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    ts = db.get(TimeSlot, slot_id)
    department_id = list_department(admin)
    if ts is not None and ts.department_id is None and department_id:
        # Deleting a period from the shared schedule a department is still
        # running on: give the department its own copy, then delete from that.
        copies = ensure_own_time_slots(db, department_id)
        ts = db.get(TimeSlot, copies.get(slot_id, slot_id))
    if ts is None:
        raise HTTPException(status_code=404, detail="Time slot not found")
    assert_can_manage(admin, ts.department_id)
    db.delete(ts)
    db.commit()
    return {"message": "Time slot deleted"}

# Constraint Profiles
@router.post("/profiles", response_model=ConstraintProfileResponse)
def create_constraint_profile(profile: ConstraintProfileCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if db.query(ConstraintProfile).filter(ConstraintProfile.id == profile.id).first():
        raise HTTPException(status_code=409, detail="A constraint profile with this id already exists")
    data = profile.model_dump()
    data["department_id"] = target_department(admin, data.get("department_id"))
    db_profile = ConstraintProfile(**data)
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.get("/profiles", response_model=List[ConstraintProfileResponse])
def list_constraint_profiles(department_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return scoped(db.query(ConstraintProfile), ConstraintProfile, user, department_id).all()

@router.get("/profiles/{profile_id}", response_model=ConstraintProfileResponse)
def get_constraint_profile(profile_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_scoped_or_404(db, ConstraintProfile, profile_id, user, "Constraint profile")

@router.put("/profiles/{profile_id}", response_model=ConstraintProfileResponse)
def update_constraint_profile(profile_id: str, profile: ConstraintProfileCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, ConstraintProfile, profile_id, admin, "Constraint profile")
    data = profile.model_dump(exclude={"id"})
    data["department_id"] = target_department(admin, data.get("department_id"))
    for key, value in data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record

@router.delete("/profiles/{profile_id}")
def delete_constraint_profile(profile_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    profile = get_scoped_or_404(db, ConstraintProfile, profile_id, admin, "Constraint profile")
    db.delete(profile)
    db.commit()
    return {"message": "Constraint profile deleted"}
