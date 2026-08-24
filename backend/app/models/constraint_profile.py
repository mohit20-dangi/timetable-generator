from sqlalchemy import Column, String, Integer, JSON
from app.db import Base

class ConstraintProfile(Base):
    __tablename__ = "constraint_profiles"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    soft_constraint_weights = Column(JSON, default=dict)