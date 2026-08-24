from sqlalchemy import Column, String, Integer, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base

class Teacher(Base):
    __tablename__ = "teachers"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    department = Column(String, nullable=True)
    max_continuous_classes = Column(Integer, default=3)
    max_daily_classes = Column(Integer, default=5)
    availability = Column(JSON, default=list)  # [{"day": "Mon", "start": "09:00", "end": "16:00"}]
    preferred_slots = Column(JSON, default=list)  # [{"day": "Mon", "slots": [{"start": "09:00", "end": "11:00"}, {"start": "13:00", "end": "15:00"}]}]
    is_guest_from_other_dept = Column(Boolean, default=False)