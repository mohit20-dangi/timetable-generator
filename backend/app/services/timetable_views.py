"""Turn a solved run's flat entry list into the per-audience views people
actually want: one grid per section, one per teacher, one per room.

The solver's only job is to decide *what goes where*. Everything here is
plain, deterministic Python over that result — no LLM involved.
"""
from typing import Any, Dict, List, Optional


def _reference_maps(subjects: List[dict], teachers: List[dict], rooms: List[dict], sections: List[dict]):
    return (
        {s["id"]: s for s in subjects},
        {t["id"]: t for t in teachers},
        {r["id"]: r for r in rooms},
        {s["id"]: s for s in sections},
    )


def _entry_cell(entry: dict, subject_map: dict, teacher_map: dict, room_map: dict,
                 section_map: dict, batch_names: Dict[str, str]) -> Dict[str, Any]:
    subject = subject_map.get(entry["subject_id"], {})
    teacher = teacher_map.get(entry["teacher_id"], {})
    room = room_map.get(entry["room_id"], {})
    section = section_map.get(entry.get("section_id"), {}) if entry.get("section_id") else None
    cell = {
        "subject_id": entry["subject_id"],
        "subject_name": subject.get("name"),
        "subject_type": subject.get("type"),
        "teacher_id": entry["teacher_id"],
        "teacher_name": teacher.get("name"),
        "room_id": entry["room_id"],
        "room_name": room.get("name"),
    }
    if section is not None:
        cell["section_id"] = section["id"]
        cell["section_name"] = section.get("name")
    if entry.get("batch_id"):
        cell["batch_id"] = entry["batch_id"]
        cell["batch_name"] = batch_names.get(entry["batch_id"])
    return cell


def _empty_grid(days: List[str]) -> Dict[str, Dict[int, Any]]:
    return {day: {} for day in days}


def build_all_grids(
    entries: List[dict],
    subjects: List[dict],
    teachers: List[dict],
    rooms: List[dict],
    sections: List[dict],
    days: List[str],
) -> Dict[str, Any]:
    """Build the section/faculty/room grids in one pass over the entries."""
    subject_map, teacher_map, room_map, section_map = _reference_maps(subjects, teachers, rooms, sections)
    batch_names = {
        b["id"]: b["batch_name"]
        for s in sections
        for b in s.get("lab_batches", [])
    }
    batch_section = {
        b["id"]: s["id"]
        for s in sections
        for b in s.get("lab_batches", [])
    }

    section_grids: Dict[str, Dict[str, Dict[int, Any]]] = {}
    faculty_grids: Dict[str, Dict[str, Dict[int, Any]]] = {}
    room_grids: Dict[str, Dict[str, Dict[int, Any]]] = {}

    for entry in entries:
        cell = _entry_cell(entry, subject_map, teacher_map, room_map, section_map, batch_names)

        # A lab-batch entry belongs to its parent section's timetable too.
        owning_section_id = entry.get("section_id") or batch_section.get(entry.get("batch_id"))
        if owning_section_id:
            grid = section_grids.setdefault(owning_section_id, _empty_grid(days))
            grid.setdefault(entry["day"], {})[entry["period"]] = cell

        teacher_id = entry["teacher_id"]
        grid = faculty_grids.setdefault(teacher_id, _empty_grid(days))
        grid.setdefault(entry["day"], {})[entry["period"]] = cell

        room_id = entry["room_id"]
        grid = room_grids.setdefault(room_id, _empty_grid(days))
        grid.setdefault(entry["day"], {})[entry["period"]] = cell

    return {"sections": section_grids, "faculty": faculty_grids, "rooms": room_grids}


def build_section_grid(entries: List[dict], section_id: str, subjects, teachers, rooms, sections, days) -> Dict[str, Any]:
    return build_all_grids(entries, subjects, teachers, rooms, sections, days)["sections"].get(section_id, _empty_grid(days))


def build_faculty_grid(entries: List[dict], teacher_id: str, subjects, teachers, rooms, sections, days) -> Dict[str, Any]:
    return build_all_grids(entries, subjects, teachers, rooms, sections, days)["faculty"].get(teacher_id, _empty_grid(days))


def build_room_grid(
    entries: List[dict], room_id: str, subjects, teachers, rooms, sections, days,
    periods_per_day: Optional[int] = None,
) -> Dict[str, Any]:
    occupied = build_all_grids(entries, subjects, teachers, rooms, sections, days)["rooms"].get(room_id, _empty_grid(days))
    if periods_per_day is None:
        return {"occupied": occupied}

    free: Dict[str, List[int]] = {}
    for day in days:
        booked_periods = set(occupied.get(day, {}).keys())
        free[day] = [p for p in range(1, periods_per_day + 1) if p not in booked_periods]
    return {"occupied": occupied, "free": free}
