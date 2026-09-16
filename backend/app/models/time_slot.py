from sqlalchemy import Column, String, Integer, Time
from app.db import Base

class TimeSlot(Base):
    __tablename__ = "time_slots"
    
    id = Column(String, primary_key=True, index=True)
    day = Column(String, nullable=False)  # Mon, Tue, Wed, Thu, Fri, Sat, Sun
    period_index = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
