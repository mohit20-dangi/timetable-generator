from sqlalchemy import Column, String, Integer, JSON
from app.db import Base

class Room(Base):
    __tablename__ = "rooms"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # lecture, lab, seminar
    capacity = Column(Integer, default=60)
    equipment = Column(JSON, default=list)
    shared_with_departments = Column(JSON, default=list)
    availability = Column(JSON, default=list)  # [{"day": "Mon", "start": "08:00", "end": "18:00"}]