"""The "scheduling priorities" that shape how a teacher's and a section's
week FEELS (teacher fatigue, repetitive days, morning vs afternoon), as
opposed to the core gap/balance/parallel-batch rules that stay inline in
model_builder._add_soft_objective.

Every rule here is soft: a violation adds `weight * violation` to the
objective (weight comes from the admin's importance level - see
app/solver/weights.py). None of them can make a timetable infeasible, which
is also why "must have" on these stays a very heavy preference rather than
a hard constraint (the teacher's own hard max_continuous/max_daily/max_weekly
caps in model_builder._add_workload_caps are the real limits; the numbers an
admin types in here are the *comfortable* limits below those).

Adding a rule: write a function taking the _Ctx, register its key in RULES
and in weights.py's SOFT_RULE_KEYS/SOFT_RULE_DESCRIPTIONS, and add it to the
frontend's RULE_DEFINITIONS.
"""
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from app.solver.calendar import DAY_ORDER, contiguous_day_runs, occupied_indices

# A teacher's "lighter day" still allows a couple of periods - "few or no
# classes" - so that an overloaded faculty member isn't forced to a fully
# empty day that would push everyone else's load up.
LIGHT_DAY_MAX_PERIODS = 2

# "Core" subjects for heavy_subjects_early. The data model has no
# difficulty/core flag, so a non-lab subject meeting this many times a week
# is treated as core - the courses that get the most contact hours are the
# ones students most need to be fresh for.
HEAVY_SUBJECT_MIN_SESSIONS = 3


class _Ctx:
    """Shared indicator cache, so rules that ask the same question ("is this
    demand on Tuesday?", "is this teacher busy in slot 12?") reuse one
    BoolVar instead of each rule building its own copy."""

    def __init__(self, mv, problem, slots_by_index, membership_indicator, groups, days):
        self.model = mv.model
        self.mv = mv
        self.problem = problem
        self.slots_by_index = slots_by_index
        self.membership_indicator = membership_indicator
        self.groups = groups
        self.days = days
        self.objective_terms = mv.objective_terms
        self._onday: Dict[Tuple[str, str], Optional["cp_model.IntVar"]] = {}
        self._occ: Dict[Tuple[str, int], Optional["cp_model.IntVar"]] = {}
        self._busy: Dict[Tuple[str, int], object] = {}
        self._frozen: Dict[str, set] = {}
        for booking in problem.fixed_bookings:
            if booking.resource_type != "teacher":
                continue
            covered = occupied_indices(booking.start_slot_index, booking.duration, slots_by_index) \
                if booking.start_slot_index in slots_by_index else []
            self._frozen.setdefault(booking.resource_id, set()).update(covered)

    def penalise(self, var, weight: int) -> None:
        self.objective_terms.append((var, weight))

    def onday(self, demand, day):
        key = (demand.id, day)
        if key not in self._onday:
            self._onday[key] = self.membership_indicator(
                self.model, self.mv.start[demand.id], demand.valid_start_slot_indices,
                [i for i in demand.valid_start_slot_indices if self.slots_by_index[i].day == day],
                f"prio_onday_{demand.id}_{day}",
            )
        return self._onday[key]

    def occupies(self, demand, slot_index):
        key = (demand.id, slot_index)
        if key not in self._occ:
            self._occ[key] = self.membership_indicator(
                self.model, self.mv.start[demand.id], demand.valid_start_slot_indices,
                [
                    v for v in demand.valid_start_slot_indices
                    if slot_index in occupied_indices(v, demand.duration, self.slots_by_index)
                ],
                f"prio_occ_{demand.id}_{slot_index}",
            )
        return self._occ[key]

    def any_of(self, indicators: List, name: str):
        """A BoolVar that is 1 iff any indicator is 1 (or plain 0 for an
        empty list, which composes fine inside linear expressions)."""
        indicators = [i for i in indicators if i is not None]
        if not indicators:
            return 0
        if len(indicators) == 1:
            return indicators[0]
        present = self.model.NewBoolVar(name)
        self.model.AddMaxEquality(present, indicators)
        return present

    def teacher_busy(self, teacher_id: str, slot_index: int):
        """1 if the teacher is teaching in this slot. Returns a BoolVar, the
        constant 1 (frozen booking from another run), or None if this
        teacher can never be in this slot."""
        if slot_index in self._frozen.get(teacher_id, ()):
            return 1
        key = (teacher_id, slot_index)
        if key in self._busy:
            return self._busy[key]
        boths = []
        for group_key, group_demands in self.groups.items():
            presence = self.mv.groups[group_key].presence_teacher.get(teacher_id)
            if presence is None:
                continue
            for demand in group_demands:
                occ = self.occupies(demand, slot_index)
                if occ is None:
                    continue
                both = self.model.NewBoolVar(f"prio_tbusy_{teacher_id}_{demand.id}_{slot_index}")
                self.model.AddBoolAnd([presence, occ]).OnlyEnforceIf(both)
                self.model.AddBoolOr([presence.Not(), occ.Not()]).OnlyEnforceIf(both.Not())
                boths.append(both)
        # MaxEquality, not a sum: merged lab batches are one class taught
        # once, but every batch demand is present on the same teacher.
        self._busy[key] = self.any_of(boths, f"prio_busy_{teacher_id}_{slot_index}") if boths else None
        return self._busy[key]

    def teacher_ids(self) -> List[str]:
        return sorted({t for gv in self.mv.groups.values() for t in gv.eligible_teacher_ids})

    def day_slots(self, day: str) -> List[int]:
        return sorted(s.index for s in self.problem.slots if s.day == day)


def _is_split_group(group_demands) -> bool:
    """A subject whose one session is split into separate single-period
    demands (back_to_back off) - those parts are nudged onto the SAME day
    elsewhere, so the "don't repeat a subject on a day" and "spread across
    the week" rules must leave them alone rather than fight that nudge."""
    return len({d.session_index for d in group_demands}) < len(group_demands)


# ---------------------------------------------------------------- teachers

def _limit_consecutive_teaching(ctx: _Ctx, weight: int, params: Dict[str, int]) -> None:
    limit = max(1, params["max_consecutive_teaching"])
    runs = contiguous_day_runs(ctx.problem.slots)
    for teacher_id in ctx.teacher_ids():
        info = ctx.problem.teachers.get(teacher_id)
        if info and limit >= info.max_continuous_classes:
            continue  # the teacher's own hard cap is already at least this strict
        for run in runs:
            for w_start in range(0, len(run) - limit):
                window = [ctx.teacher_busy(teacher_id, s) for s in run[w_start:w_start + limit + 1]]
                window = [b for b in window if b is not None]
                if len(window) <= limit:
                    continue
                over = ctx.model.NewBoolVar(f"prio_consec_{teacher_id}_{run[w_start]}")
                ctx.model.Add(sum(window) - limit <= over)
                ctx.penalise(over, weight)


def _cap_teacher_daily_periods(ctx: _Ctx, weight: int, params: Dict[str, int]) -> None:
    cap = max(1, params["max_teacher_periods_per_day"])
    for teacher_id in ctx.teacher_ids():
        info = ctx.problem.teachers.get(teacher_id)
        if info and cap >= info.max_daily_classes:
            continue  # hard daily cap is already at least this strict
        for day in ctx.days:
            busy = [b for b in (ctx.teacher_busy(teacher_id, s) for s in ctx.day_slots(day)) if b is not None]
            if len(busy) <= cap:
                continue
            over = ctx.model.NewIntVar(0, len(busy) - cap, f"prio_dailyover_{teacher_id}_{day}")
            ctx.model.Add(sum(busy) - cap <= over)
            ctx.penalise(over, weight)


def _teacher_lighter_day(ctx: _Ctx, weight: int, params: Dict[str, int]) -> None:
    if len(ctx.days) < 2:
        return
    for teacher_id in ctx.teacher_ids():
        light_flags = []
        for day in ctx.days:
            busy = [b for b in (ctx.teacher_busy(teacher_id, s) for s in ctx.day_slots(day)) if b is not None]
            if len(busy) <= LIGHT_DAY_MAX_PERIODS:
                light_flags = None  # this day is light no matter what - nothing to optimise
                break
            light = ctx.model.NewBoolVar(f"prio_light_{teacher_id}_{day}")
            ctx.model.Add(sum(busy) <= LIGHT_DAY_MAX_PERIODS).OnlyEnforceIf(light)
            light_flags.append(light)
        if not light_flags:
            continue
        no_light_day = ctx.model.NewBoolVar(f"prio_nolight_{teacher_id}")
        ctx.model.AddBoolOr(light_flags + [no_light_day])
        ctx.penalise(no_light_day, weight)


# ---------------------------------------------------------------- sections

def _no_repeat_subject_same_day(ctx: _Ctx, weight: int, params: Dict[str, int]) -> None:
    for group_demands in ctx.groups.values():
        if len(group_demands) < 2 or _is_split_group(group_demands):
            continue
        first = group_demands[0]
        # Labs and multi-period blocks are the stated exceptions; a subject
        # already capped at once a day is guaranteed by a hard constraint.
        if first.kind == "lab" or any(d.duration > 1 for d in group_demands) or first.max_per_day <= 1:
            continue
        for day in ctx.days:
            onday = [i for i in (ctx.onday(d, day) for d in group_demands) if i is not None]
            if len(onday) < 2:
                continue
            over = ctx.model.NewIntVar(0, len(onday) - 1, f"prio_repeat_{first.subject_id}_{first.audience_id}_{day}")
            ctx.model.Add(sum(onday) - 1 <= over)
            ctx.penalise(over, weight)


def _spread_subject_across_week(ctx: _Ctx, weight: int, params: Dict[str, int]) -> None:
    for group_demands in ctx.groups.values():
        if len(group_demands) < 2 or _is_split_group(group_demands):
            continue
        first = group_demands[0]
        present = [
            ctx.any_of([ctx.onday(d, day) for d in group_demands], f"prio_present_{first.subject_id}_{first.audience_id}_{day}")
            for day in ctx.days
        ]
        for i in range(len(ctx.days) - 1):
            a, b = ctx.days[i], ctx.days[i + 1]
            if a not in DAY_ORDER or b not in DAY_ORDER or DAY_ORDER.index(b) - DAY_ORDER.index(a) != 1:
                continue
            if isinstance(present[i], int) or isinstance(present[i + 1], int):
                continue  # subject can't land on one of the two days
            adjacent = ctx.model.NewBoolVar(f"prio_adjacent_{first.subject_id}_{first.audience_id}_{a}")
            ctx.model.AddBoolOr([present[i].Not(), present[i + 1].Not(), adjacent])
            ctx.penalise(adjacent, weight)


def _heavy_subjects_early(ctx: _Ctx, weight: int, params: Dict[str, int]) -> None:
    late_slots = set()
    for day in ctx.days:
        day_slots = ctx.day_slots(day)
        late_slots.update(day_slots[(len(day_slots) + 1) // 2:])
    if not late_slots:
        return
    for group_demands in ctx.groups.values():
        first = group_demands[0]
        if first.kind == "lab" or first.elective_group_id:
            continue
        if len({d.session_index for d in group_demands}) < HEAVY_SUBJECT_MIN_SESSIONS:
            continue
        for demand in group_demands:
            late = ctx.membership_indicator(
                ctx.model, ctx.mv.start[demand.id], demand.valid_start_slot_indices,
                [v for v in demand.valid_start_slot_indices if v in late_slots],
                f"prio_late_{demand.id}",
            )
            if late is not None:
                ctx.penalise(late, weight)


def _balanced_theory_lab_days(ctx: _Ctx, weight: int, params: Dict[str, int]) -> None:
    by_section: Dict[str, List] = {}
    for demand in ctx.problem.demands:
        by_section.setdefault(demand.parent_section_id, []).append(demand)
    for section_id, demands in by_section.items():
        labs = [d for d in demands if d.kind == "lab"]
        others = [d for d in demands if d.kind != "lab"]
        if not labs or not others:
            continue  # nothing to balance against
        # A lab-only day is always avoidable. A theory-only day is only
        # avoidable if there are enough separate lab sessions to put one on
        # every day - otherwise every section with one weekly lab would be
        # "violating" four days a week no matter what the solver did.
        lab_sessions = len({(d.subject_id, d.session_index) for d in labs})
        penalise_theory_only = lab_sessions >= len(ctx.days)
        for day in ctx.days:
            lab_on = ctx.any_of([ctx.onday(d, day) for d in labs], f"prio_labon_{section_id}_{day}")
            other_on = ctx.any_of([ctx.onday(d, day) for d in others], f"prio_otheron_{section_id}_{day}")
            if not isinstance(lab_on, int) or not isinstance(other_on, int):
                lab_only = ctx.model.NewBoolVar(f"prio_labonly_{section_id}_{day}")
                ctx.model.Add(lab_only >= lab_on - other_on)
                ctx.penalise(lab_only, weight)
                if penalise_theory_only:
                    theory_only = ctx.model.NewBoolVar(f"prio_theoryonly_{section_id}_{day}")
                    ctx.model.Add(theory_only >= other_on - lab_on)
                    ctx.penalise(theory_only, weight)


RULES = {
    "limit_consecutive_teaching": _limit_consecutive_teaching,
    "cap_teacher_daily_periods": _cap_teacher_daily_periods,
    "teacher_lighter_day": _teacher_lighter_day,
    "no_repeat_subject_same_day": _no_repeat_subject_same_day,
    "spread_subject_across_week": _spread_subject_across_week,
    "heavy_subjects_early": _heavy_subjects_early,
    "balanced_theory_lab_days": _balanced_theory_lab_days,
}


def apply_priority_rules(mv, problem, slots_by_index, membership_indicator, groups, days) -> None:
    """Adds an objective term per enabled rule (weight > 0 in
    problem.soft_weights). Called from build_model before the objective is
    minimised."""
    active = {key: problem.soft_weights.get(key, 0) for key in RULES}
    if not any(active.values()):
        return
    ctx = _Ctx(mv, problem, slots_by_index, membership_indicator, groups, days)
    for key, rule in RULES.items():
        if active[key] > 0:
            rule(ctx, active[key], problem.rule_params)
