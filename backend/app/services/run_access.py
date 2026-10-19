"""Department-scoped access to a TimetableRun, shared by the timetable and
manual-editor routers."""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import TEACHER
from app.auth.scope import assert_can_access
from app.models import TimetableRun, User


def assert_department_access(user: User, department_id: Optional[str]):
    """The superadmin can touch any department; everyone else only the one
    department on their account (see app/auth/scope.py)."""
    try:
        assert_can_access(user, department_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="You can only manage timetables for your own department.")


def get_run_scoped(db: Session, run_id: int, user: User) -> TimetableRun:
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    assert_department_access(user, run.department_id)
    # Teachers only ever see what's been published - a draft run isn't
    # theirs to look at, even in their own department.
    if user.role == TEACHER and not run.is_published:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
