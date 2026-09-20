from sqlalchemy import Column, String, Integer, Boolean, JSON, ForeignKey
from app.db import Base


class Subject(Base):
    """The schedulable unit. A curriculum row with both lecture and
    tutorial hours (e.g. L=3,T=1) becomes TWO Subject rows - one
    type='theory', one type='tutorial' - sharing `linked_group_id` so the
    "keep related sessions near each other" soft constraint and reporting
    can still treat them as one course. This is simpler to implement and
    test correctly than a live multi-level Scheme/Component join, while
    still fixing the original problem: neither L nor T can be silently
    dropped, because each is its own row with its own weekly_hours.

    category: BSC | HSMC | PCC | PEC | MOEC | PCC-LC | MC | INT | PR | ...
      (straight from the scheme document; drives reporting/credits only)
    delivery_mode: IN_PERSON | MOOC_NPTEL | SELF_STUDY | INDUSTRY
      (drives whether this subject consumes a timetable slot at all)
    scheme_hours_per_week: the document's Hours/Week figure - feeds
      credits/marks/transcripts. NEVER used for scheduling directly.
    contact_hours_per_week: the actual hours that need a teacher+room this
      term. Defaults to scheme_hours_per_week for IN_PERSON subjects, but
      is explicitly overridable (e.g. a 20 hr/week internship might have a
      1 hr/week faculty review session).
    """
    __tablename__ = "subjects"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # theory, lab, tutorial
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    category = Column(String, nullable=True)
    delivery_mode = Column(String, default="IN_PERSON")

    scheme_hours_per_week = Column(Integer, nullable=True)
    weekly_hours = Column(Integer, default=0)  # == contact_hours_per_week; kept as
    # `weekly_hours` for backward compatibility with the existing frontend/import
    # schema. Treated as the authoritative "hours that need scheduling" value.

    needs_continuous_block = Column(Boolean, default=False)
    block_size = Column(Integer, default=1)
    max_per_day = Column(Integer, default=1)  # hard cap: same subject at most N times/day
    requires_room_type = Column(String, nullable=True)  # lecture, lab, seminar
    requires_equipment = Column(JSON, default=list)

    linked_group_id = Column(String, nullable=True)  # ties L/T/P siblings of one curriculum row
    elective_group_id = Column(String, ForeignKey("elective_groups.id"), nullable=True)

    @property
    def is_schedulable(self) -> bool:
        """MOOC_NPTEL and INDUSTRY deliveries are examined/run by an outside
        body and never occupy a college room or teacher. SELF_STUDY may
        optionally reserve a block but contends for nothing. Only
        IN_PERSON (and a SELF_STUDY subject that opts into a reserved
        block) ever reaches the solver as real demand."""
        return self.delivery_mode == "IN_PERSON"
