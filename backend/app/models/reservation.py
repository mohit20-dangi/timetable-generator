from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


# Reservation.source value for rows imported from the central first-year PDF.
FIRST_YEAR_SOURCE = "first_year_central"


class Reservation(Base):
    """A frozen booking a NEW solve must treat as hard unavailability.

    This is the single mechanism behind two different-sounding
    requirements:
      1. "Fit into the existing timetable" scope mode - other years/
         sections already published stay frozen while a new scope is
         (re)generated.
      2. Cross-department sharing - a Maths professor's CSE-department
         hours are frozen before the Maths department (or another
         department sharing that professor) solves its own timetable.

    One row = one resource (teacher or room) is busy at one day/period,
    because some other already-committed run put it there.
    """
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False)
    resource_type = Column(String, nullable=False)  # teacher | room
    resource_id = Column(String, nullable=False)
    day = Column(String, nullable=False)
    period = Column(Integer, nullable=False)
    source_run_id = Column(Integer, ForeignKey("timetable_runs.id", ondelete="SET NULL"), nullable=True)
    reason = Column(String, nullable=True)
    # Who created the row. "first_year_central" = imported from the central
    # first-year timetable PDF: always applied (even to a fresh run) and
    # replaced wholesale on re-upload. None = created by a run/department.
    source = Column(String, nullable=True)
    # The first-year class tile this lock belongs to (see FirstYearTile), so
    # the by-teacher/by-room views can draw the whole class, not a bare slot.
    tile_id = Column(Integer, ForeignKey("first_year_tiles.id", ondelete="SET NULL"), nullable=True)

    source_run = relationship("TimetableRun", backref="reservations")
