from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User, Teacher, Section, Department
from app.schemas import UserCreate, UserResponse, LoginRequest, TokenResponse
from app.auth.security import hash_password, verify_password, create_access_token
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/bootstrap-admin", response_model=UserResponse)
def bootstrap_admin(user: UserCreate, db: Session = Depends(get_db)):
    """
    Create the very first ADMIN account. Only works when there are zero
    users in the system. After that, this endpoint always refuses, and
    new users must be created via POST /api/auth/register by an existing admin.
    """
    if db.query(User).count() > 0:
        raise HTTPException(
            status_code=403,
            detail="An admin already exists. Use /api/auth/register (as an admin) to add more users.",
        )
    if user.role != "ADMIN":
        raise HTTPException(status_code=400, detail="First bootstrapped user must have role=ADMIN")

    db_user = User(
        email=user.email,
        hashed_password=hash_password(user.password),
        full_name=user.full_name,
        role="ADMIN",
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/register", response_model=UserResponse)
def register(
    user: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Create a new user account. Admin-only."""
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    if user.role not in ("ADMIN", "HOD", "FACULTY", "STUDENT"):
        raise HTTPException(status_code=400, detail="role must be ADMIN, HOD, FACULTY, or STUDENT")

    if user.role == "HOD":
        if not user.department_id or not db.query(Department).filter(Department.id == user.department_id).first():
            raise HTTPException(status_code=400, detail="Valid department_id is required for HOD users")

    if user.role == "FACULTY":
        if not user.teacher_id or not db.query(Teacher).filter(Teacher.id == user.teacher_id).first():
            raise HTTPException(status_code=400, detail="Valid teacher_id is required for FACULTY users")

    if user.role == "STUDENT":
        if not user.section_id or not db.query(Section).filter(Section.id == user.section_id).first():
            raise HTTPException(status_code=400, detail="Valid section_id is required for STUDENT users")

    db_user = User(
        email=user.email,
        hashed_password=hash_password(user.password),
        full_name=user.full_name,
        role=user.role,
        department_id=user.department_id if user.role == "HOD" else None,
        teacher_id=user.teacher_id if user.role == "FACULTY" else None,
        section_id=user.section_id if user.role == "STUDENT" else None,
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
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Admin-only roster of every account, so an admin can see who has
    access and at what role before handing out or revoking permissions."""
    return db.query(User).order_by(User.full_name).all()


@router.patch("/users/{user_id}/active", response_model=UserResponse)
def set_user_active(
    user_id: int,
    is_active: bool,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Revoke or restore login access without deleting the account (and
    its history of who-changed-what)."""
    if user_id == admin.id and not is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user
