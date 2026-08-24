from sqlalchemy import Column, String, ForeignKey, PrimaryKeyConstraint
from app.db import Base

class Prerequisite(Base):
    __tablename__ = "prerequisites"
    
    subject_id = Column(String, ForeignKey("subjects.id"), nullable=False)
    requires_subject_id = Column(String, ForeignKey("subjects.id"), nullable=False)
    
    __table_args__ = (PrimaryKeyConstraint("subject_id", "requires_subject_id"),)