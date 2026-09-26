from pydantic import BaseModel, EmailStr, model_validator
from typing import Optional

VALID_ROLES = {"ADMIN", "HOD", "FACULTY", "STUDENT"}


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str
    department_id: Optional[str] = None
    teacher_id: Optional[str] = None
    section_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_role(self):
        if self.role not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return self


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    department_id: Optional[str] = None
    teacher_id: Optional[str] = None
    section_id: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
