from sqlalchemy import Column, String, Time, Boolean, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class ConstraintRule(Base):
    """A single structured rule - the home `structured_constraints` never
    had in the previous build. Produced either by an admin through the UI
    or by the AI agent parsing a natural-language instruction (in which
    case `source='ai_parsed'` and `raw_instruction` keeps the original text
    for audit).

    rule_type: teacher_unavailable | room_unavailable | section_unavailable
             | teacher_preferred | max_daily_override | custom
    target_type: teacher | room | section | subject
    priority: hard | soft
    """
    __tablename__ = "constraint_rules"

    id = Column(String, primary_key=True, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False)
    rule_type = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    day = Column(String, nullable=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    priority = Column(String, default="hard")  # hard | soft
    weight = Column(Integer, default=0)  # used only when priority == soft
    description = Column(String, nullable=True)
    source = Column(String, default="manual")  # manual | ai_parsed
    raw_instruction = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    department = relationship("Department", backref="constraint_rules")
