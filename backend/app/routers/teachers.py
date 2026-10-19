from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Teacher, TeacherSubject, Subject, GeneratedEntry, TimetableRun, User
from app.schemas import TeacherCreate, TeacherResponse, TeacherSubjectCreate
from app.services.entry_teachers import co_teacher_ids, entry_teacher_ids
from app.auth.dependencies import get_current_user, require_dept_admin
from app.auth.scope import assert_can_manage, get_scoped_or_404, scoped, target_department

router = APIRouter(prefix="/api/teachers", tags=["Teachers"])


def _assert_subjects_in_department(db: Session, admin: User, subject_ids) -> None:
    """A teacher can only be qualified for subjects their admin may manage -
    otherwise linking a teacher would quietly reach into another
    department's subjects."""
    for subject_id in subject_ids:
        subject = db.get(Subject, subject_id)
        if subject is None:
            raise HTTPException(status_code=400, detail=f"subject_id '{subject_id}' does not exist")
        assert_can_manage(admin, subject.department_id)

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
def create_teacher(teacher: TeacherCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    if db.query(Teacher).filter(Teacher.id == teacher.id).first():
        raise HTTPException(status_code=409, detail="A teacher with this id already exists")
    teacher_data = teacher.model_dump()
    teacher_data["department_id"] = target_department(admin, teacher_data.get("department_id"))
    subjects = teacher_data.pop("subjects", None) or []
    _assert_subjects_in_department(db, admin, subjects)
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
def list_teachers(department_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return scoped(db.query(Teacher), Teacher, user, department_id).all()

@router.get("/{teacher_id}", response_model=TeacherResponse)
def get_teacher(teacher_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_scoped_or_404(db, Teacher, teacher_id, user, "Teacher")

@router.put("/{teacher_id}", response_model=TeacherResponse)
def update_teacher(teacher_id: str, teacher: TeacherCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    record = get_scoped_or_404(db, Teacher, teacher_id, admin, "Teacher")
    data = teacher.model_dump(exclude={"id", "subjects"})
    data["department_id"] = target_department(admin, data.get("department_id"))
    if teacher.subjects is not None:
        _assert_subjects_in_department(db, admin, teacher.subjects)
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
def get_teacher_subjects(teacher_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_scoped_or_404(db, Teacher, teacher_id, user, "Teacher")
    rows = db.query(TeacherSubject).filter(TeacherSubject.teacher_id == teacher_id).all()
    return [row.subject_id for row in rows]


@router.post("/{teacher_id}/subjects")
def add_teacher_subject(teacher_id: str, ts: TeacherSubjectCreate, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    get_scoped_or_404(db, Teacher, teacher_id, admin, "Teacher")
    _assert_subjects_in_department(db, admin, [ts.subject_id])
    if db.query(TeacherSubject).filter(
        TeacherSubject.teacher_id == teacher_id, TeacherSubject.subject_id == ts.subject_id
    ).first():
        raise HTTPException(status_code=409, detail="This teacher is already qualified for this subject")

    db_ts = TeacherSubject(teacher_id=teacher_id, subject_id=ts.subject_id, role=ts.role)
    db.add(db_ts)
    db.commit()
    return {"message": "Subject added to teacher"}

@router.delete("/{teacher_id}/subjects/{subject_id}")
def remove_teacher_subject(teacher_id: str, subject_id: str, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    get_scoped_or_404(db, Teacher, teacher_id, admin, "Teacher")
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
    teacher_id: str, dry_run: bool = False, db: Session = Depends(get_db), admin: User = Depends(require_dept_admin),
):
    teacher = get_scoped_or_404(db, Teacher, teacher_id, admin, "Teacher")

    # A teacher who is only the SECOND supervisor on a co-taught lab is
    # still in a published timetable, and co_teacher_ids is a JSON list
    # with no foreign key to catch it - so it is checked explicitly rather
    # than letting the delete silently strand their name in a live run.
    published_rows = (
        db.query(GeneratedEntry)
        .join(TimetableRun, TimetableRun.id == GeneratedEntry.timetable_run_id)
        .filter(TimetableRun.is_published.is_(True))
        .filter(
            (GeneratedEntry.teacher_id == teacher_id)
            | GeneratedEntry.co_teacher_ids.isnot(None)
        )
        .all()
    )
    published = next(
        (e for e in published_rows if teacher_id in entry_teacher_ids(e)), None,
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
    # teacher_id is cleared by its FK's ON DELETE SET NULL; co_teacher_ids
    # is a plain JSON list, so a stale id there would keep showing a deleted
    # teacher as scheduled. Prune it by hand, in the unpublished runs that
    # survive this delete.
    for entry in db.query(GeneratedEntry).filter(GeneratedEntry.co_teacher_ids.isnot(None)).all():
        remaining = [t for t in co_teacher_ids(entry) if t != teacher_id]
        if len(remaining) != len(co_teacher_ids(entry)):
            entry.co_teacher_ids = remaining
    # A teacher login without its teacher record has nothing to show and
    # would block the delete on its foreign key - unlink and disable it.
    db.query(User).filter(User.teacher_id == teacher_id).update({User.teacher_id: None, User.is_active: False})
    db.delete(teacher)
    db.commit()
    return {"message": "Teacher deleted", "deleted": counts, "warning": warning, "affected_subjects": orphaned_subjects}
