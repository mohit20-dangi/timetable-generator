from datetime import time
from typing import Any, Dict, List


def _parse_time(value: Any) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _slot_in_range(slot: Dict[str, Any], rule: Dict[str, Any]) -> bool:
    if rule.get("day") and slot.get("day") != rule["day"]:
        return False
    start = _parse_time(rule.get("start_time"))
    end = _parse_time(rule.get("end_time"))
    if not start or not end:
        return True
    slot_start = _parse_time(slot.get("start_time"))
    slot_end = _parse_time(slot.get("end_time"))
    return bool(slot_start and slot_end and slot_start < end and start < slot_end)


def _eligible_teachers(subject_id: str, constraints: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [teacher for teacher in constraints.get("teachers", []) if subject_id in teacher.get("subjects", [])]


def _eligible_rooms(subject: Dict[str, Any], strength: int, constraints: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        room for room in constraints.get("rooms", [])
        if (subject.get("requires_room_type") is None or room.get("type") == subject.get("requires_room_type"))
        and room.get("capacity", 0) >= strength
        and all(item in room.get("equipment", []) for item in subject.get("requires_equipment", []))
    ]


def diagnose_infeasibility(constraints: Dict[str, Any], solver_status: str = "INFEASIBLE") -> Dict[str, Any]:
    """Produce verified, deterministic facts for an infeasible model.

    This intentionally reports only checks that can be proven from the assembled
    input data. The LLM receives this object as evidence and is not asked to
    discover additional causes.
    """
    slots = constraints.get("time_slots", [])
    if not slots:
        slots = [
            {"day": day, "period_index": period, "start_time": None, "end_time": None}
            for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            for period in range(1, 9)
        ]
    subjects = {item["id"]: item for item in constraints.get("subjects", [])}
    sections = constraints.get("sections", [])
    section_subjects = constraints.get("section_subjects", {})
    lab_batches = constraints.get("lab_batches", [])
    issues: List[Dict[str, Any]] = []

    if not slots:
        issues.append({
            "id": "no_time_slots",
            "severity": "blocking",
            "fact": "No timetable time slots are configured.",
            "suggestion": "Add at least one TimeSlot before generating a timetable.",
        })

    for section in sections:
        section_id = section["id"]
        strength = section.get("strength", 0)
        for subject_id in section_subjects.get(section_id, []):
            subject = subjects.get(subject_id)
            if not subject:
                issues.append({
                    "id": f"missing_subject:{section_id}:{subject_id}",
                    "severity": "blocking",
                    "fact": f"Section {section_id} references missing subject {subject_id}.",
                    "suggestion": "Add the subject or remove the section-subject mapping.",
                })
                continue
            if subject.get("type") == "lab":
                continue
            teachers = _eligible_teachers(subject_id, constraints)
            rooms = _eligible_rooms(subject, strength, constraints)
            if not teachers:
                issues.append({
                    "id": f"no_teacher:{section_id}:{subject_id}",
                    "severity": "blocking",
                    "fact": f"Subject {subject_id} for section {section_id} has no teacher assigned to it.",
                    "suggestion": f"Assign at least one teacher to subject {subject_id}.",
                })
            if not rooms:
                issues.append({
                    "id": f"no_room:{section_id}:{subject_id}",
                    "severity": "blocking",
                    "fact": f"Subject {subject_id} for section {section_id} has no room matching capacity, type, and equipment.",
                    "suggestion": "Add an eligible room or reduce the section size/room requirements.",
                })

    for batch in lab_batches:
        section_id = batch["section_id"]
        for subject_id in section_subjects.get(section_id, []):
            subject = subjects.get(subject_id)
            if not subject or subject.get("type") != "lab":
                continue
            teachers = _eligible_teachers(subject_id, constraints)
            rooms = [
                room for room in _eligible_rooms(subject, batch.get("strength", 0), constraints)
                if room.get("type") == "lab"
            ]
            if not teachers:
                issues.append({
                    "id": f"no_lab_teacher:{batch['id']}:{subject_id}",
                    "severity": "blocking",
                    "fact": f"Lab {subject_id} for batch {batch['id']} has no eligible teacher.",
                    "suggestion": f"Assign a teacher to lab subject {subject_id}.",
                })
            if not rooms:
                issues.append({
                    "id": f"no_lab_room:{batch['id']}:{subject_id}",
                    "severity": "blocking",
                    "fact": f"Lab {subject_id} for batch {batch['id']} has no eligible laboratory room.",
                    "suggestion": "Add a lab room with sufficient capacity and required equipment.",
                })

    for rule in constraints.get("structured_constraints", []):
        if rule.get("priority") != "hard":
            continue
        if rule.get("rule_type") in {"teacher_unavailable", "section_unavailable", "room_unavailable"}:
            matching_slots = [slot for slot in slots if _slot_in_range(slot, rule)]
            if not matching_slots:
                issues.append({
                    "id": f"empty_rule_window:{rule.get('id', 'unknown')}",
                    "severity": "blocking",
                    "fact": f"Hard rule {rule.get('id', 'unknown')} targets no configured time slots.",
                    "suggestion": "Adjust the rule day/time or configure matching time slots.",
                })

    return {
        "solver_status": solver_status,
        "summary": {
            "sections": len(sections),
            "subjects": len(subjects),
            "teachers": len(constraints.get("teachers", [])),
            "rooms": len(constraints.get("rooms", [])),
            "time_slots": len(slots),
        },
        "issues": issues,
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
