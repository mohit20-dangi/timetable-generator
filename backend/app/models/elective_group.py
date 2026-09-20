from sqlalchemy import Column, String, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class ElectiveGroup(Base):
    """A basket of options (e.g. "Elective-1: 8 options") of which a college
    actually runs only a subset in a given term. The scheme document fixes
    the full basket; `offered_subject_ids` is the admin's choice of which
    ones are actually running - only those are co-scheduled.

    `must_be_parallel=True` means every offered option is placed in the
    SAME timeslot (different rooms/teachers), so a student who picked any
    one option never clashes with their own core subjects. The solver
    enforces this only when the pre-flight room/teacher check (see
    ElectiveGroup.preflight in the constraints router) confirms it's
    actually achievable with the rooms and teachers on hand.
    """
    __tablename__ = "elective_groups"

    id = Column(String, primary_key=True, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False)
    name = Column(String, nullable=False)
    offered_subject_ids = Column(JSON, default=list)
    must_be_parallel = Column(Boolean, default=True)

    department = relationship("Department", backref="elective_groups")
