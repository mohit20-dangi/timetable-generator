from sqlalchemy import Column, String, Integer, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db import Base

class GeneratedEntry(Base):
    __tablename__ = "generated_entries"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timetable_run_id = Column(Integer, ForeignKey("timetable_runs.id"), nullable=False)
    day = Column(String, nullable=False)
    period = Column(Integer, nullable=False)
    section_id = Column(String, ForeignKey("sections.id"), nullable=True)
    batch_id = Column(String, ForeignKey("lab_batches.id"), nullable=True)
    subject_id = Column(String, ForeignKey("subjects.id"), nullable=False)
    teacher_id = Column(String, ForeignKey("teachers.id"), nullable=False)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    
    timetable_run = relationship("TimetableRun", backref="entries")
    section = relationship("Section")
    batch = relationship("LabBatch")
    subject = relationship("Subject")
    teacher = relationship("Teacher")
    room = relationship("Room")