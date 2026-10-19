from sqlalchemy import Column, Integer, String, JSON, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base


class RemedialRun(Base):
    """One generation of the remedial timetable. Kept apart from
    TimetableRun/GeneratedEntry on purpose: remedial classes are built AROUND
    the published main timetable, never part of it, so they must not leak into
    the main timetable's frozen bookings or public view."""
    __tablename__ = "remedial_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False)
    status = Column(String, default="pending")  # pending | solving | completed | failed
    settings = Column(JSON, nullable=True)  # the admin's constraints for this run
    solver_output = Column(JSON, nullable=True)  # warnings + diagnostics
    explanation = Column(String, nullable=True)  # why a run failed, in plain language
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    is_published = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    entries = relationship("RemedialEntry", back_populates="run", cascade="all, delete-orphan")


class RemedialEntry(Base):
    """One period of a scheduled remedial class (a block shares a session_group)."""
    __tablename__ = "remedial_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    remedial_run_id = Column(Integer, ForeignKey("remedial_runs.id", ondelete="CASCADE"), nullable=False)
    session_group = Column(String, nullable=True, index=True)
    day = Column(String, nullable=False)
    period = Column(Integer, nullable=False)
    group_id = Column(String, ForeignKey("remedial_groups.id", ondelete="SET NULL"), nullable=True)
    subject_id = Column(String, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    teacher_id = Column(String, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    room_id = Column(String, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    # True when the period is one of the department's remedial-only slots
    # (after hours / free day) rather than a gap in the main timetable.
    in_remedial_slot = Column(Boolean, default=False)

    run = relationship("RemedialRun", back_populates="entries")
