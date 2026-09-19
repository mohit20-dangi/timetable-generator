from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class AdminRegister(BaseModel):
    invite_token: str
    username: str
    password: str


class AdminResponse(BaseModel):
    username: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class InviteCreate(BaseModel):
    pass


class InviteResponse(BaseModel):
    token: str
    created_by: str
    expires_at: datetime
    used: bool
