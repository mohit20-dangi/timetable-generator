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
    weekly_hours=4 and block_size=1 produces four of these; a lab with
    weekly_hours=2 and block_size=2 produces one, with duration=2.
    """
    id: str  # stable id: f"{subject_id}:{audience_id}:{session_index}"
    subject_id: str
    subject_name: str
    kind: str  # theory | lab | tutorial
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
