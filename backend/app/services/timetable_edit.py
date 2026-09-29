"""Natural-language timetable editing.

The LLM only ever proposes *operations* against the existing entry list
(move / reassign_room / reassign_teacher / swap / delete) - it never invents
new entries or touches the database directly. Everything here is
deterministic Python: matching an operation to a concrete entry, simulating
the result, and checking it against the same hard rules the solver enforces
(no double-booking, room/teacher eligibility). The LLM's output is treated as
untrusted input that must resolve and validate before anything is applied.
"""
from typing import Any, Dict, List, Optional, Tuple
from pymongo.database import Database


def build_edit_context(db: Database, entries: List[dict]) -> Dict[str, Any]:
    subjects = {s["_id"]: s for s in db.subjects.find({})}
    teachers = {t["_id"]: t for t in db.teachers.find({})}
    rooms = {r["_id"]: r for r in db.rooms.find({})}
    sections = {s["_id"]: s for s in db.sections.find({})}
    batch_names = {b["id"]: b["batch_name"] for s in sections.values() for b in s.get("lab_batches", [])}

    def entry_summary(e: dict) -> dict:
        return {
            "day": e["day"],
            "period": e["period"],
            "section_id": e.get("section_id"),
            "section_name": sections.get(e.get("section_id"), {}).get("name"),
            "batch_id": e.get("batch_id"),
            "batch_name": batch_names.get(e.get("batch_id")),
            "subject_id": e["subject_id"],
            "subject_name": subjects.get(e["subject_id"], {}).get("name"),
            "teacher_id": e["teacher_id"],
            "teacher_name": teachers.get(e["teacher_id"], {}).get("name"),
            "room_id": e["room_id"],
            "room_name": rooms.get(e["room_id"], {}).get("name"),
        }

    return {
        "subjects": subjects,
        "teachers": teachers,
        "rooms": rooms,
        "sections": sections,
        "batch_names": batch_names,
        "entries_summary": [entry_summary(e) for e in entries],
        "teachers_list": [{"id": t["_id"], "name": t["name"]} for t in teachers.values()],
        "rooms_list": [{"id": r["_id"], "name": r["name"], "type": r.get("type")} for r in rooms.values()],
    }


def describe_entry(e: dict, context: Dict[str, Any]) -> str:
    subject = context["subjects"].get(e["subject_id"], {}).get("name", e["subject_id"])
    teacher = context["teachers"].get(e["teacher_id"], {}).get("name", e["teacher_id"])
    room = context["rooms"].get(e["room_id"], {}).get("name", e["room_id"])
    who = context["sections"].get(e.get("section_id"), {}).get("name") or context["batch_names"].get(e.get("batch_id")) or "?"
    return f"{subject} for {who} ({teacher}, {room}) on {e['day']} P{e['period']}"


def _find_matching_indices(entries: List[dict], match: Dict[str, Any]) -> List[int]:
    keys = [k for k, v in (match or {}).items() if v is not None and k in
            ("day", "period", "section_id", "batch_id", "subject_id", "teacher_id", "room_id")]
    if not keys:
        return []
    return [i for i, e in enumerate(entries) if all(e.get(k) == match[k] for k in keys)]


def resolve_operations(
    entries: List[dict], llm_ops: List[Dict[str, Any]], context: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    resolved: List[Dict[str, Any]] = []
    errors: List[str] = []

    for op in llm_ops:
        op_type = op.get("op")
        indices = _find_matching_indices(entries, op.get("match", {}))
        if len(indices) == 0:
            errors.append(f"Could not find a class matching {op.get('match')}")
            continue
        if len(indices) > 1:
            errors.append(f"That description matches {len(indices)} classes - please be more specific")
            continue
        idx = indices[0]
        entry = entries[idx]

        if op_type == "move":
            if not op.get("day") or not op.get("period"):
                errors.append("A 'move' operation is missing the new day/period")
                continue
            resolved.append({
                "entry_index": idx,
                "field_changes": {"day": op["day"], "period": op["period"]},
                "delete": False,
                "description": f"Move {describe_entry(entry, context)} to {op['day']} P{op['period']}",
            })

        elif op_type == "reassign_room":
            if not op.get("room_id"):
                errors.append("A 'reassign_room' operation is missing the new room_id")
                continue
            resolved.append({
                "entry_index": idx,
                "field_changes": {"room_id": op["room_id"]},
                "delete": False,
                "description": f"Move {describe_entry(entry, context)} to room {context['rooms'].get(op['room_id'], {}).get('name', op['room_id'])}",
            })

        elif op_type == "reassign_teacher":
            if not op.get("teacher_id"):
                errors.append("A 'reassign_teacher' operation is missing the new teacher_id")
                continue
            resolved.append({
                "entry_index": idx,
                "field_changes": {"teacher_id": op["teacher_id"]},
                "delete": False,
                "description": f"Reassign {describe_entry(entry, context)} to {context['teachers'].get(op['teacher_id'], {}).get('name', op['teacher_id'])}",
            })

        elif op_type == "delete":
            resolved.append({
                "entry_index": idx,
                "field_changes": {},
                "delete": True,
                "description": f"Remove {describe_entry(entry, context)}",
            })

        elif op_type == "swap":
            indices_b = _find_matching_indices(entries, op.get("match_b", {}))
            if len(indices_b) != 1:
                errors.append(f"Could not uniquely identify the second class to swap with ({op.get('match_b')})")
                continue
            idx_b = indices_b[0]
            if idx_b == idx:
                errors.append("The swap matched the same class twice")
                continue
            entry_b = entries[idx_b]

            swap_field = op.get("swap_field", "slot")
            field_map = {"slot": ["day", "period"], "room": ["room_id"], "teacher": ["teacher_id"]}
            if swap_field not in field_map:
                errors.append(f"Unknown swap_field '{swap_field}'")
                continue
            fields = field_map[swap_field]

            a_vals = {f: entry[f] for f in fields}
            b_vals = {f: entry_b[f] for f in fields}
            description = f"Swap {swap_field} between {describe_entry(entry, context)} and {describe_entry(entry_b, context)}"
            resolved.append({"entry_index": idx, "field_changes": b_vals, "delete": False, "description": description})
            resolved.append({"entry_index": idx_b, "field_changes": a_vals, "delete": False, "description": description})

        else:
            errors.append(f"Unknown operation type '{op_type}'")

    return resolved, errors


def simulate(entries: List[dict], resolved_ops: List[Dict[str, Any]]) -> List[dict]:
    working: List[Optional[dict]] = [dict(e) for e in entries]
    for op in resolved_ops:
        idx = op["entry_index"]
        if idx < 0 or idx >= len(working) or working[idx] is None:
            continue
        if op.get("delete"):
            working[idx] = None
        else:
            working[idx] = {**working[idx], **op.get("field_changes", {})}
    return [e for e in working if e is not None]


def find_conflicts(simulated_entries: List[dict], context: Dict[str, Any]) -> List[str]:
    conflicts: List[str] = []
    seen_entity_slot = set()
    seen_room_slot = set()
    seen_teacher_slot = set()

    for e in simulated_entries:
        slot = (e["day"], e["period"])
        entity_id = e.get("section_id") or e.get("batch_id")

        entity_key = (entity_id, slot)
        if entity_id and entity_key in seen_entity_slot:
            who = context["sections"].get(entity_id, {}).get("name") or context["batch_names"].get(entity_id, entity_id)
            conflicts.append(f"{who} is double-booked on {e['day']} P{e['period']}")
        seen_entity_slot.add(entity_key)

        teacher_key = (e["teacher_id"], slot)
        if teacher_key in seen_teacher_slot:
            name = context["teachers"].get(e["teacher_id"], {}).get("name", e["teacher_id"])
            conflicts.append(f"{name} is double-booked on {e['day']} P{e['period']}")
        seen_teacher_slot.add(teacher_key)

        room_key = (e["room_id"], slot)
        if room_key in seen_room_slot:
            name = context["rooms"].get(e["room_id"], {}).get("name", e["room_id"])
            conflicts.append(f"Room {name} is double-booked on {e['day']} P{e['period']}")
        seen_room_slot.add(room_key)

        subject = context["subjects"].get(e["subject_id"])
        teacher = context["teachers"].get(e["teacher_id"])
        room = context["rooms"].get(e["room_id"])

        if teacher and e["subject_id"] not in teacher.get("subject_ids", []):
            subj_name = subject.get("name") if subject else e["subject_id"]
            conflicts.append(f"{teacher.get('name', e['teacher_id'])} is not eligible to teach {subj_name}")

        if room and subject and subject.get("requires_room_type") and room.get("type") != subject["requires_room_type"]:
            conflicts.append(
                f"Room {room.get('name', e['room_id'])} is a {room.get('type')} room, "
                f"but {subject.get('name', e['subject_id'])} requires a {subject['requires_room_type']} room"
            )

    seen = set()
    deduped = []
    for c in conflicts:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped
