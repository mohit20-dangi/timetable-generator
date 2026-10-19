"""Department scoping: which department a record belongs to, and whether a
user may see or change it.

Every role except SUPERADMIN is pinned to the department on its account.
Routers ask three questions, all answered here so the rule lives in one
place instead of being re-derived (and drifting) in every endpoint:

  * list_department(user, requested) - which department a list is
    filtered to (a SUPERADMIN may ask for any, or all with None).
  * assert_can_manage(user, department_id) - may this user change data
    in that department?
  * department_of(db, record) - which department an existing record
    belongs to, following the parent chain for records that don't carry
    a department_id themselves (a lab batch -> its section -> its year).
"""
from contextvars import ContextVar
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import SUPERADMIN
from app.models import (
    AcademicYear, GeneratedEntry, LabBatch, Prerequisite, Section, SectionSubject,
    Subject, Teacher, TeacherSubject, TimetableRun, User,
)


# The department the superadmin currently has selected in the UI, sent as
# the X-Department-Id header on every request (see the middleware in
# app/main.py). The superadmin isn't pinned to a department, so without
# this every list would mix all departments and a new record would land in
# none. Ignored for everyone else - their department is on their account.
active_department: ContextVar[Optional[str]] = ContextVar("active_department", default=None)


def is_superadmin(user: User) -> bool:
    return user.role == SUPERADMIN


def list_department(user: User, requested: Optional[str] = None) -> Optional[str]:
    """The department a list endpoint should be filtered to. None means
    "every department" and is only ever returned for a SUPERADMIN who
    hasn't selected one."""
    if is_superadmin(user):
        return requested or active_department.get()
    return user.department_id or "__no_department__"


def assert_can_access(user: User, department_id: Optional[str]) -> None:
    """Read/run access: a SUPERADMIN anywhere, everyone else only in their
    own department. A record with no department (legacy shared data) is
    only reachable by a SUPERADMIN."""
    if is_superadmin(user):
        return
    if not user.department_id or department_id != user.department_id:
        raise HTTPException(status_code=403, detail="You can only work with your own department's data.")


# Changing data has the same department rule; the ROLE half of "may change"
# (DEPT_ADMIN vs HOD) is enforced by the endpoint's require_* dependency.
assert_can_manage = assert_can_access


def target_department(user: User, department_id: Optional[str]) -> Optional[str]:
    """The department a new record goes into: a department-pinned user's
    own department when the payload leaves it blank, and never another
    one."""
    if not department_id:
        department_id = active_department.get() if is_superadmin(user) else user.department_id
    assert_can_manage(user, department_id)
    return department_id


def department_of(db: Session, record: Any) -> Optional[str]:
    if record is None:
        return None
    if hasattr(record, "department_id"):
        return record.department_id
    if isinstance(record, Section):
        year = db.get(AcademicYear, record.year_id)
        return year.department_id if year else None
    if isinstance(record, (LabBatch, SectionSubject)):
        return department_of(db, db.get(Section, record.section_id))
    if isinstance(record, TeacherSubject):
        return department_of(db, db.get(Teacher, record.teacher_id))
    if isinstance(record, Prerequisite):
        return department_of(db, db.get(Subject, record.subject_id))
    if isinstance(record, GeneratedEntry):
        return department_of(db, db.get(TimetableRun, record.timetable_run_id))
    raise TypeError(f"No department rule for {type(record).__name__}")


def department_criterion(model: Any, department_id: str):
    """A SQLAlchemy filter selecting `model`'s rows in one department - the
    query-side twin of department_of, for list endpoints and scoped
    resets."""
    if hasattr(model, "department_id"):
        return model.department_id == department_id
    year_ids = select(AcademicYear.id).where(AcademicYear.department_id == department_id)
    section_ids = select(Section.id).where(Section.year_id.in_(year_ids))
    if model is Section:
        return Section.year_id.in_(year_ids)
    if model in (LabBatch, SectionSubject):
        return model.section_id.in_(section_ids)
    if model is TeacherSubject:
        return TeacherSubject.teacher_id.in_(select(Teacher.id).where(Teacher.department_id == department_id))
    if model is Prerequisite:
        return Prerequisite.subject_id.in_(select(Subject.id).where(Subject.department_id == department_id))
    if model is GeneratedEntry:
        return GeneratedEntry.timetable_run_id.in_(
            select(TimetableRun.id).where(TimetableRun.department_id == department_id)
        )
    raise TypeError(f"No department rule for {model.__name__}")


def scoped(query: Any, model: Any, user: User, requested: Optional[str] = None) -> Any:
    """Filters a list query to the departments `user` may see."""
    department_id = list_department(user, requested)
    if department_id is None:
        return query
    return query.filter(department_criterion(model, department_id))


def get_scoped_or_404(db: Session, model: Any, record_id: Any, user: User, label: str) -> Any:
    """Fetch a record the user is allowed to reach. A record in another
    department answers 404, not 403, so ids of other departments' data
    aren't confirmed to exist."""
    record = db.get(model, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    if not is_superadmin(user) and department_of(db, record) != user.department_id:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return record
