from sqlalchemy import Column, String, JSON, ForeignKey
from app.db import Base


class ConstraintProfile(Base):
    """Soft-constraint weights, expressed to admins as plain-language
    importance levels (must_have / very_important / nice_to_have /
    dont_care) and translated to solver weights at generation time - see
    app/solver/weights.py. Never shown to admins as a raw number."""
    __tablename__ = "constraint_profiles"

    id = Column(String, primary_key=True, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    name = Column(String, nullable=False)
    soft_constraint_weights = Column(JSON, default=dict)
    # Numbers typed next to the rules that take one, e.g.
    # {"max_consecutive_teaching": 2} - see weights.RULE_PARAM_DEFAULTS.
    # NULL (a profile saved before this column existed) means all defaults.
    rule_params = Column(JSON, default=dict, nullable=True)
