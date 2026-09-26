from sqlalchemy import Column, String
from app.db import Base


class Equipment(Base):
    """The catalog Subject.requires_equipment and Room.equipment pick from.
    Free text on both sides used to be matched by exact string - one typo
    meant zero eligible rooms. `id` is the normalised (lowercased) form so
    a duplicate can't be added under a different case."""
    __tablename__ = "equipment"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
