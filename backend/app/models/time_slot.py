from sqlalchemy import Column, String, Integer, Time, ForeignKey
from app.db import Base


class TimeSlot(Base):
    """A department's bell schedule. Each department keeps its own periods;
    rows with no department are the schedule from before departments were
    separated, used only by a department that hasn't set up its own yet -
    see app/services/department_calendar.py."""
    __tablename__ = "time_slots"

    id = Column(String, primary_key=True, index=True)
    day = Column(String, nullable=False)  # Mon..Sat (Sun intentionally excluded by default)
    period_index = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    # regular: part of the main timetable's bell schedule. remedial: only the
    # remedial-class solve may use it (after-hours periods, a free Saturday),
    # so the regular solver never schedules into it.
    slot_kind = Column(String, nullable=False, default="regular")
