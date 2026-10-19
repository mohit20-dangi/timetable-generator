from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User, Teacher, Department
from app.schemas import UserCreate, UserResponse, LoginRequest, TokenResponse
from app.auth.security import hash_password, verify_password, create_access_token
from app.auth.dependencies import (
    DEPT_ADMIN, HOD, SUPERADMIN, TEACHER, get_current_user, require_dept_admin,
)
from app.auth.scope import is_superadmin

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# Which roles each role may hand out. A department admin runs their own
# department's accounts but can't create another admin - that, and any
# department admin at all, comes from the superadmin.
GRANTABLE_ROLES = {
    SUPERADMIN: {SUPERADMIN, DEPT_ADMIN, HOD, TEACHER},
    DEPT_ADMIN: {HOD, TEACHER},
}


@router.post("/bootstrap-admin", response_model=UserResponse)
def bootstrap_admin(user: UserCreate, db: Session = Depends(get_db)):
    """
    Create the very first account - always the SUPERADMIN. Only works when
    there are zero users in the system. After that, this endpoint always
    refuses, and new users must be created via POST /api/auth/register.
    """
    if db.query(User).count() > 0:
        raise HTTPException(
            status_code=403,
            detail="An admin already exists. Use /api/auth/register (as an admin) to add more users.",
        )
    if user.role != SUPERADMIN:
        raise HTTPException(status_code=400, detail="First bootstrapped user must have role=SUPERADMIN")

    db_user = User(
        email=user.email,
        hashed_password=hash_password(user.password),
        full_name=user.full_name,
        role=SUPERADMIN,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/register", response_model=UserResponse)
def register(
    user: UserCreate,
    db: Session = Depends(get_db),
    creator: User = Depends(require_dept_admin),
):
    """Create a new user account. A department admin creates HOD and teacher
    accounts in their own department; the superadmin creates anything."""
    if user.role not in GRANTABLE_ROLES[creator.role]:
        raise HTTPException(status_code=403, detail=f"You can't create {user.role} accounts")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    department_id = None
    teacher_id = None
    if user.role == TEACHER:
        teacher = db.query(Teacher).filter(Teacher.id == user.teacher_id).first() if user.teacher_id else None
        if not teacher:
            raise HTTPException(status_code=400, detail="Valid teacher_id is required for TEACHER users")
        teacher_id = teacher.id
        department_id = teacher.department_id
    elif user.role in (DEPT_ADMIN, HOD):
        department_id = user.department_id if is_superadmin(creator) else creator.department_id
        if not department_id or not db.query(Department).filter(Department.id == department_id).first():
            raise HTTPException(status_code=400, detail=f"Valid department_id is required for {user.role} users")
    if not is_superadmin(creator) and department_id != creator.department_id:
        raise HTTPException(status_code=403, detail="You can only create accounts in your own department")

    db_user = User(
        email=user.email,
        hashed_password=hash_password(user.password),
        full_name=user.full_name,
        role=user.role,
        department_id=department_id,
        teacher_id=teacher_id,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(access_token=token, user=user)


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/users", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_dept_admin)):
    """Who has access and at what role - every account for the superadmin,
    a department admin's own department otherwise."""
    query = db.query(User).order_by(User.full_name)
    if not is_superadmin(admin):
        query = query.filter(User.department_id == admin.department_id)
    return query.all()


@router.patch("/users/{user_id}/active", response_model=UserResponse)
def set_user_active(
    user_id: int,
    is_active: bool,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    """Revoke or restore login access without deleting the account (and
    its history of who-changed-what)."""
    if user_id == admin.id and not is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or (not is_superadmin(admin) and user.department_id != admin.department_id):
        raise HTTPException(status_code=404, detail="User not found")
    if user.role not in GRANTABLE_ROLES[admin.role]:
        raise HTTPException(status_code=403, detail=f"You can't change {user.role} accounts")
    user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user
