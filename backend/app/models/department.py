from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class Department(Base):
    """A department (CSE, ECE, ...). The solver always solves one
    department at a time - see app/solver/README for why: departments have
    separate students, faculty pools and rooms, so there is no combinatorial
    benefit to solving them jointly. Cross-department sharing (a Maths
    professor teaching CSE, a shared central lab) is handled by freezing the
    other department's confirmed bookings as Reservations before this
    department solves, not by modelling every department in one CP-SAT model.
    """
    __tablename__ = "departments"

    id = Column(String, primary_key=True, index=True)
    # Departments used to hang off an institution; that level was removed
    # from the product. The column stays (nullable) so existing databases
    # keep working without a table rebuild.
    institution_id = Column(String, ForeignKey("institutions.id"), nullable=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=True)

    institution = relationship("Institution", backref="departments")
