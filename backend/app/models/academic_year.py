from sqlalchemy import Column, Integer, String, Time
from app.db import Base

class AcademicYear(Base):
    __tablename__ = "academic_years"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    num_sections = Column(Integer, default=1)
    lunch_start = Column(Time, nullable=True)
    lunch_end = Column(Time, nullable=True)