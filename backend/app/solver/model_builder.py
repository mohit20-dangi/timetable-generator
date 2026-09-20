"""Builds the OR-Tools CP-SAT model for one department's timetable.

Encoding summary (see CLAUDE.md's algorithm-selection section for why
CP-SAT over ILP/GA/greedy):
  - Time is flattened to a single integer axis (Slot.index, day-major then
    period-major - see app/solver/calendar.py). Within one day, slot index
    order == chronological order, which every soft-constraint helper here
    relies on.
  - Each SessionDemand gets one `start` IntVar, domain-restricted to only
    the slot indices where its full duration fits in one contiguous,
    same-day run (see calendar.valid_starts_for_duration) - so "a lab block
    never crosses a day boundary or lunch" is true by construction, not by
    a constraint that could be forgotten.
  - Room and teacher choice are channelled through per-(demand, resource)
    boolean "presence" variables and OptionalIntervalVars, the standard
    CP-SAT flexible-scheduling pattern: AddNoOverlap per resource is what
    actually enforces "no double-booking", and it is tight (native
    interval reasoning) rather than O(n^2) pairwise inequalities.
  - Teacher CONSISTENCY per (subject, audience) - a hard constraint the
    previous build never had - falls out of the encoding for free: all
    sessions of one (subject, audience) group share the SAME
    presence_teacher booleans, so picking a teacher for one session picks
    it for all of them.
  - Reservations (frozen bookings from other runs/departments/scopes) are
    injected as ordinary always-present intervals into the same
    per-resource NoOverlap lists - no special-casing needed.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from app.solver.types import ProblemData, SessionDemand
from app.solver.calendar import DAY_ORDER


@dataclass
class GroupVars:
    demand_ids: List[str]
    eligible_teacher_ids: List[str]
    presence_teacher: Dict[str, "cp_model.IntVar"]  # teacher_id -> BoolVar, shared by every demand in the group


@dataclass
class ModelVars:
    model: cp_model.CpModel
    start: Dict[str, "cp_model.IntVar"]
    occupancy_interval: Dict[str, "cp_model.IntervalVar"]
    presence_room: Dict[Tuple[str, str], "cp_model.IntVar"]  # (demand_id, room_id) -> BoolVar
    group_of_demand: Dict[str, str]  # demand_id -> group_key
    groups: Dict[str, GroupVars]
    objective_terms: List[Tuple["cp_model.IntVar", int]] = field(default_factory=list)


def _group_key(demand: SessionDemand) -> str:
    return f"{demand.subject_id}::{demand.audience_id}"


def _membership_indicator(model, var, valid_values, target_values, name):
    """A BoolVar that is 1 iff `var`'s solved value is in `target_values`
    (a subset of `valid_values`, var's own domain). Returns None if
    `target_values` is empty for this variable (it can never happen)."""
    target = sorted(set(valid_values) & set(target_values))
    if not target:
        return None
    rest = sorted(set(valid_values) - set(target))
    indicator = model.NewBoolVar(name)
    model.AddLinearExpressionInDomain(var, cp_model.Domain.FromValues(target)).OnlyEnforceIf(indicator)
    if rest:
        model.AddLinearExpressionInDomain(var, cp_model.Domain.FromValues(rest)).OnlyEnforceIf(indicator.Not())
    else:
        model.Add(indicator == 1)
    return indicator


def build_model(problem: ProblemData) -> ModelVars:
    model = cp_model.CpModel()
    slots_by_index = {s.index: s for s in problem.slots}
    max_slot_index = max((s.index for s in problem.slots), default=0)
    sentinel_high = max_slot_index + 10
    sentinel_low = -10

    # ---- group demands by (subject, audience) for teacher consistency ----
    groups: Dict[str, List[SessionDemand]] = {}
    for demand in problem.demands:
        groups.setdefault(_group_key(demand), []).append(demand)

    start: Dict[str, cp_model.IntVar] = {}
    occupancy_interval: Dict[str, cp_model.IntervalVar] = {}
    presence_room: Dict[Tuple[str, str], cp_model.IntVar] = {}
    group_of_demand: Dict[str, str] = {}
    group_vars: Dict[str, GroupVars] = {}

    for group_key, group_demands in groups.items():
        eligible_teachers = sorted(set(group_demands[0].eligible_teacher_ids))
        presence_teacher = {t: model.NewBoolVar(f"grpteach_{group_key}_{t}") for t in eligible_teachers}
        if eligible_teachers:
            model.AddExactlyOne(list(presence_teacher.values()))
        group_vars[group_key] = GroupVars(
            demand_ids=[d.id for d in group_demands],
            eligible_teacher_ids=eligible_teachers,
            presence_teacher=presence_teacher,
        )

        for demand in group_demands:
            group_of_demand[demand.id] = group_key
            if not demand.valid_start_slot_indices:
                raise ValueError(
                    f"Demand {demand.id} ({demand.subject_name}) has no valid start slot - "
                    f"its block length ({demand.duration} periods) doesn't fit any configured "
                    f"contiguous run of time slots. Add more time slots or shorten the block."
                )
            start_var = model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(sorted(set(demand.valid_start_slot_indices))),
                f"start_{demand.id}",
            )
            start[demand.id] = start_var
            occupancy_interval[demand.id] = model.NewFixedSizeIntervalVar(
                start_var, demand.duration, f"occ_{demand.id}"
            )

            room_presences = []
            for room_id in demand.eligible_room_ids:
                p = model.NewBoolVar(f"room_{demand.id}_{room_id}")
                presence_room[(demand.id, room_id)] = p
                room_presences.append(p)
            if not room_presences:
                raise ValueError(
                    f"Demand {demand.id} ({demand.subject_name}) has no eligible room - "
                    "check room type/capacity/equipment requirements."
                )
            model.AddExactlyOne(room_presences)

    # ---- per-room no-overlap ----
    all_room_ids = {r for d in problem.demands for r in d.eligible_room_ids} | set(problem.rooms.keys())
    for room_id in all_room_ids:
        intervals = []
        for demand in problem.demands:
            if room_id not in demand.eligible_room_ids:
                continue
            p = presence_room[(demand.id, room_id)]
            intervals.append(model.NewOptionalFixedSizeIntervalVar(
                start[demand.id], demand.duration, p, f"roomiv_{demand.id}_{room_id}"
            ))
        for i, booking in enumerate(problem.fixed_bookings):
            if booking.resource_type == "room" and booking.resource_id == room_id:
                intervals.append(model.NewFixedSizeIntervalVar(
                    booking.start_slot_index, booking.duration, f"roomresv_{room_id}_{i}"
                ))
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    # ---- per-teacher no-overlap ----
    all_teacher_ids = {t for g in group_vars.values() for t in g.eligible_teacher_ids} | set(problem.teachers.keys())
    for teacher_id in all_teacher_ids:
        intervals = []
        for group_key, gv in group_vars.items():
            if teacher_id not in gv.presence_teacher:
                continue
            p = gv.presence_teacher[teacher_id]
            for demand_id in gv.demand_ids:
                intervals.append(model.NewOptionalFixedSizeIntervalVar(
                    start[demand_id],
                    next(d.duration for d in problem.demands if d.id == demand_id),
                    p,
                    f"teachiv_{demand_id}_{teacher_id}",
                ))
        for i, booking in enumerate(problem.fixed_bookings):
            if booking.resource_type == "teacher" and booking.resource_id == teacher_id:
                intervals.append(model.NewFixedSizeIntervalVar(
                    booking.start_slot_index, booking.duration, f"teachresv_{teacher_id}_{i}"
                ))
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    # ---- per-audience no-overlap (section vs its own batches) ----
    demands_by_section: Dict[str, List[SessionDemand]] = {}
    demands_by_batch: Dict[str, List[SessionDemand]] = {}
    for demand in problem.demands:
        demands_by_section.setdefault(demand.parent_section_id, []).append(demand)
        if demand.audience_type == "batch":
            demands_by_batch.setdefault(demand.audience_id, []).append(demand)

    for section_id, section_demands in demands_by_section.items():
        section_level = [d for d in section_demands if d.audience_type == "section"]
        if len(section_level) > 1:
            model.AddNoOverlap([occupancy_interval[d.id] for d in section_level])

    for batch_id, batch_demands in demands_by_batch.items():
        parent_section = batch_demands[0].parent_section_id
        section_level = [d for d in demands_by_section.get(parent_section, []) if d.audience_type == "section"]
        combined = batch_demands + section_level
        if len(combined) > 1:
            model.AddNoOverlap([occupancy_interval[d.id] for d in combined])

    # ---- HARD: same (subject, audience) at most max_per_day times/day ----
    for group_key, group_demands in groups.items():
        max_per_day = group_demands[0].max_per_day
        for day in DAY_ORDER:
            indicators = []
            for demand in group_demands:
                ind = _membership_indicator(
                    model, start[demand.id], demand.valid_start_slot_indices,
                    [i for i in demand.valid_start_slot_indices if slots_by_index[i].day == day],
                    f"onday_{demand.id}_{day}",
                )
                if ind is not None:
                    indicators.append(ind)
            if indicators:
                model.Add(sum(indicators) <= max_per_day)

    # ---- HARD: elective basket options co-scheduled ----
    by_elective_slot: Dict[Tuple[str, int], List[SessionDemand]] = {}
    for demand in problem.demands:
        if demand.elective_group_id:
            by_elective_slot.setdefault((demand.elective_group_id, demand.session_index), []).append(demand)
    for (_group, _idx), members in by_elective_slot.items():
        if len(members) > 1:
            anchor = start[members[0].id]
            for other in members[1:]:
                model.Add(start[other.id] == anchor)

    mv = ModelVars(
        model=model, start=start, occupancy_interval=occupancy_interval,
        presence_room=presence_room, group_of_demand=group_of_demand, groups=group_vars,
    )

    _add_soft_objective(
        mv, problem, slots_by_index, sentinel_high, sentinel_low,
        _membership_indicator, groups,
    )
    return mv


def _add_soft_objective(mv, problem, slots_by_index, sentinel_high, sentinel_low, membership_indicator, groups):
    model = mv.model
    weights = problem.soft_weights
    objective_terms = mv.objective_terms

    days_present = sorted({s.day for s in problem.slots}, key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 99)
    edge_first = {}
    edge_last = {}
    for day in days_present:
        day_slots = [s for s in problem.slots if s.day == day]
        if day_slots:
            edge_first[day] = min(s.index for s in day_slots)
            edge_last[day] = max(s.index for s in day_slots)

    # ---- student gaps + day-balance, computed together per section ----
    demands_by_section: Dict[str, List] = {}
    for demand in problem.demands:
        demands_by_section.setdefault(demand.parent_section_id, []).append(demand)

    gap_weight = weights.get("minimize_student_gaps", 0)
    balance_weight = weights.get("balance_load_across_days", 0)

    for section_id, section_demands in demands_by_section.items():
        day_counts = []
        for day in days_present:
            first_terms, last_terms, onday_bools = [], [], []
            for demand in section_demands:
                onday = membership_indicator(
                    model, mv.start[demand.id], demand.valid_start_slot_indices,
                    [i for i in demand.valid_start_slot_indices if slots_by_index[i].day == day],
                    f"gaponday_{demand.id}_{day}",
                )
                if onday is None:
                    continue
                onday_bools.append(onday)
                first_i = model.NewIntVar(sentinel_low, sentinel_high, f"first_{demand.id}_{day}")
                model.Add(first_i == mv.start[demand.id]).OnlyEnforceIf(onday)
                model.Add(first_i == sentinel_high).OnlyEnforceIf(onday.Not())
                last_i = model.NewIntVar(sentinel_low, sentinel_high, f"last_{demand.id}_{day}")
                model.Add(last_i == mv.start[demand.id] + demand.duration - 1).OnlyEnforceIf(onday)
                model.Add(last_i == sentinel_low).OnlyEnforceIf(onday.Not())
                first_terms.append(first_i)
                last_terms.append(last_i)
            if not onday_bools:
                day_counts.append(model.NewConstant(0))
                continue
            day_count = model.NewIntVar(0, len(onday_bools), f"count_{section_id}_{day}")
            model.Add(day_count == sum(onday_bools))
            day_counts.append(day_count)

            if gap_weight > 0:
                any_that_day = model.NewBoolVar(f"any_{section_id}_{day}")
                model.Add(day_count >= 1).OnlyEnforceIf(any_that_day)
                model.Add(day_count == 0).OnlyEnforceIf(any_that_day.Not())
                day_first = model.NewIntVar(sentinel_low, sentinel_high, f"dfirst_{section_id}_{day}")
                model.AddMinEquality(day_first, first_terms)
                day_last = model.NewIntVar(sentinel_low, sentinel_high, f"dlast_{section_id}_{day}")
                model.AddMaxEquality(day_last, last_terms)
                gap = model.NewIntVar(0, sentinel_high, f"gap_{section_id}_{day}")
                model.Add(gap == day_last - day_first + 1 - day_count).OnlyEnforceIf(any_that_day)
                model.Add(gap == 0).OnlyEnforceIf(any_that_day.Not())
                objective_terms.append((gap, gap_weight))

        if balance_weight > 0 and len(day_counts) > 1:
            max_c = model.NewIntVar(0, 200, f"maxc_{section_id}")
            min_c = model.NewIntVar(0, 200, f"minc_{section_id}")
            model.AddMaxEquality(max_c, day_counts)
            model.AddMinEquality(min_c, day_counts)
            spread = model.NewIntVar(0, 200, f"spread_{section_id}")
            model.Add(spread == max_c - min_c)
            objective_terms.append((spread, balance_weight))

    # ---- avoid first/last period of the day ----
    edge_weight = weights.get("avoid_edge_periods", 0)
    if edge_weight > 0:
        first_values = set(edge_first.values())
        last_values = set(edge_last.values())
        for demand in problem.demands:
            start_hits = membership_indicator(
                model, mv.start[demand.id], demand.valid_start_slot_indices,
                [v for v in demand.valid_start_slot_indices if v in first_values],
                f"edgefirst_{demand.id}",
            )
            if start_hits is not None:
                objective_terms.append((start_hits, edge_weight))
            end_values = [v + demand.duration - 1 for v in demand.valid_start_slot_indices]
            ending_in_last = [v for v, e in zip(demand.valid_start_slot_indices, end_values) if e in last_values]
            end_hits = membership_indicator(
                model, mv.start[demand.id], demand.valid_start_slot_indices, ending_in_last,
                f"edgelast_{demand.id}",
            )
            if end_hits is not None:
                objective_terms.append((end_hits, edge_weight))

    # ---- teacher preferred slots (reward -> negative weight) ----
    pref_weight = weights.get("teacher_preferred_slots", 0)
    if pref_weight > 0:
        for group_key, group_demands in groups.items():
            gv = mv.groups[group_key]
            for teacher_id, presence in gv.presence_teacher.items():
                teacher = problem.teachers.get(teacher_id)
                if not teacher or not teacher.preferred_slot_indices:
                    continue
                for demand in group_demands:
                    hits = membership_indicator(
                        model, mv.start[demand.id], demand.valid_start_slot_indices,
                        [v for v in demand.valid_start_slot_indices if v in teacher.preferred_slot_indices],
                        f"pref_{demand.id}_{teacher_id}",
                    )
                    if hits is None:
                        continue
                    both = model.NewBoolVar(f"prefboth_{demand.id}_{teacher_id}")
                    model.AddBoolAnd([presence, hits]).OnlyEnforceIf(both)
                    model.AddBoolOr([presence.Not(), hits.Not()]).OnlyEnforceIf(both.Not())
                    objective_terms.append((both, -pref_weight))

    # ---- fair teacher workload: minimize (max load - min load) ----
    fair_weight = weights.get("fair_teacher_workload", 0)
    if fair_weight > 0:
        loaded_teachers = {t for gv in mv.groups.values() for t in gv.eligible_teacher_ids}
        loads = []
        for teacher_id in loaded_teachers:
            terms = []
            for group_key, group_demands in groups.items():
                gv = mv.groups[group_key]
                if teacher_id not in gv.presence_teacher:
                    continue
                total_duration = sum(d.duration for d in group_demands)
                terms.append((gv.presence_teacher[teacher_id], total_duration))
            if not terms:
                continue
            load = model.NewIntVar(0, 200, f"load_{teacher_id}")
            model.Add(load == sum(var * coeff for var, coeff in terms))
            loads.append(load)
        if len(loads) > 1:
            max_load = model.NewIntVar(0, 200, "max_load")
            min_load = model.NewIntVar(0, 200, "min_load")
            model.AddMaxEquality(max_load, loads)
            model.AddMinEquality(min_load, loads)
            fairness_spread = model.NewIntVar(0, 200, "fairness_spread")
            model.Add(fairness_spread == max_load - min_load)
            objective_terms.append((fairness_spread, fair_weight))

    # ---- prefer lab batches run in parallel ----
    parallel_weight = weights.get("parallel_lab_batches", 0)
    if parallel_weight > 0:
        by_subject_section_session: Dict[Tuple[str, str, int], List] = {}
        for demand in problem.demands:
            if demand.audience_type != "batch":
                continue
            key = (demand.subject_id, demand.parent_section_id, demand.session_index)
            by_subject_section_session.setdefault(key, []).append(demand)
        for key, batch_demands in by_subject_section_session.items():
            if len(batch_demands) < 2:
                continue
            anchor = mv.start[batch_demands[0].id]
            for other in batch_demands[1:]:
                diff = model.NewIntVar(-500, 500, f"paralleldiff_{other.id}")
                model.Add(diff == mv.start[other.id] - anchor)
                abs_diff = model.NewIntVar(0, 500, f"parallelabs_{other.id}")
                model.AddAbsEquality(abs_diff, diff)
                objective_terms.append((abs_diff, parallel_weight))

    if objective_terms:
        model.Minimize(sum(var * weight for var, weight in objective_terms))
