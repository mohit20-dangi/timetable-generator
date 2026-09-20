from sqlalchemy import Column, Integer, String, JSON, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base


class TimetableRun(Base):
    __tablename__ = "timetable_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    constraint_profile_id = Column(String, ForeignKey("constraint_profiles.id"), nullable=True)
    status = Column(String, default="pending")  # pending | solving | completed | failed
    # fit_into_existing (default, safe): everything outside `year_ids` /
    # `section_ids` is frozen via Reservation rows before solving.
    # fresh: scope solved in isolation, ignoring what else exists - faster,
    # but the caller accepts the risk of clashing with other scopes.
    scope_mode = Column(String, default="fit_into_existing")
    year_ids = Column(JSON, nullable=True)
    section_ids = Column(JSON, nullable=True)
    num_alternatives = Column(Integer, default=1)
    solver_output = Column(JSON, nullable=True)
    llm_explanation = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    is_published = Column(Boolean, default=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    parent_run_id = Column(Integer, ForeignKey("timetable_runs.id"), nullable=True)
    change_summary = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    department = relationship("Department", backref="timetable_runs")
