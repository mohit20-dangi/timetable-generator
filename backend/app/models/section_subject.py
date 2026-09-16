from sqlalchemy import Column, String, ForeignKey, Boolean, PrimaryKeyConstraint
from app.db import Base

class SectionSubject(Base):
    __tablename__ = "section_subjects"
    
    section_id = Column(String, ForeignKey("sections.id"), nullable=False)
    subject_id = Column(String, ForeignKey("subjects.id"), nullable=False)
    is_elective = Column(Boolean, default=False)
    elective_group_id = Column(String, nullable=True)
    
    __table_args__ = (PrimaryKeyConstraint("section_id", "subject_id"),)