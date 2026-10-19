"""Admin-defined preferences: parameterised rule TEMPLATES.

The fixed soft-rule catalogue in weights.py only lets an admin change how
important each built-in rule is. This module is what lets an admin create
NEW rules without a code change: each template below is a small, safe,
parameterised building block (never free-form code), and an admin combines
a template with a target, parameters and a priority:

  hard - the rule is never violated (a real constraint);
  soft - each violation costs `weight` in the objective.

To add another template: write a function here that takes the CP-SAT model
and a CustomRule, register it in TEMPLATES, allow its rule_type/target in
app/schemas/constraint_rule.py, and add its form fields in the frontend's
ConstraintRulesManager.tsx. Nothing else (weights.py, _add_soft_objective)
needs to change.
"""
from typing import Dict, List

from ortools.sat.python import cp_model

from app.solver.calendar import DAY_ORDER, occupied_indices
from app.solver.types import CustomRule, ProblemData, SessionDemand


def _penalise(model, objective_terms, rule: CustomRule, violation_expr, upper: int, name: str) -> None:
    """Adds `weight * violation` to the objective. `violation_expr` is a
    linear expression that is >= 0 exactly when the rule is being broken."""
    excess = model.NewIntVar(0, max(1, upper), name)
    model.Add(excess >= violation_expr)
    objective_terms.append((excess, rule.weight))


def _subject_time_window(ctx, rule: CustomRule) -> None:
    """Keep a subject inside (mode="within") or out of (mode="avoid") a
    time window, e.g. "Maths only in the morning". Judged per session: a
    session counts as inside only if every period it occupies is inside."""
    model, problem = ctx["model"], ctx["problem"]
    matched = [d for d in problem.demands if d.subject_id == rule.target_id]
    for demand in matched:
        offending = []
        for start in demand.valid_start_slot_indices:
            occupied = set(occupied_indices(start, demand.duration, ctx["slots_by_index"]))
            inside = occupied <= rule.slot_indices
            touches = bool(occupied & rule.slot_indices)
            violates = (not inside) if rule.mode == "within" else touches
            if violates:
                offending.append(start)
        if not offending:
            continue
        if rule.hard:
            allowed = sorted(set(demand.valid_start_slot_indices) - set(offending))
            if not allowed:
                raise ValueError(
                    f"Rule '{rule.label}' leaves no valid time for {demand.subject_name} "
                    f"({demand.audience_id}): every slot it could use is excluded. "
                    "Widen the window, make the rule soft, or shorten the session."
                )
            model.AddLinearExpressionInDomain(
                ctx["start"][demand.id], cp_model.Domain.FromValues(allowed)
            )
        else:
            hit = ctx["membership_indicator"](
                model, ctx["start"][demand.id], demand.valid_start_slot_indices, offending,
                f"twin_{rule.label}_{demand.id}",
            )
            if hit is not None:
                ctx["objective_terms"].append((hit, rule.weight))


def _max_subjects_per_day(ctx, rule: CustomRule) -> None:
    """A section has at most `limit` different subjects on any one day.
    Elective-basket options count as ONE subject (they run together)."""
    model, problem = ctx["model"], ctx["problem"]
    by_section: Dict[str, List[SessionDemand]] = {}
    for demand in problem.demands:
        if rule.target_id in ("*", demand.parent_section_id):
            by_section.setdefault(demand.parent_section_id, []).append(demand)

    for section_id, demands in by_section.items():
        by_subject: Dict[str, List[SessionDemand]] = {}
        for demand in demands:
            key = demand.elective_group_id or demand.subject_id
            by_subject.setdefault(key, []).append(demand)
        if len(by_subject) <= rule.limit:
            continue  # can never be exceeded
        for day in ctx["days"]:
            subject_present = []
            for subject_key, subject_demands in by_subject.items():
                onday = []
                for demand in subject_demands:
                    ind = ctx["membership_indicator"](
                        model, ctx["start"][demand.id], demand.valid_start_slot_indices,
                        [i for i in demand.valid_start_slot_indices if ctx["slots_by_index"][i].day == day],
                        f"msd_on_{rule.label}_{demand.id}_{day}",
                    )
                    if ind is not None:
                        onday.append(ind)
                if not onday:
                    continue
                present = model.NewBoolVar(f"msd_{rule.label}_{section_id}_{subject_key}_{day}")
                model.AddMaxEquality(present, onday)
                subject_present.append(present)
            if len(subject_present) <= rule.limit:
                continue
            if rule.hard:
                model.Add(sum(subject_present) <= rule.limit)
            else:
                _penalise(
                    model, ctx["objective_terms"], rule, sum(subject_present) - rule.limit,
                    len(subject_present), f"msd_excess_{rule.label}_{section_id}_{day}",
                )


def _teacher_max_days_per_week(ctx, rule: CustomRule) -> None:
    """A teacher teaches on at most `limit` different days of the week."""
    model, problem, groups = ctx["model"], ctx["problem"], ctx["groups"]
    day_used = []
    for day in ctx["days"]:
        both_terms = []
        for group_key, group_demands in groups.items():
            presence = ctx["group_vars"][group_key].presence_teacher.get(rule.target_id)
            if presence is None:
                continue
            for demand in group_demands:
                onday = ctx["membership_indicator"](
                    model, ctx["start"][demand.id], demand.valid_start_slot_indices,
                    [i for i in demand.valid_start_slot_indices if ctx["slots_by_index"][i].day == day],
                    f"tmd_on_{rule.label}_{demand.id}_{day}",
                )
                if onday is None:
                    continue
                both = model.NewBoolVar(f"tmd_both_{rule.label}_{demand.id}_{day}")
                model.AddBoolAnd([presence, onday]).OnlyEnforceIf(both)
                model.AddBoolOr([presence.Not(), onday.Not()]).OnlyEnforceIf(both.Not())
                both_terms.append(both)
        # Frozen bookings from other runs also count as a day this teacher works.
        frozen_days = {
            ctx["slots_by_index"][b.start_slot_index].day
            for b in problem.fixed_bookings
            if b.resource_type == "teacher" and b.resource_id == rule.target_id
            and b.start_slot_index in ctx["slots_by_index"]
        }
        used = model.NewBoolVar(f"tmd_used_{rule.label}_{day}")
        if day in frozen_days:
            model.Add(used == 1)
        elif both_terms:
            model.AddMaxEquality(used, both_terms)
        else:
            model.Add(used == 0)
        day_used.append(used)
    if len(day_used) <= rule.limit:
        return
    if rule.hard:
        model.Add(sum(day_used) <= rule.limit)
    else:
        _penalise(
            model, ctx["objective_terms"], rule, sum(day_used) - rule.limit,
            len(day_used), f"tmd_excess_{rule.label}",
        )


TEMPLATES = {
    "subject_time_window": _subject_time_window,
    "max_subjects_per_day": _max_subjects_per_day,
    "teacher_max_days_per_week": _teacher_max_days_per_week,
}


def apply_custom_rules(mv, problem: ProblemData, slots_by_index, membership_indicator, groups, group_vars) -> None:
    """Compiles every admin-defined rule onto the model. Hard rules become
    constraints; soft rules append weighted terms to mv.objective_terms
    (which build_model minimises after this returns)."""
    if not problem.custom_rules:
        return
    days = sorted({s.day for s in problem.slots}, key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 99)
    ctx = {
        "model": mv.model, "problem": problem, "start": mv.start, "slots_by_index": slots_by_index,
        "membership_indicator": membership_indicator, "groups": groups, "group_vars": group_vars,
        "days": days, "objective_terms": mv.objective_terms,
    }
    for rule in problem.custom_rules:
        TEMPLATES[rule.kind](ctx, rule)
