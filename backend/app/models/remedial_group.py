from sqlalchemy import Column, String, Integer, Boolean, JSON, ForeignKey
from app.db import Base


class RemedialGroup(Base):
    """A set of low-attendance students who need extra classes in one
    subject. Students are not tracked individually: the admin names the
    sections the students come from (usually one; several when the group is
    combined) and how many of them there are, and the remedial solve keeps
    every one of those sections free of clashes."""
    __tablename__ = "remedial_groups"

    id = Column(String, primary_key=True, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False)
    name = Column(String, nullable=False)
    subject_id = Column(String, ForeignKey("subjects.id"), nullable=False)
    section_ids = Column(JSON, nullable=False)  # sections the students come from
    strength = Column(Integer, nullable=False)  # students in the group (combined)
    # The admin's weightage for the subject: remedial periods per week.
    periods_per_week = Column(Integer, nullable=False, default=1)
    periods_per_session = Column(Integer, nullable=False, default=1)
    # Pin one teacher; otherwise the subject's regular teacher is preferred.
    teacher_id = Column(String, ForeignKey("teachers.id"), nullable=True)
    # Restrict to certain days (e.g. ["Sat"]); null means any day.
    allowed_days = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
