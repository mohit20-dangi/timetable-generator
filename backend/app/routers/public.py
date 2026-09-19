from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database
from typing import Optional
from app.db import get_database
from app.services.timetable_views import build_section_grid, build_faculty_grid, build_room_grid

router = APIRouter(prefix="/api/public/timetables", tags=["Public"])


def _default_days(db: Database) -> list:
    slots = list(db.time_slots.find({}))
    if slots:
        canonical = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return sorted({s["day"] for s in slots}, key=lambda d: canonical.index(d) if d in canonical else 99)
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _latest_run(db: Database, run_id: Optional[int]) -> dict:
    if run_id is not None:
        run = db.timetable_runs.find_one({"_id": run_id, "status": "completed"})
        if not run:
            raise HTTPException(status_code=404, detail="Completed timetable run not found")
        return run

    run = db.timetable_runs.find_one({"status": "completed"}, sort=[("completed_at", -1)])
    if not run:
        raise HTTPException(status_code=404, detail="No completed timetable run available yet")
    return run


def _reference_data(db: Database):
    subjects = [{**s, "id": s["_id"]} for s in db.subjects.find({})]
    teachers = [{**t, "id": t["_id"]} for t in db.teachers.find({})]
    rooms = [{**r, "id": r["_id"]} for r in db.rooms.find({})]
    sections = [{**s, "id": s["_id"]} for s in db.sections.find({})]
    return subjects, teachers, rooms, sections


@router.get("/sections")
def list_section_timetables(run_id: Optional[int] = Query(None), db: Database = Depends(get_database)):
    run = _latest_run(db, run_id)
    subjects, teachers, rooms, sections = _reference_data(db)
    days = _default_days(db)
    return {
        "run_id": run["_id"],
        "sections": [
            {"section_id": s["id"], "section_name": s["name"],
             "grid": build_section_grid(run["entries"], s["id"], subjects, teachers, rooms, sections, days)}
            for s in sections
        ],
    }


@router.get("/sections/{section_id}")
def get_section_timetable(section_id: str, run_id: Optional[int] = Query(None), db: Database = Depends(get_database)):
    run = _latest_run(db, run_id)
    if not db.sections.find_one({"_id": section_id}):
        raise HTTPException(status_code=404, detail="Section not found")
    subjects, teachers, rooms, sections = _reference_data(db)
    days = _default_days(db)
    grid = build_section_grid(run["entries"], section_id, subjects, teachers, rooms, sections, days)
    return {"run_id": run["_id"], "section_id": section_id, "grid": grid}


@router.get("/faculty")
def list_faculty_timetables(run_id: Optional[int] = Query(None), db: Database = Depends(get_database)):
    run = _latest_run(db, run_id)
    subjects, teachers, rooms, sections = _reference_data(db)
    days = _default_days(db)
    return {
        "run_id": run["_id"],
        "faculty": [
            {"teacher_id": t["_id"], "teacher_name": t["name"],
             "grid": build_faculty_grid(run["entries"], t["_id"], subjects, teachers, rooms, sections, days)}
            for t in teachers
        ],
    }


@router.get("/faculty/{teacher_id}")
def get_faculty_timetable(teacher_id: str, run_id: Optional[int] = Query(None), db: Database = Depends(get_database)):
    run = _latest_run(db, run_id)
    if not db.teachers.find_one({"_id": teacher_id}):
        raise HTTPException(status_code=404, detail="Teacher not found")
    subjects, teachers, rooms, sections = _reference_data(db)
    days = _default_days(db)
    grid = build_faculty_grid(run["entries"], teacher_id, subjects, teachers, rooms, sections, days)
    return {"run_id": run["_id"], "teacher_id": teacher_id, "grid": grid}


@router.get("/rooms")
def list_room_timetables(run_id: Optional[int] = Query(None), db: Database = Depends(get_database)):
    run = _latest_run(db, run_id)
    subjects, teachers, rooms, sections = _reference_data(db)
    days = _default_days(db)
    time_slots = list(db.time_slots.find({}))
    periods_per_day = max((ts["period_index"] for ts in time_slots), default=8)
    return {
        "run_id": run["_id"],
        "rooms": [
            {"room_id": r["_id"], "room_name": r["name"],
             **build_room_grid(run["entries"], r["_id"], subjects, teachers, rooms, sections, days, periods_per_day)}
            for r in rooms
        ],
    }


@router.get("/rooms/{room_id}")
def get_room_timetable(room_id: str, run_id: Optional[int] = Query(None), db: Database = Depends(get_database)):
    run = _latest_run(db, run_id)
    if not db.rooms.find_one({"_id": room_id}):
        raise HTTPException(status_code=404, detail="Room not found")
    subjects, teachers, rooms, sections = _reference_data(db)
    days = _default_days(db)
    time_slots = list(db.time_slots.find({}))
    periods_per_day = max((ts["period_index"] for ts in time_slots), default=8)
    result = build_room_grid(run["entries"], room_id, subjects, teachers, rooms, sections, days, periods_per_day)
    return {"run_id": run["_id"], "room_id": room_id, **result}
