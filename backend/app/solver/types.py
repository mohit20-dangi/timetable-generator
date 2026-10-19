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
    # Phase 3.1: how many DISTINCT eligible teachers this one session needs
    # at the same time (Subject.teachers_required). 1 for everything that
    # isn't a co-supervised lab.
    teachers_required: int = 1
    # Phase 3.1: the LabRotationGroup this demand belongs to, if any. A
    # rotation member is scheduled by the rotation block in model_builder
    # (shared round start slots, one subject per batch per round) and is
    # deliberately EXEMPT from batch_mode, which can only ever talk about
    # one subject's own batches.
    rotation_group_id: Optional[str] = None
    # Extra sections whose students sit in this class without owning it: a
    # repeater section attending its host section's class, or the sections a
    # remedial group draws its students from. They are never given a persisted
    # entry of their own, but the class must not overlap anything they attend.
    attending_section_ids: List[str] = field(default_factory=list)
    # A self-study block (an NPTEL elective): holds the section for one
    # period at the very start or end of a day, with no teacher and no room.
    self_study: bool = False
    # Teachers (a subset of eligible_teacher_ids) who may run the session;
    # the rest of the eligible teachers only assist. Empty = no distinction.
    main_teacher_ids: List[str] = field(default_factory=list)


@dataclass
class RotationGroup:
    """A set of lab subjects one section runs as a rotation (see
    app/models/lab_rotation_group.py). Every (subject, session_index) pair
    in the group is one "activity"; the group runs in as many equal-length
    rounds as there are activities, and in each round every batch is in a
    different activity. That is what makes a rotation cheap in staff: the
    group may hold three 3-batch labs and still only ever need ONE teacher
    per subject at a time, where three parallel batches of a single lab
    would need three.

    `allowed_start_slot_indices` is None for "anywhere a session fits", or
    the slot indices of the admin's pinned window (e.g. Monday 14:00-16:00).
    """
    id: str
    label: str
    section_id: str
    subject_ids: List[str]
    allowed_start_slot_indices: Optional[set] = None


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
    """One `priority="soft"` "section unavailable" ConstraintRule (see Phase
    1.4): a preference that a section NOT be scheduled in `slot_indices`,
    contributing `weight` to the objective per period placed there instead
    of forbidding it outright the way a hard rule would. (Teacher and room
    unavailability are always hard, so they never become one of these.)"""
    scope: str  # section
    resource_id: str
    slot_indices: set = field(default_factory=set)
    weight: int = 0


@dataclass
class CustomRule:
    """One admin-defined preference (a ConstraintRule whose rule_type is a
    template in app/solver/custom_rules.py), already resolved to solver
    terms - slot indices, not day/time strings."""
    kind: str  # subject_time_window | max_subjects_per_day | teacher_max_days_per_week
    hard: bool
    weight: int  # penalty per violation; only used when hard is False
    target_id: str  # subject / section ("*" = every section) / teacher id
    slot_indices: set = field(default_factory=set)  # subject_time_window only
    mode: str = "within"  # subject_time_window: within | avoid
    limit: int = 0  # max_subjects_per_day / teacher_max_days_per_week
    label: str = ""  # shown in error messages


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
    custom_rules: List[CustomRule] = field(default_factory=list)
    # Admin-typed numbers for the priorities that take one (see
    # app/solver/weights.py::RULE_PARAM_DEFAULTS), already sanitised.
    rule_params: Dict[str, int] = field(default_factory=lambda: {
        "max_consecutive_teaching": 2, "max_teacher_periods_per_day": 4,
    })
    # section_id -> slot indices that section is already committed to by a
    # timetable outside this solve (a published host class a repeater attends,
    # or the published main timetable a remedial run is built around). Any
    # attending demand must avoid them; the validator rechecks it.
    section_busy_slot_indices: Dict[str, set] = field(default_factory=dict)
    rotation_groups: List[RotationGroup] = field(default_factory=list)


@dataclass
class ScheduledSession:
    demand_id: str
    subject_id: str
    audience_type: str
    audience_id: str
    parent_section_id: str
    start_slot_index: int
    duration: int
    room_id: Optional[str]
    teacher_id: Optional[str]
    # Teachers beyond the first, when the subject needs several at once.
    # teacher_id is always teacher_ids[0]; use `teacher_ids` for anything
    # that counts load or looks for clashes.
    co_teacher_ids: List[str] = field(default_factory=list)

    @property
    def teacher_ids(self) -> List[str]:
        return [t for t in (self.teacher_id, *self.co_teacher_ids) if t]


@dataclass
class SolveResult:
    status: str  # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN | MODEL_INVALID
    objective_value: Optional[float]
    sessions: List[ScheduledSession]
    wall_time_seconds: float
    diagnostics: Optional[Dict[str, Any]] = None
