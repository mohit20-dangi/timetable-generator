from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import time
from app.db import get_db
from app.models import (
    SectionSubject, LabBatch, Prerequisite, TimeSlot, ConstraintProfile,
    Section, Subject, Room, TeacherSubject, GeneratedEntry, TimetableRun, User,
)
from app.schemas import (
    SectionSubjectCreate, LabBatchCreate, LabBatchResponse,
    PrerequisiteCreate, TimeSlotCreate, TimeSlotResponse,
    ConstraintProfileCreate, ConstraintProfileResponse,
    BatchPreflightResponse, BatchPreflightIssue,
)
from app.auth.dependencies import get_current_user, require_admin
from app.routers.elective_groups import _max_rooms_free_together

router = APIRouter(prefix="/api/constraints", tags=["Constraints"])

SCHEDULE_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Section-Subject mappings
@router.get("/section-subjects")
def list_all_section_subjects(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(SectionSubject).all()

@router.post("/section-subjects")
def add_section_subject(ss: SectionSubjectCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if not db.query(Section).filter(Section.id == ss.section_id).first():
        raise HTTPException(status_code=400, detail="section_id does not exist")
    if not db.query(Subject).filter(Subject.id == ss.subject_id).first():
        raise HTTPException(status_code=400, detail="subject_id does not exist")
    if db.query(SectionSubject).filter(
        SectionSubject.section_id == ss.section_id, SectionSubject.subject_id == ss.subject_id
    ).first():
        raise HTTPException(status_code=409, detail="This subject is already assigned to this section")
    db_ss = SectionSubject(**ss.model_dump())
    db.add(db_ss)
    db.commit()
    return {"message": "Section-Subject mapping added"}

@router.get("/section-subjects/{section_id}")
def get_section_subjects(section_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(SectionSubject).filter(SectionSubject.section_id == section_id).all()

@router.delete("/section-subjects/{section_id}/{subject_id}")
def remove_section_subject(section_id: str, subject_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
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
def create_lab_batch(batch: LabBatchCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    section = db.query(Section).filter(Section.id == batch.section_id).first()
    if not section:
        raise HTTPException(status_code=400, detail="section_id does not exist")
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
def list_all_lab_batches(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(LabBatch).all()

@router.get("/lab-batches/{section_id}", response_model=List[LabBatchResponse])
def get_lab_batches(section_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(LabBatch).filter(LabBatch.section_id == section_id).all()

@router.delete("/lab-batches/{batch_id}")
def delete_lab_batch(
    batch_id: str, dry_run: bool = False, db: Session = Depends(get_db), _admin: User = Depends(require_admin),
):
    batch = db.query(LabBatch).filter(LabBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Lab batch not found")

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
    db: Session = Depends(get_db), _user: User = Depends(get_current_user),
):
    """Phase 2.9: checks, in plain language, whether this subject's lab
    batches can actually run under their configured batch_scheduling_mode
    before the admin clicks Generate - same purpose as the elective-group
    preflight check (see elective_groups.py), for parallel/merged batches."""
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

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
    bell_schedule = db.query(TimeSlot).all()
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
def add_prerequisite(prereq: PrerequisiteCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if not db.query(Subject).filter(Subject.id == prereq.subject_id).first():
        raise HTTPException(status_code=400, detail="subject_id does not exist")
    if not db.query(Subject).filter(Subject.id == prereq.requires_subject_id).first():
        raise HTTPException(status_code=400, detail="requires_subject_id does not exist")
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
def list_prerequisites(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Prerequisite).all()

@router.delete("/prerequisites/{subject_id}/{requires_subject_id}")
def remove_prerequisite(subject_id: str, requires_subject_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
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
@router.post("/time-slots", response_model=TimeSlotResponse)
def create_time_slot(ts: TimeSlotCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
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
    ).first():
        raise HTTPException(status_code=409, detail="That day and period already has a time slot")
    db_ts = TimeSlot(**ts.model_dump())
    db.add(db_ts)
    db.commit()
    db.refresh(db_ts)
    return db_ts

@router.get("/time-slots", response_model=List[TimeSlotResponse])
def list_time_slots(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(TimeSlot).all()

@router.delete("/time-slots/{slot_id}")
def delete_time_slot(slot_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    ts = db.query(TimeSlot).filter(TimeSlot.id == slot_id).first()
    if not ts:
        raise HTTPException(status_code=404, detail="Time slot not found")
    db.delete(ts)
    db.commit()
    return {"message": "Time slot deleted"}

# Constraint Profiles
@router.post("/profiles", response_model=ConstraintProfileResponse)
def create_constraint_profile(profile: ConstraintProfileCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(ConstraintProfile).filter(ConstraintProfile.id == profile.id).first():
        raise HTTPException(status_code=409, detail="A constraint profile with this id already exists")
    db_profile = ConstraintProfile(**profile.model_dump())
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.get("/profiles", response_model=List[ConstraintProfileResponse])
def list_constraint_profiles(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(ConstraintProfile).all()

@router.get("/profiles/{profile_id}", response_model=ConstraintProfileResponse)
def get_constraint_profile(profile_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    profile = db.query(ConstraintProfile).filter(ConstraintProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Constraint profile not found")
    return profile

@router.put("/profiles/{profile_id}", response_model=ConstraintProfileResponse)
def update_constraint_profile(profile_id: str, profile: ConstraintProfileCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(ConstraintProfile).filter(ConstraintProfile.id == profile_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Constraint profile not found")
    for key, value in profile.model_dump(exclude={"id"}).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record

@router.delete("/profiles/{profile_id}")
def delete_constraint_profile(profile_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    profile = db.query(ConstraintProfile).filter(ConstraintProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Constraint profile not found")
    db.delete(profile)
    db.commit()
    return {"message": "Constraint profile deleted"}
