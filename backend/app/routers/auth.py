import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pymongo.database import Database
from app.db import get_database
from app.core.config import settings
from app.models import AdminRegister, AdminResponse, Token, InviteResponse
from app.auth.security import hash_password, verify_password, create_access_token
from app.auth.dependencies import get_current_admin

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/invites", response_model=InviteResponse)
def create_invite(
    db: Database = Depends(get_database),
    admin: dict = Depends(get_current_admin),
):
    """Admin-only: mint an invite token that lets one new admin register."""
    invite = {
        "token": secrets.token_urlsafe(24),
        "created_by": admin["username"],
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=settings.INVITE_EXPIRE_HOURS),
        "used": False,
    }
    db.invites.insert_one(invite)
    return invite


@router.post("/register", response_model=AdminResponse)
def register(payload: AdminRegister, db: Database = Depends(get_database)):
    """Create a new admin account, consuming a valid, unused, unexpired invite token."""
    invite = db.invites.find_one({"token": payload.invite_token})
    if not invite:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invite token")
    if invite["used"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite token already used")
    expires_at = invite["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite token has expired")

    if db.admins.find_one({"_id": payload.username}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")

    admin = {
        "_id": payload.username,
        "hashed_password": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc),
    }
    db.admins.insert_one(admin)
    db.invites.update_one({"token": payload.invite_token}, {"$set": {"used": True}})

    return {"username": admin["_id"], "created_at": admin["created_at"]}


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Database = Depends(get_database)):
    admin = db.admins.find_one({"_id": form_data.username})
    if not admin or not verify_password(form_data.password, admin["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": create_access_token(subject=admin["_id"])}


@router.get("/me", response_model=AdminResponse)
def me(admin: dict = Depends(get_current_admin)):
    return admin
