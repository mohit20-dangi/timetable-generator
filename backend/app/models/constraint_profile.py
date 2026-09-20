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
