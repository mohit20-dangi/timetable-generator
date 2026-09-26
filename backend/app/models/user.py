from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # ADMIN | HOD | FACULTY | STUDENT
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    teacher_id = Column(String, ForeignKey("teachers.id"), nullable=True)
    section_id = Column(String, ForeignKey("sections.id"), nullable=True)
    is_active = Column(Boolean, default=True)
