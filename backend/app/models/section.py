from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base

class Section(Base):
    __tablename__ = "sections"
    
    id = Column(String, primary_key=True, index=True)
    year_id = Column(String, ForeignKey("academic_years.id"), nullable=False)
    name = Column(String, nullable=False)
    strength = Column(Integer, default=60)
    
    year = relationship("AcademicYear", backref="sections")