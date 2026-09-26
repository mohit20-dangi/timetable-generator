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
from app.solver.calendar import DAY_ORDER, occupied_indices, contiguous_day_runs


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


def _overlap_intervals_collapsing_electives(demands, model, start, occupancy_interval):
    """Elective basket options sharing (elective_group_id, session_index)
    are forced onto the SAME start slot below (that's the whole point - the
    section's several offered options run at once, in different rooms) so
    they must never also be fed as separate entries into a "this audience
    can't be in two places at once" AddNoOverlap - that combination is
    unsatisfiable by construction (same slot == overlapping, "no overlap"
    forbids exactly that), which made every basket with 2+ offered options
    fail every time. Collapses each such cluster into one representative
    interval - anchored at the shared start, sized to the longest option,
    since the audience is genuinely occupied for that whole span regardless
    of which option a given student is in - before it reaches AddNoOverlap.
    A demand with no elective_group_id is its own singleton and passes
    through unchanged."""
    clusters: Dict[Tuple[Optional[str], int], List[SessionDemand]] = {}
    for demand in demands:
        key = (demand.elective_group_id, demand.session_index) if demand.elective_group_id else (None, id(demand))
        clusters.setdefault(key, []).append(demand)

    intervals = []
    for members in clusters.values():
        if len(members) == 1:
            intervals.append(occupancy_interval[members[0].id])
            continue
        anchor = members[0]
        max_duration = max(d.duration for d in members)
        intervals.append(model.NewFixedSizeIntervalVar(
            start[anchor.id], max_duration,
            f"electiveocc_{anchor.elective_group_id}_{anchor.session_index}_{anchor.parent_section_id}",
        ))
    return intervals


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
                # ---- HARD (1.2): a room's availability windows are the
                # only times it may be used - forbid any start whose
                # occupied span touches its unavailable slots, but only
                # when this room is actually chosen for this demand.
                room_info = problem.rooms.get(room_id)
                if room_info and room_info.unavailable_slot_indices:
                    allowed = sorted(
                        v for v in demand.valid_start_slot_indices
                        if not (set(occupied_indices(v, demand.duration, slots_by_index)) & room_info.unavailable_slot_indices)
                    )
                    if len(allowed) < len(demand.valid_start_slot_indices):
                        if allowed:
                            model.AddLinearExpressionInDomain(
                                start_var, cp_model.Domain.FromValues(allowed)
                            ).OnlyEnforceIf(p)
                        else:
                            model.Add(p == 0)
            if not room_presences:
                raise ValueError(
                    f"Demand {demand.id} ({demand.subject_name}) has no eligible room - "
                    "check room type/capacity/equipment requirements."
                )
            model.AddExactlyOne(room_presences)

            # ---- HARD (1.1): a teacher's availability windows are the
            # only times they may teach - forbid any start whose occupied
            # span touches their unavailable slots, but only for the
            # teacher actually chosen for this (subject, audience) group.
            for teacher_id, presence in presence_teacher.items():
                teacher_info = problem.teachers.get(teacher_id)
                if not teacher_info or not teacher_info.unavailable_slot_indices:
                    continue
                allowed = sorted(
                    v for v in demand.valid_start_slot_indices
                    if not (set(occupied_indices(v, demand.duration, slots_by_index)) & teacher_info.unavailable_slot_indices)
                )
                if len(allowed) < len(demand.valid_start_slot_indices):
                    if allowed:
                        model.AddLinearExpressionInDomain(
                            start_var, cp_model.Domain.FromValues(allowed)
                        ).OnlyEnforceIf(presence)
                    else:
                        model.Add(presence == 0)

    # ---- Phase 2.9: "merged" lab batches are taught as ONE combined class
    # - same room, same teacher, same slot - not just nudged toward it.
    # Scoped by (subject_id, parent_section_id): two different sections
    # taking the same subject must never be forced onto each other's
    # teacher/room just because they share a subject id. Exactly one batch
    # per merged group is the "anchor"; every sibling's start/room/teacher
    # is forced equal to it below. Like the elective-basket collapsing
    # this module already does (_overlap_intervals_collapsing_electives),
    # the siblings' own intervals must be EXCLUDED from the shared
    # per-room/per-teacher AddNoOverlap lists just below - otherwise
    # "same room, same time" (the equality) directly contradicts "no two
    # intervals in the same room overlap" (AddNoOverlap), which is
    # unsatisfiable by construction.
    merged_batch_ids_by_subject_section: Dict[Tuple[str, str], List[str]] = {}
    for demand in problem.demands:
        if demand.audience_type == "batch" and demand.batch_mode == "merged":
            key = (demand.subject_id, demand.parent_section_id)
            ids = merged_batch_ids_by_subject_section.setdefault(key, [])
            if demand.audience_id not in ids:
                ids.append(demand.audience_id)
    merged_anchor_batch: Dict[Tuple[str, str], str] = {
        key: batch_ids[0] for key, batch_ids in merged_batch_ids_by_subject_section.items()
        if len(batch_ids) > 1
    }
    merged_non_anchor_demand_ids = {
        d.id for d in problem.demands
        if d.audience_type == "batch" and d.batch_mode == "merged"
        and merged_anchor_batch.get((d.subject_id, d.parent_section_id)) not in (None, d.audience_id)
    }
    merged_non_anchor_group_keys = {
        gk for gk, gd in groups.items()
        if gd[0].audience_type == "batch" and gd[0].batch_mode == "merged"
        and merged_anchor_batch.get((gd[0].subject_id, gd[0].parent_section_id)) not in (None, gd[0].audience_id)
    }

    # ---- HARD (2.9): merged batches share ONE teacher for the whole
    # subject (weekly-consistent, same mechanism as ordinary teacher
    # consistency) - not just per-session, since a merged class is taught
    # together every time it meets.
    for (subject_id, section_id), batch_ids in merged_batch_ids_by_subject_section.items():
        if len(batch_ids) < 2:
            continue
        anchor_id = merged_anchor_batch[(subject_id, section_id)]
        anchor_group = group_vars.get(f"{subject_id}::{anchor_id}")
        if not anchor_group:
            continue
        for batch_id in batch_ids:
            if batch_id == anchor_id:
                continue
            other_group = group_vars.get(f"{subject_id}::{batch_id}")
            if not other_group:
                continue
            for teacher_id, presence in anchor_group.presence_teacher.items():
                other_presence = other_group.presence_teacher.get(teacher_id)
                if other_presence is not None:
                    model.Add(presence == other_presence)

    # ---- per-room no-overlap ----
    all_room_ids = {r for d in problem.demands for r in d.eligible_room_ids} | set(problem.rooms.keys())
    for room_id in all_room_ids:
        intervals = []
        for demand in problem.demands:
            if room_id not in demand.eligible_room_ids:
                continue
            if demand.id in merged_non_anchor_demand_ids:
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
            if group_key in merged_non_anchor_group_keys:
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

    # ---- HARD (1.3): teacher daily / weekly / continuous workload caps.
    # `teacher_loads` (total periods/week per teacher) is handed back so
    # the soft "fair_teacher_workload" objective term can reuse it instead
    # of recomputing the same sum.
    teacher_loads = _add_workload_caps(
        model, problem, groups, group_vars, start, slots_by_index, _membership_indicator,
    )

    # ---- per-audience no-overlap (section vs its own batches) ----
    demands_by_section: Dict[str, List[SessionDemand]] = {}
    demands_by_batch: Dict[str, List[SessionDemand]] = {}
    for demand in problem.demands:
        demands_by_section.setdefault(demand.parent_section_id, []).append(demand)
        if demand.audience_type == "batch":
            demands_by_batch.setdefault(demand.audience_id, []).append(demand)

    section_level_intervals_by_section: Dict[str, List["cp_model.IntervalVar"]] = {}
    for section_id, section_demands in demands_by_section.items():
        section_level = [d for d in section_demands if d.audience_type == "section"]
        section_level_intervals_by_section[section_id] = _overlap_intervals_collapsing_electives(
            section_level, model, start, occupancy_interval,
        )
        if len(section_level_intervals_by_section[section_id]) > 1:
            model.AddNoOverlap(section_level_intervals_by_section[section_id])

    for batch_id, batch_demands in demands_by_batch.items():
        parent_section = batch_demands[0].parent_section_id
        batch_intervals = _overlap_intervals_collapsing_electives(batch_demands, model, start, occupancy_interval)
        combined = batch_intervals + section_level_intervals_by_section.get(parent_section, [])
        if len(combined) > 1:
            model.AddNoOverlap(combined)

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
    # Keyed by (elective_group_id, session_index, parent_section_id) - NOT
    # just the first two. The same ElectiveGroup is routinely offered to
    # several sections (that's what SectionSubject.elective_group_id is
    # for), and co-scheduling is a per-cohort promise ("a student who
    # picked any option never clashes with THEIR OWN core subjects" - see
    # ElectiveGroup's docstring), not a college-wide one. Without
    # parent_section_id here, sharing one basket across two sections forced
    # every section's occurrence onto the exact same global slot - needing
    # sections x offered-options simultaneous rooms/teachers - which made
    # the whole run INFEASIBLE the moment a basket was reused, the normal
    # case for a real curriculum.
    by_elective_slot: Dict[Tuple[str, int, str], List[SessionDemand]] = {}
    for demand in problem.demands:
        if demand.elective_group_id:
            key = (demand.elective_group_id, demand.session_index, demand.parent_section_id)
            by_elective_slot.setdefault(key, []).append(demand)
    for (_group, _idx, _section), members in by_elective_slot.items():
        if len(members) > 1:
            anchor = start[members[0].id]
            for other in members[1:]:
                model.Add(start[other.id] == anchor)

    # ---- HARD (1.5 / 2.9): batch scheduling mode. Either the admin marked
    # the soft "parallel_lab_batches" preference "must have" (legacy
    # Phase 1.5 promotion - treated as "at least parallel" for any batch
    # group that's still "independent"), or the subject/ConstraintRule sets
    # an explicit mode (Phase 2.9): parallel (same start, separate
    # rooms/teachers), sequential (never overlap), or merged (same start,
    # same room, same teacher - room/teacher equality added above, this
    # block only needs the start equality; "must_have" never overrides an
    # explicit "sequential" choice, since forcing them together would
    # directly contradict what the admin asked for).
    must_have_parallel = "parallel_lab_batches" in problem.must_have_rules
    by_subject_section_session: Dict[Tuple[str, str, int], List[SessionDemand]] = {}
    for demand in problem.demands:
        if demand.audience_type != "batch":
            continue
        key = (demand.subject_id, demand.parent_section_id, demand.session_index)
        by_subject_section_session.setdefault(key, []).append(demand)
    for key, batch_demands in by_subject_section_session.items():
        if len(batch_demands) < 2:
            continue
        mode = batch_demands[0].batch_mode
        if mode == "sequential":
            model.AddNoOverlap([occupancy_interval[d.id] for d in batch_demands])
            continue
        if mode not in ("parallel", "merged") and not must_have_parallel:
            continue
        anchor = batch_demands[0]
        for other in batch_demands[1:]:
            model.Add(start[other.id] == start[anchor.id])
            if mode == "merged":
                # Same physical room for this session too, not just "some
                # capacity-eligible room each" - eligible_room_ids is
                # already the identical shared-capacity set (data_loader),
                # so every room id here has a presence var on both sides.
                for room_id in anchor.eligible_room_ids:
                    p_anchor = presence_room.get((anchor.id, room_id))
                    p_other = presence_room.get((other.id, room_id))
                    if p_anchor is not None and p_other is not None:
                        model.Add(p_anchor == p_other)

    # ---- SOFT (2.4): when a session's periods don't have to be
    # back-to-back, data_loader emits them as separate duration=1 demands
    # sharing (subject_id, audience_id, session_index) instead of one
    # contiguous block. Nudge those siblings toward the same day - a
    # student/teacher shouldn't see one subject's periods scattered across
    # the week just because the block itself isn't required to be
    # contiguous.
    by_split_session: Dict[Tuple[str, str, int], List[SessionDemand]] = {}
    for demand in problem.demands:
        if demand.duration != 1:
            continue
        key = (demand.subject_id, demand.audience_id, demand.session_index)
        by_split_session.setdefault(key, []).append(demand)
    day_by_slot = [DAY_ORDER.index(s.day) if s.day in DAY_ORDER else 99 for s in problem.slots]
    day_index_cache: Dict[str, "cp_model.IntVar"] = {}
    split_session_terms: List[Tuple["cp_model.IntVar", int]] = []
    SPLIT_SESSION_SAME_DAY_WEIGHT = 10  # a fixed nudge, not an admin-configurable dial - see 2.4
    for key, siblings in by_split_session.items():
        if len(siblings) < 2:
            continue
        day_vars = []
        for demand in siblings:
            if demand.id not in day_index_cache:
                day_var = model.NewIntVar(0, len(DAY_ORDER), f"day_{demand.id}")
                model.AddElement(start[demand.id], day_by_slot, day_var)
                day_index_cache[demand.id] = day_var
            day_vars.append(day_index_cache[demand.id])
        anchor_day = day_vars[0]
        for other_day, other_demand in zip(day_vars[1:], siblings[1:]):
            not_same_day = model.NewBoolVar(f"splitdiffday_{other_demand.id}")
            model.Add(anchor_day == other_day).OnlyEnforceIf(not_same_day.Not())
            model.Add(anchor_day != other_day).OnlyEnforceIf(not_same_day)
            split_session_terms.append((not_same_day, SPLIT_SESSION_SAME_DAY_WEIGHT))

    mv = ModelVars(
        model=model, start=start, occupancy_interval=occupancy_interval,
        presence_room=presence_room, group_of_demand=group_of_demand, groups=group_vars,
    )
    mv.objective_terms.extend(split_session_terms)

    _add_soft_objective(
        mv, problem, slots_by_index, sentinel_high, sentinel_low,
        _membership_indicator, groups, teacher_loads,
    )
    return mv


def _add_workload_caps(model, problem, groups, group_vars, start, slots_by_index, membership_indicator):
    """HARD (1.3): `max_daily_classes`, `max_weekly_hours` and
    `max_continuous_classes` were collected, stored and shown to the admin
    but never enforced - this is what makes them real. Counts PERIODS
    occupied, not sessions, so a 2-period lab counts as 2 hours of load.
    Returns {teacher_id: weekly-load IntVar} so the soft fair-workload
    objective term can reuse the same sum instead of recomputing it.
    """
    all_teacher_ids = {t for g in group_vars.values() for t in g.eligible_teacher_ids}
    teacher_loads: Dict[str, "cp_model.IntVar"] = {}
    # "does this demand occupy slot s" depends only on the demand's own
    # start var, never on which teacher is being checked - shared across
    # every teacher's continuous-block cap below instead of rebuilt once
    # per teacher.
    occ_cache: Dict[Tuple[str, int], object] = {}

    for teacher_id in all_teacher_ids:
        teacher_info = problem.teachers.get(teacher_id)
        max_daily = teacher_info.max_daily_classes if teacher_info else 6
        max_weekly = teacher_info.max_weekly_hours if teacher_info else 24
        max_continuous = teacher_info.max_continuous_classes if teacher_info else 3

        weekly_terms = []
        for group_key, gv in group_vars.items():
            presence = gv.presence_teacher.get(teacher_id)
            if presence is None:
                continue
            total_duration = sum(d.duration for d in groups[group_key])
            weekly_terms.append((presence, total_duration))

        load = model.NewIntVar(0, 500, f"load_{teacher_id}")
        if weekly_terms:
            model.Add(load == sum(var * coeff for var, coeff in weekly_terms))
        else:
            model.Add(load == 0)
        model.Add(load <= max_weekly)
        teacher_loads[teacher_id] = load

        # ---- daily cap ----
        for day in DAY_ORDER:
            day_terms = []
            for group_key, gv in group_vars.items():
                presence = gv.presence_teacher.get(teacher_id)
                if presence is None:
                    continue
                for demand in groups[group_key]:
                    onday = membership_indicator(
                        model, start[demand.id], demand.valid_start_slot_indices,
                        [i for i in demand.valid_start_slot_indices if slots_by_index[i].day == day],
                        f"tdaily_onday_{teacher_id}_{demand.id}_{day}",
                    )
                    if onday is None:
                        continue
                    both = model.NewBoolVar(f"tdaily_{teacher_id}_{demand.id}_{day}")
                    model.AddBoolAnd([presence, onday]).OnlyEnforceIf(both)
                    model.AddBoolOr([presence.Not(), onday.Not()]).OnlyEnforceIf(both.Not())
                    day_terms.append((both, demand.duration))
            if day_terms:
                model.Add(sum(var * coeff for var, coeff in day_terms) <= max_daily)

        # ---- continuous-block cap: in any window of max_continuous+1
        # consecutive same-day slots, at most max_continuous may be
        # occupied by this teacher ----
        window_size = max_continuous + 1
        candidate_demands = [
            (demand, presence)
            for group_key, gv in group_vars.items()
            if (presence := gv.presence_teacher.get(teacher_id)) is not None
            for demand in groups[group_key]
        ]
        if not candidate_demands:
            continue
        both_cache: Dict[Tuple[str, int], object] = {}
        for run in contiguous_day_runs(problem.slots):
            if len(run) < window_size:
                continue
            for w_start in range(0, len(run) - window_size + 1):
                window_slots = run[w_start:w_start + window_size]
                terms = []
                for demand, presence in candidate_demands:
                    for s in window_slots:
                        cache_key = (demand.id, s)
                        if cache_key not in occ_cache:
                            matching_starts = [
                                v for v in demand.valid_start_slot_indices
                                if s in occupied_indices(v, demand.duration, slots_by_index)
                            ]
                            occ_cache[cache_key] = membership_indicator(
                                model, start[demand.id], demand.valid_start_slot_indices,
                                matching_starts, f"occ_{demand.id}_{s}",
                            )
                        occ = occ_cache[cache_key]
                        if occ is None:
                            continue
                        both_key = (demand.id, s)
                        if both_key not in both_cache:
                            both = model.NewBoolVar(f"tcont_{teacher_id}_{demand.id}_{s}")
                            model.AddBoolAnd([presence, occ]).OnlyEnforceIf(both)
                            model.AddBoolOr([presence.Not(), occ.Not()]).OnlyEnforceIf(both.Not())
                            both_cache[both_key] = both
                        terms.append(both_cache[both_key])
                if terms:
                    model.Add(sum(terms) <= max_continuous)

    return teacher_loads


def _add_soft_objective(mv, problem, slots_by_index, sentinel_high, sentinel_low, membership_indicator, groups, teacher_loads=None):
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
                # `day_count` sums one indicator per DEMAND on this day, so
                # two demands sharing the same slot (parallel lab batches,
                # or an elective basket's co-scheduled options - both
                # forced to the same start elsewhere in this file) inflate
                # it past the number of periods actually spanned, which
                # would otherwise drive the raw gap negative and make the
                # model spuriously infeasible. Floor at 0 - a gap can never
                # sensibly be negative - instead of assuming day_count
                # equals distinct periods occupied.
                raw_gap = model.NewIntVar(sentinel_low, sentinel_high, f"rawgap_{section_id}_{day}")
                model.Add(raw_gap == day_last - day_first + 1 - day_count).OnlyEnforceIf(any_that_day)
                model.Add(raw_gap == 0).OnlyEnforceIf(any_that_day.Not())
                gap = model.NewIntVar(0, sentinel_high, f"gap_{section_id}_{day}")
                model.AddMaxEquality(gap, [raw_gap, model.NewConstant(0)])
                if "minimize_student_gaps" in problem.must_have_rules:
                    # HARD (1.5): "must have" promotes this from a penalty
                    # to a real zero-gaps requirement instead of just a
                    # very large weight.
                    model.Add(gap == 0)
                else:
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
    # Reuses the weekly-load IntVars _add_workload_caps already built for
    # the hard max_weekly_hours cap (1.3) instead of recomputing the same
    # presence*duration sum a second time.
    fair_weight = weights.get("fair_teacher_workload", 0)
    if fair_weight > 0 and teacher_loads:
        loads = list(teacher_loads.values())
        if len(loads) > 1:
            max_load = model.NewIntVar(0, 500, "max_load")
            min_load = model.NewIntVar(0, 500, "min_load")
            model.AddMaxEquality(max_load, loads)
            model.AddMinEquality(min_load, loads)
            fairness_spread = model.NewIntVar(0, 500, "fairness_spread")
            model.Add(fairness_spread == max_load - min_load)
            objective_terms.append((fairness_spread, fair_weight))

    # ---- prefer lab batches run in parallel ----
    # Skipped for any (subject, section, session) already forced together -
    # or forced apart, or forced merged - by a hard constraint above
    # (Phase 2.9's batch_mode, or the legacy "must_have" promotion), since
    # nudging on top would be either redundant or, for "sequential",
    # actively fighting the hard no-overlap constraint.
    parallel_weight = weights.get("parallel_lab_batches", 0)
    must_have_parallel = "parallel_lab_batches" in problem.must_have_rules
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
            if must_have_parallel or any(d.batch_mode != "independent" for d in batch_demands):
                continue
            anchor = mv.start[batch_demands[0].id]
            for other in batch_demands[1:]:
                diff = model.NewIntVar(-500, 500, f"paralleldiff_{other.id}")
                model.Add(diff == mv.start[other.id] - anchor)
                abs_diff = model.NewIntVar(0, 500, f"parallelabs_{other.id}")
                model.AddAbsEquality(abs_diff, diff)
                objective_terms.append((abs_diff, parallel_weight))

    # ---- ConstraintRule soft avoid-slot preferences (1.4, priority="soft") ----
    for rule_idx, rule in enumerate(problem.soft_avoid_rules):
        if rule.weight <= 0 or not rule.slot_indices:
            continue
        if rule.scope == "teacher":
            for group_key, group_demands in groups.items():
                presence = mv.groups[group_key].presence_teacher.get(rule.resource_id)
                if presence is None:
                    continue
                for demand in group_demands:
                    hits = membership_indicator(
                        model, mv.start[demand.id], demand.valid_start_slot_indices,
                        [v for v in demand.valid_start_slot_indices if v in rule.slot_indices],
                        f"ruleavoid_{rule_idx}_{demand.id}",
                    )
                    if hits is None:
                        continue
                    both = model.NewBoolVar(f"ruleavoidboth_{rule_idx}_{demand.id}")
                    model.AddBoolAnd([presence, hits]).OnlyEnforceIf(both)
                    model.AddBoolOr([presence.Not(), hits.Not()]).OnlyEnforceIf(both.Not())
                    objective_terms.append((both, rule.weight))
        elif rule.scope == "room":
            for demand in problem.demands:
                presence = mv.presence_room.get((demand.id, rule.resource_id))
                if presence is None:
                    continue
                hits = membership_indicator(
                    model, mv.start[demand.id], demand.valid_start_slot_indices,
                    [v for v in demand.valid_start_slot_indices if v in rule.slot_indices],
                    f"ruleavoidroom_{rule_idx}_{demand.id}",
                )
                if hits is None:
                    continue
                both = model.NewBoolVar(f"ruleavoidroomboth_{rule_idx}_{demand.id}")
                model.AddBoolAnd([presence, hits]).OnlyEnforceIf(both)
                model.AddBoolOr([presence.Not(), hits.Not()]).OnlyEnforceIf(both.Not())
                objective_terms.append((both, rule.weight))
        elif rule.scope == "section":
            for demand in problem.demands:
                if demand.parent_section_id != rule.resource_id:
                    continue
                hits = membership_indicator(
                    model, mv.start[demand.id], demand.valid_start_slot_indices,
                    [v for v in demand.valid_start_slot_indices if v in rule.slot_indices],
                    f"ruleavoidsection_{rule_idx}_{demand.id}",
                )
                if hits is not None:
                    objective_terms.append((hits, rule.weight))

    if objective_terms:
        model.Minimize(sum(var * weight for var, weight in objective_terms))
