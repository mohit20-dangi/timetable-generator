from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.auth.security import decode_access_token

# Token endpoint used only for the interactive /docs "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise credentials_exception

    return user


def require_roles(*allowed_roles: str):
    """Usage: Depends(require_roles(SUPERADMIN, DEPT_ADMIN))"""

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return checker


# Roles, broadest first. Every role except SUPERADMIN is pinned to the one
# department on its account - role membership alone never grants access to
# another department's data; see app/auth/scope.py for that check.
SUPERADMIN = "SUPERADMIN"  # the developer/operator: every department
DEPT_ADMIN = "DEPT_ADMIN"  # full control of one department's setup and timetables
HOD = "HOD"                # one department's timetables: generate/edit/publish
TEACHER = "TEACHER"        # their own published timetable
ALL_ROLES = (SUPERADMIN, DEPT_ADMIN, HOD, TEACHER)

require_superadmin = require_roles(SUPERADMIN)
# Changing setup data (subjects, teachers, rooms, rules, users, imports).
require_dept_admin = require_roles(SUPERADMIN, DEPT_ADMIN)
# Generating, editing and publishing timetables.
require_timetable_manager = require_roles(SUPERADMIN, DEPT_ADMIN, HOD)
