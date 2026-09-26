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
    lecture_hours/tutorial_hours/practical_hours: the scheme table's L, T, P
      hours/week for what became THIS Subject row (e.g. the theory sibling
      of an L=3,T=1 pair carries lecture_hours=3, tutorial_hours=0). Feeds
      `weekly_hours` by default - see SubjectBase's derivation in
      app/schemas/subject.py (Phase 2.3) - but weekly_hours can be
      overridden directly (e.g. a 0-0-0 internship that still needs a
      1 hr/week faculty review session).
    scheme_hours_per_week: the document's Hours/Week figure - feeds
      credits/marks/transcripts. NEVER used for scheduling directly.
    weekly_hours: == contact_hours_per_week, the actual hours that need a
      teacher+room this term. Defaults to lecture_hours+tutorial_hours+
      practical_hours for IN_PERSON subjects, 0 otherwise, but is always
      explicitly overridable.
    sessions_per_week/periods_per_session: how the weekly_hours are chunked
      into meetings - e.g. a 4-hour/week lab might be 2 sessions of 2
      periods each, while a 4-hour/week theory subject is 4 sessions of 1
      period each. Replaces the old block_size/needs_continuous_block pair
      (Phase 2.4), which conflated "how many periods per meeting" with "do
      they have to be contiguous" into an unenforced checkbox.
    back_to_back: whether periods_per_session must be one contiguous block
      (the normal case for a lab) or may be scheduled as separate
      single-period sessions on possibly-different days (rare, but real for
      some tutorial-heavy subjects).
    batch_scheduling_mode: how this subject's lab batches relate to each
      other in time/space (Phase 2.9). One of:
        independent (default) - no hard link between sibling batches;
          only the soft "parallel_lab_batches" preference nudges them.
        parallel - hard: every batch's session is forced into the SAME
          start slot, in separate rooms (and usually separate teachers).
        sequential - hard: sibling batches may never overlap in time.
        merged - hard: sibling batches share the SAME start, room AND
          teacher - taught as one combined class. Requires a room whose
          capacity covers every batch's combined strength; see the
          lab-batches preflight check.
      A ConstraintRule of rule_type="batch_scheduling_mode" can override
      this per-subject, globally or restricted to a specific day/time
      window (e.g. "only merge them Tuesday 10-12, when the one teacher
      qualified for this subject is free").
    """
    __tablename__ = "subjects"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    # Short printed code for the PDF/Excel exports (e.g. "CO4_PDQA") -
    # Phase 4.1. Derived from the id/name on create when not given
    # explicitly, but always overridable.
    code = Column(String, nullable=True)
    type = Column(String, nullable=False)  # references subject_types.id
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    category = Column(String, nullable=True)
    delivery_mode = Column(String, default="IN_PERSON")

    lecture_hours = Column(Integer, default=0)
    tutorial_hours = Column(Integer, default=0)
    practical_hours = Column(Integer, default=0)

    scheme_hours_per_week = Column(Integer, nullable=True)
    weekly_hours = Column(Integer, default=0)  # == contact_hours_per_week; kept as
    # `weekly_hours` for backward compatibility with the existing frontend/import
    # schema. Treated as the authoritative "hours that need scheduling" value.

    sessions_per_week = Column(Integer, nullable=True)  # null == derive from weekly_hours / periods_per_session
    periods_per_session = Column(Integer, default=1)
    back_to_back = Column(Boolean, default=True)
    batch_scheduling_mode = Column(String, default="independent")  # independent | parallel | sequential | merged

    max_per_day = Column(Integer, default=1)  # hard cap: same subject at most N times/day
    requires_room_type = Column(String, nullable=True)  # lecture, lab, seminar
    requires_equipment = Column(JSON, default=list)  # ids into the equipment catalog

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
