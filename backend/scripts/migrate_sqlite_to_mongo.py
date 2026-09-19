"""Best-effort one-off copy of an existing backend/timetable.db (the old
SQLAlchemy/SQLite store) into MongoDB, applying the same embedding
transformations the new models use (teacher_subjects -> Teacher.subject_ids,
section_subjects/lab_batches -> embedded on Section, prerequisites ->
Subject.prerequisite_ids, generated_entries -> embedded on TimetableRun).

Not required to run - the app works fine starting from an empty Mongo
database. Use this only if there's SQLite dev data worth keeping.

Run from backend/, with the venv active:
    python scripts/migrate_sqlite_to_mongo.py [path-to-timetable.db]
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_database  # noqa: E402


def rows(conn, table):
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    except sqlite3.OperationalError:
        return []


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "timetable.db"
    if not Path(db_path).exists():
        print(f"No SQLite file found at {db_path}; nothing to migrate.")
        return

    conn = sqlite3.connect(db_path)
    db = get_database()

    years = rows(conn, "academic_years")
    sections = rows(conn, "sections")
    subjects = rows(conn, "subjects")
    teachers = rows(conn, "teachers")
    rooms = rows(conn, "rooms")
    teacher_subjects = rows(conn, "teacher_subjects")
    section_subjects = rows(conn, "section_subjects")
    lab_batches = rows(conn, "lab_batches")
    prerequisites = rows(conn, "prerequisites")
    time_slots = rows(conn, "time_slots")
    constraint_profiles = rows(conn, "constraint_profiles")
    timetable_runs = rows(conn, "timetable_runs")
    generated_entries = rows(conn, "generated_entries")

    if years:
        db.academic_years.insert_many([
            {"_id": y["id"], "name": y["name"], "lunch_start": y.get("lunch_start"), "lunch_end": y.get("lunch_end")}
            for y in years
        ])

    teacher_subject_map = {}
    for ts in teacher_subjects:
        teacher_subject_map.setdefault(ts["teacher_id"], []).append(ts["subject_id"])

    if teachers:
        db.teachers.insert_many([
            {
                "_id": t["id"], "name": t["name"], "department": t.get("department"),
                "subject_ids": teacher_subject_map.get(t["id"], []),
                "max_continuous_classes": t.get("max_continuous_classes", 3),
                "max_daily_classes": t.get("max_daily_classes", 5),
                "availability": json.loads(t["availability"]) if t.get("availability") else [],
                "preferred_slots": json.loads(t["preferred_slots"]) if t.get("preferred_slots") else [],
                "is_guest_from_other_dept": bool(t.get("is_guest_from_other_dept")),
            }
            for t in teachers
        ])

    if rooms:
        db.rooms.insert_many([
            {
                "_id": r["id"], "name": r["name"], "type": r["type"], "capacity": r.get("capacity", 60),
                "equipment": json.loads(r["equipment"]) if r.get("equipment") else [],
                "shared_with_departments": json.loads(r["shared_with_departments"]) if r.get("shared_with_departments") else [],
                "availability": json.loads(r["availability"]) if r.get("availability") else [],
            }
            for r in rooms
        ])

    prereq_map = {}
    for p in prerequisites:
        prereq_map.setdefault(p["subject_id"], []).append(p["requires_subject_id"])

    if subjects:
        db.subjects.insert_many([
            {
                "_id": s["id"], "name": s["name"], "type": s["type"], "weekly_hours": s.get("weekly_hours", 0),
                "needs_continuous_block": bool(s.get("needs_continuous_block")),
                "block_size": s.get("block_size", 1), "requires_room_type": s.get("requires_room_type"),
                "requires_equipment": json.loads(s["requires_equipment"]) if s.get("requires_equipment") else [],
                "prerequisite_ids": prereq_map.get(s["id"], []),
            }
            for s in subjects
        ])

    section_subj_map = {}
    for ss in section_subjects:
        section_subj_map.setdefault(ss["section_id"], []).append({
            "subject_id": ss["subject_id"],
            "is_elective": bool(ss.get("is_elective")),
            "elective_group_id": ss.get("elective_group_id"),
        })

    batch_map = {}
    for b in lab_batches:
        batch_map.setdefault(b["section_id"], []).append({
            "id": b["id"], "batch_name": b["batch_name"], "strength": b.get("strength", 30),
        })

    if sections:
        db.sections.insert_many([
            {
                "_id": s["id"], "year_id": s["year_id"], "name": s["name"], "strength": s.get("strength", 60),
                "subjects": section_subj_map.get(s["id"], []),
                "lab_batches": batch_map.get(s["id"], []),
            }
            for s in sections
        ])

    if time_slots:
        db.time_slots.insert_many([
            {"_id": t["id"], "day": t["day"], "period_index": t["period_index"],
             "start_time": t["start_time"], "end_time": t["end_time"]}
            for t in time_slots
        ])

    if constraint_profiles:
        db.constraint_profiles.insert_many([
            {"_id": c["id"], "name": c["name"],
             "soft_constraint_weights": json.loads(c["soft_constraint_weights"]) if c.get("soft_constraint_weights") else {}}
            for c in constraint_profiles
        ])

    entries_by_run = {}
    for e in generated_entries:
        entries_by_run.setdefault(e["timetable_run_id"], []).append({
            "day": e["day"], "period": e["period"], "section_id": e.get("section_id"),
            "batch_id": e.get("batch_id"), "subject_id": e["subject_id"],
            "teacher_id": e["teacher_id"], "room_id": e["room_id"],
        })

    if timetable_runs:
        max_run_id = 0
        db.timetable_runs.insert_many([
            {
                "_id": r["id"], "constraint_profile_id": r.get("constraint_profile_id"), "status": r["status"],
                "entries": entries_by_run.get(r["id"], []), "llm_explanation": r.get("llm_explanation"),
                "created_at": r["created_at"], "completed_at": r.get("completed_at"),
            }
            for r in timetable_runs
        ])
        max_run_id = max(r["id"] for r in timetable_runs)
        db.counters.update_one({"_id": "timetable_runs"}, {"$set": {"seq": max_run_id}}, upsert=True)

    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
