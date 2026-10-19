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
from typing import Optional, Any, Dict, List
from dataclasses import dataclass

from app.solver.calendar import occupied_indices
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
        if demand.self_study:
            continue  # needs neither a room nor a teacher
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
        #
        # Phase 3.1: a lab in a ROTATION never needs one teacher per batch
        # either, and this is the single most important case to get right -
        # it is why admins kept being told to hire three lab teachers for a
        # subject that only ever runs with one batch at a time. A rotation
        # runs each of its labs once per round, so one qualified teacher
        # covers it; what it does need is `teachers_required` of them, the
        # same as any other subject.
        per_session_teachers = max(1, batch_demands[0].teachers_required)
        mode = batch_demands[0].batch_mode
        in_rotation = bool(batch_demands[0].rotation_group_id)
        needs_distinct_teachers = (not in_rotation) and mode in ("independent", "parallel")
        required_teachers = (
            num_batches * per_session_teachers if needs_distinct_teachers else per_session_teachers
        )
        if num_batches > 1 and len(teacher_pool) < required_teachers:
            if needs_distinct_teachers:
                fact = (
                    f"{batch_demands[0].subject_name} splits into {num_batches} simultaneous lab "
                    f"batches for section {section_id}, but only {len(teacher_pool)} teacher(s) are "
                    f"qualified to teach it."
                )
                suggestion = (
                    f"Either qualify at least {required_teachers} teacher(s) for this subject, or - "
                    "usually the cheaper fix - stop running all its batches at once: put it in a lab "
                    "rotation with the section's other labs, so each batch is in a different lab at "
                    "any one time and one teacher per lab is enough. Setting its batch scheduling "
                    "mode to 'sequential' also works."
                )
            else:
                fact = (
                    f"{batch_demands[0].subject_name} for section {section_id} needs "
                    f"{per_session_teachers} teachers in the room at once, but only "
                    f"{len(teacher_pool)} teacher(s) are qualified to teach it."
                )
                suggestion = (
                    f"Qualify at least {per_session_teachers} teacher(s) for this subject, or lower "
                    "its 'teachers required' setting."
                )
            issues.append(DiagnosticIssue(
                f"insufficient_lab_teachers:{subject_id}:{section_id}", "blocking", fact, suggestion,
            ))

    # ---- a subject that needs more teachers at once than are qualified ----
    seen_short_staffed = set()
    for demand in problem.demands:
        required = max(1, demand.teachers_required)
        eligible = set(demand.eligible_teacher_ids)
        key = f"{demand.subject_id}:{demand.audience_id}"
        # No qualified teacher at all is already reported above, in the
        # terms the admin needs ("assign a teacher via Teacher-Subject
        # mapping"). Saying it again as "needs 1 teacher, has 0" would add
        # a second, vaguer line about the same single missing mapping.
        if not eligible or required <= len(eligible) or key in seen_short_staffed:
            continue
        seen_short_staffed.add(key)
        issues.append(DiagnosticIssue(
            f"teachers_required_short:{key}", "blocking",
            f"{demand.subject_name} (for {demand.audience_id}) is set to need {required} teachers "
            f"at the same time, but only {len(eligible)} teacher(s) are qualified to teach it.",
            f"Qualify at least {required} teacher(s) for {demand.subject_name} via Teacher-Subject "
            "mapping, or lower its 'teachers required' setting.",
        ))

    # ---- lab rotations: structurally impossible shapes ----
    for rotation in problem.rotation_groups:
        members = [
            d for d in problem.demands
            if d.rotation_group_id == rotation.id and d.audience_type == "batch"
        ]
        if not members:
            continue
        batch_ids = {d.audience_id for d in members}
        num_rounds = len({(d.subject_id, d.session_index) for d in members})
        # Each round holds one batch per lab, so a rotation can never move
        # more batches than it has rounds - two of them would have to share
        # a lab, which is exactly the simultaneous-batches problem the
        # rotation was set up to avoid.
        if len(batch_ids) > num_rounds:
            issues.append(DiagnosticIssue(
                f"rotation_too_few_rounds:{rotation.id}", "blocking",
                f"Lab rotation '{rotation.label}' moves {len(batch_ids)} batches through "
                f"{num_rounds} lab session(s), so at least two batches would have to be in the "
                "same lab at the same time.",
                f"Add another lab to the rotation (it needs at least {len(batch_ids)} lab sessions "
                "a week in total), give its labs more sessions per week, or use fewer batches.",
            ))
        incomplete = sorted(
            batch_id for batch_id in batch_ids
            if {d.subject_id for d in members if d.audience_id == batch_id} != set(rotation.subject_ids)
        )
        if incomplete:
            issues.append(DiagnosticIssue(
                f"rotation_incomplete:{rotation.id}", "blocking",
                f"Lab rotation '{rotation.label}': batch(es) {', '.join(incomplete)} do not take "
                "every lab in the rotation.",
                "Every batch in a rotation must take every lab in it - check the section's lab "
                "batches and its subject mapping, or remove the odd lab from the rotation.",
            ))

    # ---- an elective basket holding a section-level class AND a batch-level
    # one for the same cohort. Basket members are ALTERNATIVES - a student
    # picks one - so the model forces them all onto the same start slot.
    # That is right for two options a student chooses between, and
    # unsatisfiable by construction for a theory and its own lab, which the
    # same students both attend: the section-level class and the batch class
    # would have to run at once, and the audience no-overlap rightly forbids
    # it. The solver can only report a bare INFEASIBLE, so name it here. ----
    elective_clusters: Dict[tuple, List] = {}
    for demand in problem.demands:
        if demand.elective_group_id:
            key = (demand.elective_group_id, demand.session_index, demand.parent_section_id)
            elective_clusters.setdefault(key, []).append(demand)
    for (group_id, _idx, section_id), members in elective_clusters.items():
        kinds = {d.audience_type for d in members}
        if len(kinds) < 2:
            continue
        section_level = sorted({d.subject_name for d in members if d.audience_type == "section"})
        batch_level = sorted({d.subject_name for d in members if d.audience_type == "batch"})
        issues.append(DiagnosticIssue(
            f"elective_mixes_section_and_batch:{group_id}:{section_id}", "blocking",
            f"Elective group {group_id} asks {', '.join(section_level)} (taught to the whole "
            f"section) and {', '.join(batch_level)} (taught to lab batches) to run at the same "
            f"time for section {section_id}. Options in one basket run together because a student "
            "picks only one of them - but these students take both, so they can never be "
            "scheduled at the same time.",
            "If these are the theory and lab parts of ONE elective, take the lab out of the "
            "elective group - it is a component of that elective, not an alternative to it. Link "
            "them with the same linked_group_id instead, and the lab will be scheduled on its own.",
        ))

    # ---- resource-capacity arithmetic: a teacher who is the ONLY option
    # for more combined hours than their weekly cap allows makes the
    # model infeasible regardless of how the solver searches. ----
    sole_teacher_load: Dict[str, int] = {}
    sole_teacher_subjects: Dict[str, List[str]] = {}
    for group_key, group_demands in groups.items():
        eligible = set(group_demands[0].eligible_teacher_ids)
        # A subject needing N teachers at once out of exactly N qualified
        # ones commits all N of them, not just a lone teacher - so the same
        # "their caps cannot cover this" arithmetic has to count every one.
        required = max(1, group_demands[0].teachers_required)
        if eligible and len(eligible) == required:
            hours = sum(d.duration for d in group_demands)
            for teacher_id in eligible:
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

    # ---- hard admin-defined time-window rules (app/solver/custom_rules.py):
    # if a subject needs more sessions than the days its allowed window
    # leaves it (each day holds at most max_per_day of them), no solver
    # search can succeed - name the rule instead of a bare INFEASIBLE. ----
    slots_by_index = {sl.index: sl for sl in problem.slots}
    for rule in problem.custom_rules:
        if not (rule.hard and rule.kind == "subject_time_window"):
            continue
        for group_key, group_demands in groups.items():
            if group_demands[0].subject_id != rule.target_id:
                continue
            allowed_days = set()
            for start in set().union(*(d.valid_start_slot_indices for d in group_demands)):
                occupied = set(occupied_indices(start, group_demands[0].duration, slots_by_index))
                ok = occupied <= rule.slot_indices if rule.mode == "within" else not (occupied & rule.slot_indices)
                if ok:
                    allowed_days.add(slots_by_index[start].day)
            capacity = len(allowed_days) * group_demands[0].max_per_day
            if len(group_demands) > capacity:
                name = group_demands[0].subject_name
                issues.append(DiagnosticIssue(
                    f"custom_window_too_tight:{rule.label}:{group_demands[0].audience_id}", "blocking",
                    f"The rule '{rule.label}' ({rule.mode} its time window) leaves {name} "
                    f"(for {group_demands[0].audience_id}) room for only {capacity} session(s) a week "
                    f"({len(allowed_days)} day(s) x {group_demands[0].max_per_day} per day), "
                    f"but it needs {len(group_demands)}.",
                    "Widen the rule's time window, make it a soft preference, or reduce that subject's hours.",
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


def explain_infeasibility(
    problem: ProblemData, solver_status: str = "INFEASIBLE", solver_error: Optional[str] = None,
) -> Dict[str, Any]:
    issues = preflight_checks(problem)
    if solver_error:
        # The model builder rejected the problem outright (e.g. a hard rule
        # leaves a class no possible time) - its message is already specific
        # and actionable, so it leads the report instead of being dropped.
        issues.insert(0, DiagnosticIssue(
            "model_invalid", "blocking", solver_error,
            "Fix the data or rule named above, then generate again.",
        ))
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
