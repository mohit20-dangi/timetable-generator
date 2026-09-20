from sqlalchemy import Column, String, Integer, Time
from app.db import Base


class TimeSlot(Base):
    """The institution's bell schedule. Deliberately global rather than
    per-department: in practice one college runs one set of periods, and
    CLAUDE.md says not to add configuration surface until it's needed."""
    __tablename__ = "time_slots"

    id = Column(String, primary_key=True, index=True)
    day = Column(String, nullable=False)  # Mon..Sat (Sun intentionally excluded by default)
    period_index = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
