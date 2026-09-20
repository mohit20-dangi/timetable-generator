from sqlalchemy import Column, String, Integer, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    max_continuous_classes = Column(Integer, default=3)
    max_daily_classes = Column(Integer, default=6)
    max_weekly_hours = Column(Integer, default=24)  # CLAUDE.md: max 24 hrs/week teaching
    # [{"day": "Mon", "start": "08:00", "end": "18:00"}] - windows the
    # teacher IS available; absence of a day means unavailable all day.
    availability = Column(JSON, default=list)
    # [{"day": "Mon", "slots": [{"start": "09:00", "end": "11:00"}]}] - a
    # soft preference, not a hard cap like `availability`.
    preferred_slots = Column(JSON, default=list)
    is_guest_from_other_dept = Column(Boolean, default=False)

    department = relationship("Department", backref="teachers")
