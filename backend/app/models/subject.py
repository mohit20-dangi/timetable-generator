from sqlalchemy import Column, String, Integer, Boolean, JSON
from app.db import Base

class Subject(Base):
    __tablename__ = "subjects"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # theory, lab, tutorial
    weekly_hours = Column(Integer, default=0)
    needs_continuous_block = Column(Boolean, default=False)
    block_size = Column(Integer, default=1)
    requires_room_type = Column(String, nullable=True)  # lecture, lab, seminar
    requires_equipment = Column(JSON, default=list)