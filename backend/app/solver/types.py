"""Plain-Python data shapes for the solver. Deliberately independent of
SQLAlchemy: every solver unit test builds a ProblemData by hand (or with
Hypothesis) and never touches a database. app/solver/data_loader.py is the
only place that converts ORM rows into these shapes.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass(frozen=True)
class Slot:
    """One bell-schedule period, with a stable integer index used
    everywhere else in the solver. `index` is assigned by
    build_slot_calendar in day-major, then period-major order."""
    index: int
    day: str
    period_index: int
    start_minutes: int  # minutes since midnight, for lunch/window overlap checks
    end_minutes: int


@dataclass
class RoomInfo:
    id: str
    type: str
    capacity: int
    equipment: List[str] = field(default_factory=list)
    # Slot indices this room is NOT available at (outside its availability
    # windows). Precomputed once by data_loader so the solver never parses
    # time strings mid-build.
    unavailable_slot_indices: set = field(default_factory=set)


@dataclass
class TeacherInfo:
    id: str
    max_continuous_classes: int = 3
    max_daily_classes: int = 6
    max_weekly_hours: int = 24
    unavailable_slot_indices: set = field(default_factory=set)
    preferred_slot_indices: set = field(default_factory=set)


@dataclass
class SessionDemand:
    """One class that needs a (start slot, room, teacher). A subject with
    sessions_per_week=4 and periods_per_session=1 produces four of these; a
    lab with sessions_per_week=1 and periods_per_session=2 produces one,
    with duration=2. When back_to_back=False splits a session across
    non-contiguous single periods, the resulting demands share
    (subject_id, audience_id, session_index) but not `id` - model_builder
    uses that shared key to add a soft same-day preference between them
    (Phase 2.4).
    """
    id: str  # stable id: f"{subject_id}:{audience_id}:{session_index}[:{part}]"
    subject_id: str
    subject_name: str
    kind: str  # theory | lab | tutorial | ... (a subject_types catalog id)
    audience_type: str  # section | batch
    audience_id: str
    parent_section_id: str  # the section itself, even for batch-level demands
    session_index: int  # 0-based index among this subject+audience's sessions this week
    duration: int  # in periods
    room_type: Optional[str]
    equipment: List[str]
    eligible_room_ids: List[str]
    eligible_teacher_ids: List[str]
    valid_start_slot_indices: List[int]
    max_per_day: int
    elective_group_id: Optional[str] = None
    # Phase 2.9: how sibling lab-batch demands sharing (subject_id,
    # parent_section_id, session_index) relate to each other in time/space.
    #   independent - no hard link; only the soft "parallel_lab_batches"
    #     nudge (if weighted) pulls them toward the same start.
    #   parallel  - same start slot, hard; rooms and teachers stay
    #     independent per batch (separate rooms, can be separate teachers).
    #   sequential - hard: batches may never overlap in time (forced apart).
    #   merged - hard: same start slot AND same room AND same teacher -
    #     the batches are physically taught as one combined class. Only
    #     valid when a single room's capacity covers every batch's
    #     combined strength (data_loader filters eligible_room_ids
    #     accordingly before this ever reaches the model).
    batch_mode: str = "independent"


@dataclass
class FixedBooking:
    """A reservation: a resource already committed at a specific slot by
    some other run/department, which the new solve must never touch."""
    resource_type: str  # teacher | room
    resource_id: str
    start_slot_index: int
    duration: int = 1
    reason: str = ""


@dataclass
class SoftAvoidRule:
    """One `priority="soft"` ConstraintRule (see Phase 1.4): a preference
    that a teacher/room/section NOT be scheduled in `slot_indices`,
    contributing `weight` to the objective per period placed there instead
    of forbidding it outright the way a hard rule would."""
    scope: str  # teacher | room | section
    resource_id: str
    slot_indices: set = field(default_factory=set)
    weight: int = 0


@dataclass
class ProblemData:
    slots: List[Slot]
    rooms: Dict[str, RoomInfo]
    teachers: Dict[str, TeacherInfo]
    demands: List[SessionDemand]
    fixed_bookings: List[FixedBooking] = field(default_factory=list)
    soft_weights: Dict[str, int] = field(default_factory=dict)
    # section_id -> (lunch_start_minutes, lunch_end_minutes). Carried
    # through explicitly (rather than only baked into valid-start domains)
    # so the independent validator can recheck lunch overlap itself,
    # without trusting that the model builder's domain restriction worked.
    lunch_windows: Dict[str, Any] = field(default_factory=dict)
    # Soft-rule keys (see app/solver/weights.py::SOFT_RULE_KEYS) the admin
    # marked "must_have" that this problem promotes to a hard constraint
    # instead of a heavily-weighted objective term (Phase 1.5). Only keys
    # model_builder actually knows how to promote belong here.
    must_have_rules: set = field(default_factory=set)
    soft_avoid_rules: List[SoftAvoidRule] = field(default_factory=list)


@dataclass
class ScheduledSession:
    demand_id: str
    subject_id: str
    audience_type: str
    audience_id: str
    parent_section_id: str
    start_slot_index: int
    duration: int
    room_id: str
    teacher_id: str


@dataclass
class SolveResult:
    status: str  # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN | MODEL_INVALID
    objective_value: Optional[float]
    sessions: List[ScheduledSession]
    wall_time_seconds: float
    diagnostics: Optional[Dict[str, Any]] = None
