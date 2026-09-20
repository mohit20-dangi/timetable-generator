from sqlalchemy import Column, String, ForeignKey, PrimaryKeyConstraint
from app.db import Base


class TeacherSubject(Base):
    """Qualifies a teacher to teach a subject. A subject with N simultaneous
    lab batches needs at least N eligible teachers here, or generation
    correctly reports infeasible - see seed_example.py's comment on this."""
    __tablename__ = "teacher_subjects"

    teacher_id = Column(String, ForeignKey("teachers.id"), nullable=False)
    subject_id = Column(String, ForeignKey("subjects.id"), nullable=False)

    __table_args__ = (PrimaryKeyConstraint("teacher_id", "subject_id"),)
