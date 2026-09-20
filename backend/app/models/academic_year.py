from sqlalchemy import Column, Integer, String, Time, ForeignKey
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
    lunch_start = Column(Time, nullable=True)
    lunch_end = Column(Time, nullable=True)

    department = relationship("Department", backref="academic_years")
