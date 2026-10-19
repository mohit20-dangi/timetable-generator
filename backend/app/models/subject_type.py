from sqlalchemy import Column, String, Integer, Boolean, ForeignKey
from app.db import Base


class SubjectType(Base):
    """The catalog Subject.type points into. Seeded with the three types the
    app previously hardcoded (theory/lab/tutorial) - see
    SQLITE_STARTUP_SEEDS in app/main.py - but an admin can add more
    (seminar, project, internship, workshop) without a code change."""
    __tablename__ = "subject_types"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    default_block_size = Column(Integer, default=1)
    default_room_type = Column(String, nullable=True)  # lecture, lab, seminar
    colour_hex = Column(String, nullable=False, default="E5E7EB")
    is_builtin = Column(Boolean, default=False)
    # Built-in types are shared by every department (every subject depends
    # on them); a type an admin adds belongs to their department only.
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
