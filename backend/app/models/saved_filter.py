from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, ForeignKey, JSON, DateTime
from app.db import Base


class SavedFilter(Base):
    """A reusable Custom Filter view (see app/schemas/custom_filter.py::FilterSpec).

    Stored as the structured spec, never as the LLM's raw output or any
    code: re-running a saved filter is a plain deterministic evaluation with
    no model call. That is the whole point - once a teacher's recurring
    question ("free slots + a seminar hall") is saved, the LLM isn't needed
    for it again.

    department_id NULL means visible to everyone; otherwise only to that
    department's users (and ADMINs).
    """
    __tablename__ = "saved_filters"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    original_query = Column(String, nullable=True)
    spec = Column(JSON, nullable=False)
    department_id = Column(String, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
