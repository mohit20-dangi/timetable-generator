from sqlalchemy import Column, String, Time, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class LabRotationGroup(Base):
    """A set of lab subjects one section runs AS A ROTATION: in each round
    every batch is in a different one of the group's labs, and in the next
    round they swap, until every batch has done every lab.

    This is the thing `batch_scheduling_mode` could never express.
    `batch_scheduling_mode` only ever describes how the batches of ONE
    subject relate to each other, so "run the labs together" could only
    mean "parallel", i.e. all three batches in the SAME lab at the same
    time - which needs one qualified teacher per batch and is exactly the
    "3 batches, only 2 teachers" wall admins kept hitting. A rotation runs
    the same three batches at the same time in THREE DIFFERENT labs, so
    each subject only ever needs ONE teacher at a time.

    Concretely, for "Monday 14:00-16:00, SEC3A: A1 does CN Lab, A2 does
    DBMS Lab, A3 does OOPS Lab":
        section_id = SEC3A
        subject_ids = [CN_LAB, DBMS_LAB, OOPS_LAB]
        day/start_time/end_time = Mon / 14:00 / 16:00  (optional - with no
          window the solver places the rounds wherever they fit best; with
          one, every round must sit inside it)

    The rounds themselves are solver-assigned (see model_builder's rotation
    block): which batch gets which lab in which round is a Latin square the
    solver fills in, not something the admin spells out batch by batch.
    """
    __tablename__ = "lab_rotation_groups"

    id = Column(String, primary_key=True, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False)
    section_id = Column(String, ForeignKey("sections.id"), nullable=False)
    name = Column(String, nullable=False)
    # Subject ids in the rotation. Every one must be a lab subject of this
    # section, and they must agree on periods_per_session - a round is one
    # shared block of time, so a 2-period lab cannot rotate with a 3-period
    # one. data_loader warns and skips the group rather than guessing.
    subject_ids = Column(JSON, default=list)
    day = Column(String, nullable=True)          # Mon..Sun; null = any day
    start_time = Column(Time, nullable=True)     # null = anywhere in the day
    end_time = Column(Time, nullable=True)
    source = Column(String, default="manual")    # manual | ai_parsed
    raw_instruction = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    department = relationship("Department", backref="lab_rotation_groups")
    section = relationship("Section", backref="lab_rotation_groups")
