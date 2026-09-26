from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class AcademicYear(Base):
    """A curriculum year-of-study within a department (e.g. "III Year").
    Not a calendar concept - see AcademicTerm for that."""
    __tablename__ = "academic_years"

    id = Column(String, primary_key=True, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    name = Column(String, nullable=False)
    num_sections = Column(Integer, default=1)
    default_section_strength = Column(Integer, default=60)
    # Phase 2.5: lunch is per-day, not one window applied to every day - a
    # real timetable can have a class running through what's normally the
    # lunch slot on one day (e.g. Thursday) while every other day breaks
    # for lunch then. {"Mon": ["12:00", "13:00"], ...}; a day absent from
    # this dict has no lunch break at all.
    lunch_windows = Column(JSON, default=dict)

    department = relationship("Department", backref="academic_years")
