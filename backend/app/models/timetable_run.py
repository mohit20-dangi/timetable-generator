from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db import Base

class TimetableRun(Base):
    __tablename__ = "timetable_runs"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    constraint_profile_id = Column(String, ForeignKey("constraint_profiles.id"), nullable=True)
    status = Column(String, default="pending")  # pending, solving, completed, failed
    solver_output = Column(JSON, nullable=True)
    llm_explanation = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    constraint_profile = relationship("ConstraintProfile")