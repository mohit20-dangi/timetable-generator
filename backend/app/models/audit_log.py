from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db import Base


class AuditLog(Base):
    """Who changed what, when, and why - CLAUDE.md requires an audit trail.
    Written by both manual edits and the AI agent's applied tool calls."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)  # e.g. "update_teacher_limits", "edit_entry"
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    reason = Column(String, nullable=True)  # e.g. the NL prompt that caused an AI edit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
