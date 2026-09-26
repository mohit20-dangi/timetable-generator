"""Pre-flight and post-failure diagnostics, operating on the exact same
ProblemData the solver consumes - no parallel dict format to keep in sync,
and the same hand-built fixtures used in solver tests exercise this too.

Two entry points:
  - preflight_checks(problem): run BEFORE solving. Catches the data
    problems that would make INFEASIBLE inevitable (a subject with no
    eligible teacher/room, a teacher who is the sole option for more
    hours than their weekly cap allows, ...) and reports them in plain
    language with a concrete suggestion - never "check your data".
  - explain_infeasibility(problem): run AFTER the solver reports
    INFEASIBLE. Re-runs the same checks (an INFEASIBLE result usually
    traces back to something preflight already would have caught) and
    adds solver-status context.
"""
from typing import Any, Dict, List
from dataclasses import dataclass

from app.solver.types import ProblemData


@dataclass
class DiagnosticIssue:
    id: str
    severity: str  # blocking | warning
    fact: str
    suggestion: str


def _group_demands(problem: ProblemData):
    groups: Dict[str, List] = {}
    for demand in problem.demands:
        groups.setdefault(f"{demand.subject_id}::{demand.audience_id}", []).append(demand)
    return groups


def preflight_checks(problem: ProblemData) -> List[DiagnosticIssue]:
    issues: List[DiagnosticIssue] = []

    if not problem.slots:
        issues.append(DiagnosticIssue(
            "no_time_slots", "blocking",
            "No timetable time slots are configured.",
            "Add at least one time slot before generating a timetable.",
        ))
        return issues

    if not problem.demands:
        issues.append(DiagnosticIssue(
            "no_demand", "warning",
            "Nothing is schedulable in this scope - either every subject is a MOOC/internship "
            "with no contact hours, or no sections/subjects are mapped yet.",
            "Check SectionSubject mappings and subject delivery modes for this scope.",
        ))
        return issues

    groups = _group_demands(problem)

    # ---- every demand needs at least one eligible room and teacher ----
    seen_missing_room = set()
    seen_missing_teacher = set()
    for demand in problem.demands:
        key = f"{demand.subject_id}:{demand.audience_id}"
        if not demand.eligible_room_ids and key not in seen_missing_room:
            seen_missing_room.add(key)
            issues.append(DiagnosticIssue(
                f"no_room:{key}", "blocking",
                f"{demand.subject_name} (for {demand.audience_id}) has no room matching the "
                f"required type/capacity/equipment.",
                "Add an eligible room, or relax the subject's room-type/equipment requirement.",
            ))
        if not demand.eligible_teacher_ids and key not in seen_missing_teacher:
            seen_missing_teacher.add(key)
            issues.append(DiagnosticIssue(
                f"no_teacher:{key}", "blocking",
                f"{demand.subject_name} (for {demand.audience_id}) has no teacher qualified to "
                f"teach it.",
                f"Assign at least one teacher to {demand.subject_name} via Teacher-Subject mapping.",
            ))

    # ---- lab batches needing more simultaneous teachers than exist ----
    by_subject_section_session: Dict[tuple, List] = {}
    for demand in problem.demands:
        if demand.audience_type == "batch":
            key = (demand.subject_id, demand.parent_section_id, demand.session_index)
            by_subject_section_session.setdefault(key, []).append(demand)
    for (subject_id, section_id, _idx), batch_demands in by_subject_section_session.items():
        num_batches = len(batch_demands)
        teacher_pool = set()
        for d in batch_demands:
            teacher_pool.update(d.eligible_teacher_ids)
        # Phase 2.9: "sequential" and "merged" are explicit hard modes that
        # PROVABLY never need a different teacher per batch - sequential
        # because sibling batches are never at the same time (same teacher
        # can cover all of them, one after another), merged because they
        # deliberately share one teacher by construction. "independent"
        # keeps the old conservative assumption (the solver is still free
        # to schedule them in parallel, so warn early) and "parallel" of
        # course needs one teacher per simultaneous batch.
        mode = batch_demands[0].batch_mode
        needs_distinct_teachers = mode in ("independent", "parallel")
        required_teachers = num_batches if needs_distinct_teachers else 1
        if num_batches > 1 and len(teacher_pool) < required_teachers:
            issues.append(DiagnosticIssue(
                f"insufficient_lab_teachers:{subject_id}:{section_id}", "blocking",
                f"{batch_demands[0].subject_name} splits into {num_batches} simultaneous lab "
                f"batches for section {section_id}, but only {len(teacher_pool)} teacher(s) are "
                f"qualified to teach it.",
                (
                    f"Qualify at least {required_teachers} teacher(s) for this subject"
                    + (
                        ", since all batches run in the same week and may need to run in parallel."
                        if needs_distinct_teachers
                        else "."
                    )
                ),
            ))

    # ---- resource-capacity arithmetic: a teacher who is the ONLY option
    # for more combined hours than their weekly cap allows makes the
    # model infeasible regardless of how the solver searches. ----
    sole_teacher_load: Dict[str, int] = {}
    sole_teacher_subjects: Dict[str, List[str]] = {}
    for group_key, group_demands in groups.items():
        eligible = set(group_demands[0].eligible_teacher_ids)
        if len(eligible) == 1:
            teacher_id = next(iter(eligible))
            hours = sum(d.duration for d in group_demands)
            sole_teacher_load[teacher_id] = sole_teacher_load.get(teacher_id, 0) + hours
            sole_teacher_subjects.setdefault(teacher_id, []).append(group_demands[0].subject_name)
    for teacher_id, load in sole_teacher_load.items():
        teacher = problem.teachers.get(teacher_id)
        cap = teacher.max_weekly_hours if teacher else None
        if cap is not None and load > cap:
            subjects_list = ", ".join(sorted(set(sole_teacher_subjects[teacher_id])))
            issues.append(DiagnosticIssue(
                f"teacher_overloaded:{teacher_id}", "blocking",
                f"{teacher_id} is the only eligible teacher for {subjects_list}, which together "
                f"need {load} hours/week, but their cap is {cap} hours/week.",
                f"Raise {teacher_id}'s weekly hour cap to at least {load}, or qualify another "
                "teacher for one of these subjects.",
            ))

    # ---- room-type capacity: soft warning, not blocking (combinatorial fit still possible) ----
    demand_hours_by_room_type: Dict[str, int] = {}
    for demand in problem.demands:
        if demand.room_type:
            demand_hours_by_room_type[demand.room_type] = (
                demand_hours_by_room_type.get(demand.room_type, 0) + demand.duration
            )
    rooms_by_type: Dict[str, int] = {}
    for room in problem.rooms.values():
        rooms_by_type[room.type] = rooms_by_type.get(room.type, 0) + 1
    total_slots = len(problem.slots)
    for room_type, demand_hours in demand_hours_by_room_type.items():
        supply_hours = rooms_by_type.get(room_type, 0) * total_slots
        if supply_hours and demand_hours > supply_hours:
            issues.append(DiagnosticIssue(
                f"room_type_tight:{room_type}", "warning",
                f"{room_type} rooms need {demand_hours} room-hours/week across all demand, but "
                f"only {supply_hours} room-hours/week exist across {rooms_by_type.get(room_type, 0)} "
                f"room(s).",
                f"Add another {room_type} room, or reduce {room_type} demand.",
            ))

    return issues


def explain_infeasibility(problem: ProblemData, solver_status: str = "INFEASIBLE") -> Dict[str, Any]:
    issues = preflight_checks(problem)
    return {
        "solver_status": solver_status,
        "summary": {
            "sections": len({d.parent_section_id for d in problem.demands}),
            "demands": len(problem.demands),
            "teachers": len(problem.teachers),
            "rooms": len(problem.rooms),
            "time_slots": len(problem.slots),
        },
        "issues": [
            {"id": i.id, "severity": i.severity, "fact": i.fact, "suggestion": i.suggestion}
            for i in issues
        ],
    }


def format_diagnostics(report: Dict[str, Any]) -> str:
    lines = [
        f"Verified solver status: {report.get('solver_status', 'UNKNOWN')}.",
        "Verified diagnostics (only these facts should be used in an explanation):",
    ]
    issues = report.get("issues", [])
    if not issues:
        lines.append("- The basic data checks passed, but the complete timetable cannot fit all classes together.")
        lines.append("- This usually means shared teachers or rooms are over-constrained when all sections are scheduled together.")
        lines.append("- Review teacher maximum classes per day, maximum consecutive classes, room availability, hard unavailable-time rules, and continuous lab blocks.")
        lines.append("- Try generating one year or fewer sections first. If that works, add another teacher or increase only the affected teachers' limits.")
    for issue in issues:
        lines.append(f"- [{issue['id']}] {issue['fact']} Suggested action: {issue['suggestion']}")
    return "\n".join(lines)
