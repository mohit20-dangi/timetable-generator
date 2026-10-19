from sqlalchemy import Column, Integer, JSON, String, ForeignKey
from app.db import Base


class FirstYearTile(Base):
    """The full class "tile" of one first-year class, as printed on the central
    timetable: what the by-teacher / by-room views draw in the slots that the
    matching Reservation rows lock.

    A Reservation says only "teacher X is busy Mon P4". The tile keeps what a
    person reading a timetable needs to see - which section, which subject and
    batch, who else teaches it, which room - and spans consecutive periods of
    one day. Reservations point back here via `tile_id`; a tile with no
    Reservation left is deleted, so the two never drift apart.
    """
    __tablename__ = "first_year_tiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)
    section = Column(String, nullable=False, default="")        # e.g. "I-A" as printed on the page
    subject = Column(String, nullable=False, default="")        # printed subject code, e.g. "CO34_OS"
    batches = Column(JSON, nullable=False, default=list)        # ["A1", "A2"]
    faculty = Column(JSON, nullable=False, default=list)        # [{"code": "RKD", "name": "Shri Rajesh Dhakad"}]
    room_text = Column(String, nullable=False, default="")      # room exactly as printed
    day = Column(String, nullable=False)
    periods = Column(JSON, nullable=False, default=list)        # our period_index values, ascending
    start = Column(String, nullable=False, default="")          # clock span as printed, "HH:MM"
    end = Column(String, nullable=False, default="")
    source = Column(String, nullable=False, default="first_year_central")
