from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pymongo.database import Database
from typing import List, Optional
from datetime import datetime, timezone
from app.db import get_database
from app.repositories import Repository, next_sequence
from app.models import TimetableGenerateRequest, TimetableRunResponse
from app.solver import solve_timetable
from app.llm.client import nvidia_client
from app.auth.dependencies import get_current_admin

router = APIRouter(prefix="/api/timetable", tags=["Timetable"])


def assemble_constraints(db: Database, profile_id: Optional[str] = None) -> dict:
    """Assemble all constraints from the database into the solver's input format."""
    years = list(db.academic_years.find({}))
    sections = list(db.sections.find({}))
    subjects = list(db.subjects.find({}))
    teachers = list(db.teachers.find({}))
    rooms = list(db.rooms.find({}))
    time_slots = list(db.time_slots.find({}))

    profile = db.constraint_profiles.find_one({"_id": profile_id}) if profile_id else None

    year_lunch = {y["_id"]: {"start": y.get("lunch_start"), "end": y.get("lunch_end")} for y in years}

    section_subj_map = {
        s["_id"]: [link["subject_id"] for link in s.get("subjects", [])]
        for s in sections
    }

    lab_batches = [
        {"id": b["id"], "section_id": s["_id"], "batch_name": b["batch_name"], "strength": b["strength"]}
        for s in sections
        for b in s.get("lab_batches", [])
    ]

    prerequisites = [
        {"subject_id": s["_id"], "requires_subject_id": req}
        for s in subjects
        for req in s.get("prerequisite_ids", [])
    ]

    return {
        "sections": [
            {
                "id": s["_id"],
                "year_id": s["year_id"],
                "name": s["name"],
                "strength": s.get("strength", 60),
                "lunch_start": year_lunch.get(s["year_id"], {}).get("start"),
                "lunch_end": year_lunch.get(s["year_id"], {}).get("end"),
            }
            for s in sections
        ],
        "subjects": [
            {
                "id": s["_id"],
                "name": s["name"],
                "type": s["type"],
                "weekly_hours": s.get("weekly_hours", 0),
                "needs_continuous_block": s.get("needs_continuous_block", False),
                "block_size": s.get("block_size", 1),
                "requires_room_type": s.get("requires_room_type"),
                "requires_equipment": s.get("requires_equipment", []),
            }
            for s in subjects
        ],
        "teachers": [
            {
                "id": t["_id"],
                "name": t["name"],
                "subjects": t.get("subject_ids", []),
                "max_continuous_classes": t.get("max_continuous_classes", 3),
                "max_daily_classes": t.get("max_daily_classes", 5),
                "availability": t.get("availability", []),
                "preferred_slots": t.get("preferred_slots", []),
                "is_guest_from_other_dept": t.get("is_guest_from_other_dept", False),
            }
            for t in teachers
        ],
        "rooms": [
            {
                "id": r["_id"],
                "name": r["name"],
                "type": r["type"],
                "capacity": r.get("capacity", 60),
                "equipment": r.get("equipment", []),
                "shared_with_departments": r.get("shared_with_departments", []),
            }
            for r in rooms
        ],
        "time_slots": [
            {
                "id": ts["_id"],
                "day": ts["day"],
                "period_index": ts["period_index"],
                "start_time": ts["start_time"],
                "end_time": ts["end_time"],
            }
            for ts in time_slots
        ],
        "section_subjects": section_subj_map,
        "lab_batches": lab_batches,
        "prerequisites": prerequisites,
        "soft_constraint_weights": profile.get("soft_constraint_weights", {}) if profile else {},
    }


@router.post("/generate", response_model=TimetableRunResponse)
def generate_timetable(
    request: TimetableGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    """Trigger timetable generation."""
    run = {
        "_id": next_sequence(db, "timetable_runs"),
        "constraint_profile_id": request.constraint_profile_id,
        "status": "solving",
        "entries": [],
        "llm_explanation": None,
        "created_at": datetime.now(timezone.utc),
        "completed_at": None,
    }
    db.timetable_runs.insert_one(run)

    constraints = assemble_constraints(db, request.constraint_profile_id)
    background_tasks.add_task(run_solver_task, run["_id"], constraints)

    return {**run, "id": run["_id"]}


def run_solver_task(run_id: int, constraints: dict):
    """Background task to run the solver."""
    from app.db import get_database
    db = get_database()
    try:
        success, solution, status_msg = solve_timetable(constraints)

        if success:
            db.timetable_runs.update_one(
                {"_id": run_id},
                {"$set": {
                    "status": "completed",
                    "entries": solution.get("entries", []),
                    "completed_at": datetime.now(timezone.utc),
                }},
            )
        else:
            explanation = nvidia_client.explain_infeasibility(constraints, "INFEASIBLE", status_msg)
            db.timetable_runs.update_one(
                {"_id": run_id},
                {"$set": {
                    "status": "failed",
                    "llm_explanation": explanation,
                    "completed_at": datetime.now(timezone.utc),
                }},
            )
    except Exception as e:
        db.timetable_runs.update_one(
            {"_id": run_id},
            {"$set": {
                "status": "failed",
                "llm_explanation": f"Solver error: {str(e)}",
                "completed_at": datetime.now(timezone.utc),
            }},
        )


def _run_response(run: dict) -> dict:
    return {**run, "id": run["_id"]}


@router.get("/runs", response_model=List[TimetableRunResponse])
def list_timetable_runs(
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    runs = db.timetable_runs.find({}).sort("created_at", -1)
    return [_run_response(r) for r in runs]


@router.get("/runs/{run_id}", response_model=TimetableRunResponse)
def get_timetable_run(
    run_id: int,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    run = db.timetable_runs.find_one({"_id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")
    return _run_response(run)


@router.get("/runs/{run_id}/entries")
def get_timetable_entries(
    run_id: int,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    run = db.timetable_runs.find_one({"_id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")
    return run.get("entries", [])


@router.get("/runs/{run_id}/explain")
def explain_infeasibility(
    run_id: int,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    run = db.timetable_runs.find_one({"_id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")

    if run["status"] != "failed":
        return {"explanation": "Timetable generation was successful. No explanation needed."}

    if run.get("llm_explanation"):
        return {"explanation": run["llm_explanation"]}

    constraints = assemble_constraints(db, run.get("constraint_profile_id"))
    explanation = nvidia_client.explain_infeasibility(constraints, run["status"], "No solver output")
    db.timetable_runs.update_one({"_id": run_id}, {"$set": {"llm_explanation": explanation}})

    return {"explanation": explanation}


@router.get("/runs/{run_id}/export")
def export_timetable(
    run_id: int,
    format: str = "xlsx",
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    run = db.timetable_runs.find_one({"_id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")

    entries = run.get("entries", [])
    sections = {s["_id"]: s for s in db.sections.find({})}
    batches = {b["id"]: b for s in sections.values() for b in s.get("lab_batches", [])}
    subjects = {s["_id"]: s for s in db.subjects.find({})}
    teachers = {t["_id"]: t for t in db.teachers.find({})}
    rooms = {r["_id"]: r for r in db.rooms.find({})}

    if format == "xlsx":
        return export_to_excel(run_id, entries, sections, batches, subjects, teachers, rooms)
    elif format == "pdf":
        return export_to_pdf(run_id, entries, sections, batches, subjects, teachers, rooms)
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")


def _rows_for_export(entries, sections, batches, subjects, teachers, rooms):
    """Batch-fetch reference data once (dicts above) instead of a query per
    entry, and dedupe truncated Excel/PDF sheet names so two entities that
    truncate to the same 31-char prefix don't collide."""
    rows = []
    for e in entries:
        section = sections.get(e.get("section_id"))
        batch = batches.get(e.get("batch_id"))
        subject = subjects.get(e["subject_id"])
        teacher = teachers.get(e["teacher_id"])
        room = rooms.get(e["room_id"])

        rows.append({
            "Day": e["day"],
            "Period": e["period"],
            "Section/Batch": section["name"] if section else (batch["batch_name"] if batch else ""),
            "Subject": subject["name"] if subject else "",
            "Subject Type": subject["type"] if subject else "",
            "Teacher": teacher["name"] if teacher else "",
            "Room": room["name"] if room else "",
            "Room Type": room["type"] if room else "",
        })
    return rows


def _unique_sheet_name(base: str, used: set) -> str:
    name = base[:31] or "Sheet"
    candidate = name
    suffix = 1
    while candidate in used:
        suffix_str = f"_{suffix}"
        candidate = f"{name[:31 - len(suffix_str)]}{suffix_str}"
        suffix += 1
    used.add(candidate)
    return candidate


def export_to_excel(run_id, entries, sections, batches, subjects, teachers, rooms):
    import pandas as pd
    from fastapi.responses import StreamingResponse
    import io

    data = _rows_for_export(entries, sections, batches, subjects, teachers, rooms)
    df = pd.DataFrame(data)

    output = io.BytesIO()
    used_sheet_names = {"Full Timetable"}
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name="Full Timetable", index=False)

        if "Section/Batch" in df.columns:
            for section_name in df["Section/Batch"].unique():
                if section_name:
                    section_df = df[df["Section/Batch"] == section_name]
                    sheet_name = _unique_sheet_name(section_name, used_sheet_names)
                    section_df.to_excel(writer, sheet_name=sheet_name, index=False)

        for teacher_name in df["Teacher"].unique():
            if teacher_name:
                teacher_df = df[df["Teacher"] == teacher_name]
                sheet_name = _unique_sheet_name(f"T_{teacher_name}", used_sheet_names)
                teacher_df.to_excel(writer, sheet_name=sheet_name, index=False)

        for room_name in df["Room"].unique():
            if room_name:
                room_df = df[df["Room"] == room_name]
                sheet_name = _unique_sheet_name(f"R_{room_name}", used_sheet_names)
                room_df.to_excel(writer, sheet_name=sheet_name, index=False)

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.read()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=timetable_run_{run_id}.xlsx"}
    )


def export_to_pdf(run_id, entries, sections, batches, subjects, teachers, rooms):
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from fastapi.responses import StreamingResponse
    import io

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    elements = [Paragraph("Timetable Export", styles['Title']), Spacer(1, 12)]

    rows = _rows_for_export(entries, sections, batches, subjects, teachers, rooms)
    data = [["Day", "Period", "Section/Batch", "Subject", "Type", "Teacher", "Room"]]
    for row in rows:
        data.append([
            row["Day"], str(row["Period"]), row["Section/Batch"],
            row["Subject"], row["Subject Type"], row["Teacher"], row["Room"],
        ])

    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))

    elements.append(table)
    doc.build(elements)

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.read()),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=timetable_run_{run_id}.pdf"}
    )
