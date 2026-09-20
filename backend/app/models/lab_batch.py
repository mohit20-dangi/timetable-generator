from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class LabBatch(Base):
    """A section split into a smaller group for a practical session. A lab
    subject is only actually schedulable once a section has at least one
    batch - see diagnose_infeasibility, which flags this explicitly."""
    __tablename__ = "lab_batches"

    id = Column(String, primary_key=True, index=True)
    section_id = Column(String, ForeignKey("sections.id"), nullable=False)
    batch_name = Column(String, nullable=False)
    strength = Column(Integer, default=30)

    section = relationship("Section", backref="lab_batches")
