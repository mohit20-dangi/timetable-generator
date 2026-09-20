"""Orchestrates one solve: build the CP-SAT model, run it, extract the
schedule, and (optionally) produce several diverse near-optimal
alternatives for side-by-side comparison in the UI.
"""
import time
from typing import List

from ortools.sat.python import cp_model

from app.solver.types import ProblemData, SolveResult, ScheduledSession
from app.solver.model_builder import build_model, _group_key

STATUS_NAMES = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.UNKNOWN: "UNKNOWN",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
}


def _extract_sessions(problem: ProblemData, mv, solver: cp_model.CpSolver) -> List[ScheduledSession]:
    demands_by_id = {d.id: d for d in problem.demands}
    sessions = []
    for demand_id, demand in demands_by_id.items():
        start_val = solver.Value(mv.start[demand_id])
        room_id = next(
            r for r in demand.eligible_room_ids
            if solver.Value(mv.presence_room[(demand_id, r)]) == 1
        )
        group_key = mv.group_of_demand[demand_id]
        gv = mv.groups[group_key]
        teacher_id = next(
            t for t, p in gv.presence_teacher.items() if solver.Value(p) == 1
        )
        sessions.append(ScheduledSession(
            demand_id=demand_id,
            subject_id=demand.subject_id,
            audience_type=demand.audience_type,
            audience_id=demand.audience_id,
            parent_section_id=demand.parent_section_id,
            start_slot_index=start_val,
            duration=demand.duration,
            room_id=room_id,
            teacher_id=teacher_id,
        ))
    return sessions


def solve_with_alternatives(
    problem: ProblemData,
    max_seconds: int = 240,
    num_workers: int = 8,
    num_alternatives: int = 1,
) -> List[SolveResult]:
    if not problem.demands:
        return [SolveResult(status="OPTIMAL", objective_value=0, sessions=[], wall_time_seconds=0.0)]

    try:
        mv = build_model(problem)
    except ValueError as exc:
        return [SolveResult(
            status="MODEL_INVALID", objective_value=None, sessions=[], wall_time_seconds=0.0,
            diagnostics={"error": str(exc)},
        )]

    results: List[SolveResult] = []
    best_objective = None
    has_objective = bool(mv.objective_terms)

    for k in range(max(1, num_alternatives)):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max_seconds
        solver.parameters.num_search_workers = num_workers
        solver.parameters.random_seed = 12345  # deterministic across runs on identical input
        start_time = time.time()
        status = solver.Solve(mv.model)
        elapsed = time.time() - start_time

        status_name = STATUS_NAMES.get(status, "UNKNOWN")
        if status_name not in ("OPTIMAL", "FEASIBLE"):
            if k == 0:
                results.append(SolveResult(
                    status=status_name, objective_value=None, sessions=[], wall_time_seconds=elapsed,
                ))
            break

        objective_value = solver.ObjectiveValue() if has_objective else 0.0
        sessions = _extract_sessions(problem, mv, solver)
        results.append(SolveResult(
            status=status_name, objective_value=objective_value, sessions=sessions, wall_time_seconds=elapsed,
        ))

        if k == 0 and has_objective and best_objective is None:
            best_objective = objective_value
            slack = max(5, round(best_objective * 0.15))
            weighted_sum = sum(var * weight for var, weight in mv.objective_terms)
            mv.model.Add(weighted_sum <= int(best_objective) + slack)

        if k + 1 >= max(1, num_alternatives):
            break

        # No-good cut: forbid repeating this exact start-assignment so the
        # next solve is forced to differ in at least one placement.
        match_literals = []
        for demand_id, var in mv.start.items():
            value = solver.Value(var)
            match = mv.model.NewBoolVar(f"matchcut_{k}_{demand_id}")
            mv.model.Add(var == value).OnlyEnforceIf(match)
            mv.model.Add(var != value).OnlyEnforceIf(match.Not())
            match_literals.append(match)
        mv.model.Add(sum(match_literals) <= len(match_literals) - 1)

    return results
