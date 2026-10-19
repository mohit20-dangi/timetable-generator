"""Rules only the remedial solve has, added on top of the regular model (see
engine.solve_with_alternatives' extend_model hook). The regular model already
guarantees no section, teacher or room is double-booked and that the frozen
main timetable is respected; this adds the admin's remedial limits.
"""
from typing import Dict, List

from ortools.sat.python import cp_model

from app.solver.calendar import DAY_ORDER
from app.solver.model_builder import ModelVars, _membership_indicator
from app.solver.remedial_loader import RemedialContext
from app.solver.types import ProblemData


def extend_remedial_model(problem: ProblemData, mv: ModelVars, context: RemedialContext) -> None:
    model = mv.model
    settings = context.settings
    slots_by_index = {s.index: s for s in problem.slots}
    days = sorted({s.day for s in problem.slots}, key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 99)

    # ---- per section, per day: how many remedial periods the students attend.
    # HARD cap (the "never more than two a day" rule); SOFT penalty for going
    # past the preferred number (the "one a day if at all possible" rule). ----
    demands_by_section: Dict[str, list] = {}
    for demand in problem.demands:
        for section_id in demand.attending_section_ids:
            demands_by_section.setdefault(section_id, []).append(demand)

    for section_id, attended in demands_by_section.items():
        for day in days:
            terms = []
            for demand in attended:
                day_starts = [i for i in demand.valid_start_slot_indices if slots_by_index[i].day == day]
                indicator = _membership_indicator(
                    model, mv.start[demand.id], demand.valid_start_slot_indices, day_starts,
                    f"remsec_{section_id}_{day}_{demand.id}",
                )
                if indicator is not None:
                    terms.append((indicator, demand.duration))
            if not terms:
                continue
            periods_that_day = sum(var * duration for var, duration in terms)
            model.Add(periods_that_day <= settings.hard_max_per_day)
            if settings.hard_max_per_day > settings.preferred_max_per_day and settings.weight_over_preferred_per_day:
                excess = model.NewIntVar(0, settings.hard_max_per_day, f"remexcess_{section_id}_{day}")
                model.Add(excess >= periods_that_day - settings.preferred_max_per_day)
                mv.objective_terms.append((excess, settings.weight_over_preferred_per_day))

    # ---- SOFT: prefer after-class / remedial-only slots over a gap in the
    # middle of the students' day ----
    if settings.weight_mid_day_gap:
        for demand in problem.demands:
            mid_day = context.mid_day_starts.get(demand.id)
            if not mid_day:
                continue
            indicator = _membership_indicator(
                model, mv.start[demand.id], demand.valid_start_slot_indices, mid_day, f"remmid_{demand.id}",
            )
            if indicator is not None:
                mv.objective_terms.append((indicator, settings.weight_mid_day_gap))

    # ---- SOFT: prefer the teacher who already teaches the subject to these
    # sections. One penalty per (group) since a group keeps one teacher. ----
    if settings.weight_non_regular_teacher:
        seen_groups = set()
        for demand in problem.demands:
            group_key = mv.group_of_demand[demand.id]
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            regular = context.regular_teachers.get(demand.id) or set()
            gv = mv.groups[group_key]
            regular_presence: List[cp_model.IntVar] = [gv.presence_teacher[t] for t in regular if t in gv.presence_teacher]
            if not regular_presence or len(regular_presence) == len(gv.presence_teacher):
                continue  # no regular teacher to prefer, or every candidate is one
            not_regular = model.NewBoolVar(f"remnonreg_{group_key}")
            model.Add(not_regular + sum(regular_presence) == 1)
            mv.objective_terms.append((not_regular, settings.weight_non_regular_teacher))
