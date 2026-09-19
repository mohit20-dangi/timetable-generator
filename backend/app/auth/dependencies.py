from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pymongo.database import Database
from app.db import get_database
from app.auth.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_admin(
    token: str = Depends(oauth2_scheme),
    db: Database = Depends(get_database),
) -> dict:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise credentials_error

    admin = db.admins.find_one({"_id": payload["sub"]})
    if not admin:
        raise credentials_error

    return {"username": admin["_id"], "created_at": admin.get("created_at")}
