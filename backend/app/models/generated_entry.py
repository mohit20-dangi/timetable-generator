from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class GeneratedEntry(Base):
    """One scheduled session within a run. `alternative_rank` distinguishes
    the primary schedule (rank 1) from alternates (rank 2..N) generated in
    the same run for side-by-side comparison."""
    __tablename__ = "generated_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timetable_run_id = Column(Integer, ForeignKey("timetable_runs.id"), nullable=False)
    alternative_rank = Column(Integer, default=1)
    # Shared by every period-row belonging to the same scheduled session
    # (a 2-period lab block is 2 rows with the same session_group). Lets an
    # edit move a whole block at once instead of one period at a time, and
    # lets exports merge the rows back into one visual cell.
    session_group = Column(String, nullable=True, index=True)
    day = Column(String, nullable=False)
    period = Column(Integer, nullable=False)
    section_id = Column(String, ForeignKey("sections.id"), nullable=True)
    batch_id = Column(String, ForeignKey("lab_batches.id"), nullable=True)
    subject_id = Column(String, ForeignKey("subjects.id"), nullable=False)
    teacher_id = Column(String, ForeignKey("teachers.id"), nullable=False)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)

    run = relationship("TimetableRun", backref="entries")
