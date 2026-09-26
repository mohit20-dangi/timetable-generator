from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Teacher, TeacherSubject, Subject, GeneratedEntry, TimetableRun, User
from app.schemas import TeacherCreate, TeacherResponse, TeacherSubjectCreate
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/teachers", tags=["Teachers"])

_TITLE_PREFIXES = ("prof.", "prof", "dr.", "dr", "mr.", "mr", "mrs.", "mrs", "ms.", "ms")


def _derive_teacher_initials(name: str) -> str:
    """A sensible default export initials when the admin hasn't set one -
    Phase 4.1. Strips a leading title (Prof./Dr./...) and takes the first
    letter of each remaining word, e.g. "Prof. D. A. Mehta" -> "DAM"."""
    words = [w.strip(".") for w in name.split() if w.strip(".")]
    words = [w for w in words if w.lower() not in _TITLE_PREFIXES]
    initials = "".join(w[0].upper() for w in words if w)
    return initials or name[:3].upper()


@router.post("/", response_model=TeacherResponse)
def create_teacher(teacher: TeacherCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(Teacher).filter(Teacher.id == teacher.id).first():
        raise HTTPException(status_code=409, detail="A teacher with this id already exists")
    teacher_data = teacher.model_dump()
    subjects = teacher_data.pop("subjects", None) or []
    teacher_data["initials"] = teacher_data["initials"] or _derive_teacher_initials(teacher.name)

    db_teacher = Teacher(**teacher_data)
    db.add(db_teacher)
    db.commit()
    db.refresh(db_teacher)

    for subject_id in subjects:
        ts = TeacherSubject(teacher_id=db_teacher.id, subject_id=subject_id)
        db.add(ts)
    db.commit()

    return db_teacher

@router.get("/", response_model=List[TeacherResponse])
def list_teachers(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Teacher).all()

@router.get("/{teacher_id}", response_model=TeacherResponse)
def get_teacher(teacher_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return teacher

@router.put("/{teacher_id}", response_model=TeacherResponse)
def update_teacher(teacher_id: str, teacher: TeacherCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    record = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Teacher not found")
    data = teacher.model_dump(exclude={"id", "subjects"})
    data["initials"] = data["initials"] or _derive_teacher_initials(teacher.name)
    for key, value in data.items():
        setattr(record, key, value)
    # Only replace mappings when the client explicitly provides them. This
    # keeps an edit of name/limits from silently removing qualifications.
    if teacher.subjects is not None:
        db.query(TeacherSubject).filter(TeacherSubject.teacher_id == teacher_id).delete()
        for subject_id in teacher.subjects:
            db.add(TeacherSubject(teacher_id=teacher_id, subject_id=subject_id))
    db.commit()
    db.refresh(record)
    return record

@router.get("/{teacher_id}/subjects")
def get_teacher_subjects(teacher_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    if not db.query(Teacher).filter(Teacher.id == teacher_id).first():
        raise HTTPException(status_code=404, detail="Teacher not found")
    rows = db.query(TeacherSubject).filter(TeacherSubject.teacher_id == teacher_id).all()
    return [row.subject_id for row in rows]


@router.post("/{teacher_id}/subjects")
def add_teacher_subject(teacher_id: str, ts: TeacherSubjectCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    if not db.query(Subject).filter(Subject.id == ts.subject_id).first():
        raise HTTPException(status_code=400, detail="subject_id does not exist")
    if db.query(TeacherSubject).filter(
        TeacherSubject.teacher_id == teacher_id, TeacherSubject.subject_id == ts.subject_id
    ).first():
        raise HTTPException(status_code=409, detail="This teacher is already qualified for this subject")

    db_ts = TeacherSubject(teacher_id=teacher_id, subject_id=ts.subject_id)
    db.add(db_ts)
    db.commit()
    return {"message": "Subject added to teacher"}

@router.delete("/{teacher_id}/subjects/{subject_id}")
def remove_teacher_subject(teacher_id: str, subject_id: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    ts = db.query(TeacherSubject).filter(
        TeacherSubject.teacher_id == teacher_id,
        TeacherSubject.subject_id == subject_id
    ).first()
    if not ts:
        raise HTTPException(status_code=404, detail="Teacher-Subject mapping not found")
    db.delete(ts)
    db.commit()
    return {"message": "Subject removed from teacher"}

@router.delete("/{teacher_id}")
def delete_teacher(
    teacher_id: str, dry_run: bool = False, db: Session = Depends(get_db), _admin: User = Depends(require_admin),
):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    published = (
        db.query(GeneratedEntry)
        .join(TimetableRun, TimetableRun.id == GeneratedEntry.timetable_run_id)
        .filter(GeneratedEntry.teacher_id == teacher_id, TimetableRun.is_published.is_(True))
        .first()
    )
    blocked_reason = (
        "This teacher is used in a published timetable and cannot be deleted while it is live."
        if published else None
    )

    subject_ids = [
        ts.subject_id for ts in db.query(TeacherSubject).filter(TeacherSubject.teacher_id == teacher_id).all()
    ]
    orphaned_subjects = [
        sid for sid in subject_ids
        if db.query(TeacherSubject)
        .filter(TeacherSubject.subject_id == sid, TeacherSubject.teacher_id != teacher_id)
        .count() == 0
    ]
    counts = {"teacher_subjects": len(subject_ids)}
    warning = (
        f"{len(orphaned_subjects)} subject(s) would be left with no qualified teacher."
        if orphaned_subjects else None
    )

    if dry_run:
        return {
            "deletes": counts, "warning": warning, "blocked_reason": blocked_reason,
            "affected_subjects": orphaned_subjects,
        }
    if blocked_reason:
        raise HTTPException(status_code=409, detail=blocked_reason)

    db.query(TeacherSubject).filter(TeacherSubject.teacher_id == teacher_id).delete()
    db.delete(teacher)
    db.commit()
    return {"message": "Teacher deleted", "deleted": counts, "warning": warning, "affected_subjects": orphaned_subjects}
