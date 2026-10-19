from sqlalchemy import Column, String, ForeignKey, Boolean, PrimaryKeyConstraint
from app.db import Base


class SectionSubject(Base):
    __tablename__ = "section_subjects"

    section_id = Column(String, ForeignKey("sections.id"), nullable=False)
    subject_id = Column(String, ForeignKey("subjects.id"), nullable=False)
    is_elective = Column(Boolean, default=False)
    elective_group_id = Column(String, ForeignKey("elective_groups.id"), nullable=True)
    # A repeater section takes this subject by sitting in another section's
    # class instead of having one of its own: set to the host section (and,
    # for a lab, the host's batch). The solver then schedules no class for
    # this row; the host's class simply must not clash with anything this
    # section attends. See app/services/section_attendance.py.
    attends_with_section_id = Column(String, ForeignKey("sections.id"), nullable=True)
    attends_with_batch_id = Column(String, ForeignKey("lab_batches.id"), nullable=True)

    __table_args__ = (PrimaryKeyConstraint("section_id", "subject_id"),)
