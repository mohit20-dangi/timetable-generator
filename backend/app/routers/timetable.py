from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db import get_db
from app.models import TimetableRun, GeneratedEntry, AcademicYear, Section, Subject, Teacher, Room, TeacherSubject, SectionSubject, LabBatch, Prerequisite, ConstraintProfile
from app.schemas import TimetableGenerateRequest, TimetableRunResponse, TimetableEntryResponse
from app.solver import solve_timetable
from app.llm.client import nvidia_client
import json
from datetime import datetime

router = APIRouter(prefix="/api/timetable", tags=["Timetable"])

def assemble_constraints(db: Session, profile_id: Optional[str] = None) -> dict:
    """Assemble all constraints from database into solver format."""
    years = db.query(AcademicYear).all()
    sections = db.query(Section).all()
    subjects = db.query(Subject).all()
    teachers = db.query(Teacher).all()
    rooms = db.query(Room).all()
    teacher_subjects = db.query(TeacherSubject).all()
    section_subjects = db.query(SectionSubject).all()
    lab_batches = db.query(LabBatch).all()
    prerequisites = db.query(Prerequisite).all()
    
    profile = None
    if profile_id:
        profile = db.query(ConstraintProfile).filter(ConstraintProfile.id == profile_id).first()
    
    # Build teacher subjects map
    teacher_subj_map = {}
    for ts in teacher_subjects:
        if ts.teacher_id not in teacher_subj_map:
            teacher_subj_map[ts.teacher_id] = []
        teacher_subj_map[ts.teacher_id].append(ts.subject_id)
    
    # Build section subjects map
    section_subj_map = {}
    for ss in section_subjects:
        if ss.section_id not in section_subj_map:
            section_subj_map[ss.section_id] = []
        section_subj_map[ss.section_id].append(ss.subject_id)
    
    return {
        "years": [
            {
                "id": y.id,
                "name": y.name,
                "sections": len([s for s in sections if s.year_id == y.id]),
                "lunch": {
                    "start": y.lunch_start.strftime("%H:%M") if y.lunch_start else None,
                    "end": y.lunch_end.strftime("%H:%M") if y.lunch_end else None
                }
            }
            for y in years
        ],
        "subjects": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.type,
                "weekly_hours": s.weekly_hours,
                "needs_continuous_block": s.needs_continuous_block,
                "block_size": s.block_size,
                "requires_room_type": s.requires_room_type,
                "requires_equipment": s.requires_equipment or []
            }
            for s in subjects
        ],
        "teachers": [
            {
                "id": t.id,
                "name": t.name,
                "subjects": teacher_subj_map.get(t.id, []),
                "max_continuous_classes": t.max_continuous_classes,
                "max_daily_classes": t.max_daily_classes,
                "availability": t.availability or [],
                "preferred_slots": t.preferred_slots or [],
                "is_guest_from_other_dept": t.is_guest_from_other_dept
            }
            for t in teachers
        ],
        "rooms": [
            {
                "id": r.id,
                "name": r.name,
                "type": r.type,
                "capacity": r.capacity,
                "equipment": r.equipment or [],
                "shared_with_departments": r.shared_with_departments or []
            }
            for r in rooms
        ],
        "section_subjects": section_subj_map,
        "lab_batches": [
            {
                "id": b.id,
                "section_id": b.section_id,
                "batch_name": b.batch_name,
                "strength": b.strength
            }
            for b in lab_batches
        ],
        "prerequisites": [
            {"subject_id": p.subject_id, "requires_subject_id": p.requires_subject_id}
            for p in prerequisites
        ],
        "soft_constraint_weights": profile.soft_constraint_weights if profile else {}
    }

@router.post("/generate", response_model=TimetableRunResponse)
def generate_timetable(
    request: TimetableGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Trigger timetable generation."""
    # Create run record
    run = TimetableRun(
        constraint_profile_id=request.constraint_profile_id,
        status="solving"
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    
    # Assemble constraints
    constraints = assemble_constraints(db, request.constraint_profile_id)
    
    # Run solver in background
    background_tasks.add_task(run_solver_task, run.id, constraints)
    
    return run

def run_solver_task(run_id: int, constraints: dict):
    """Background task to run the solver."""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
        if not run:
            return
        
        success, solution, status_msg = solve_timetable(constraints)
        
        if success:
            run.status = "completed"
            run.solver_output = solution
            run.completed_at = datetime.utcnow()
            
            # Save generated entries
            for entry in solution.get("entries", []):
                gen_entry = GeneratedEntry(
                    timetable_run_id=run.id,
                    day=entry["day"],
                    period=entry["period"],
                    section_id=entry.get("section_id"),
                    batch_id=entry.get("batch_id"),
                    subject_id=entry["subject_id"],
                    teacher_id=entry["teacher_id"],
                    room_id=entry["room_id"]
                )
                db.add(gen_entry)
        else:
            run.status = "failed"
            run.llm_explanation = nvidia_client.explain_infeasibility(
                constraints, "INFEASIBLE", status_msg
            )
            run.completed_at = datetime.utcnow()
        
        db.commit()
    except Exception as e:
        run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.llm_explanation = f"Solver error: {str(e)}"
            run.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()

@router.get("/runs", response_model=List[TimetableRunResponse])
def list_timetable_runs(db: Session = Depends(get_db)):
    return db.query(TimetableRun).order_by(TimetableRun.created_at.desc()).all()

@router.get("/runs/{run_id}", response_model=TimetableRunResponse)
def get_timetable_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")
    return run

@router.get("/runs/{run_id}/entries", response_model=List[TimetableEntryResponse])
def get_timetable_entries(run_id: int, db: Session = Depends(get_db)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")
    return db.query(GeneratedEntry).filter(GeneratedEntry.timetable_run_id == run_id).all()

@router.get("/runs/{run_id}/explain")
def explain_infeasibility(run_id: int, db: Session = Depends(get_db)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")
    
    if run.status != "failed":
        return {"explanation": "Timetable generation was successful. No explanation needed."}
    
    if run.llm_explanation:
        return {"explanation": run.llm_explanation}
    
    # Generate explanation if not already done
    constraints = assemble_constraints(db, run.constraint_profile_id)
    explanation = nvidia_client.explain_infeasibility(
        constraints, run.status, run.solver_output or "No solver output"
    )
    run.llm_explanation = explanation
    db.commit()
    
    return {"explanation": explanation}

@router.get("/runs/{run_id}/export")
def export_timetable(run_id: int, format: str = "xlsx", db: Session = Depends(get_db)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")
    
    entries = db.query(GeneratedEntry).filter(GeneratedEntry.timetable_run_id == run_id).all()
    
    if format == "xlsx":
        return export_to_excel(entries, db)
    elif format == "pdf":
        return export_to_pdf(entries, db)
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")

def export_to_excel(entries, db):
    import pandas as pd
    from fastapi.responses import StreamingResponse
    import io
    
    # Build data for export
    data = []
    for e in entries:
        section = db.query(Section).filter(Section.id == e.section_id).first() if e.section_id else None
        batch = db.query(LabBatch).filter(LabBatch.id == e.batch_id).first() if e.batch_id else None
        subject = db.query(Subject).filter(Subject.id == e.subject_id).first()
        teacher = db.query(Teacher).filter(Teacher.id == e.teacher_id).first()
        room = db.query(Room).filter(Room.id == e.room_id).first()
        
        data.append({
            "Day": e.day,
            "Period": e.period,
            "Section/Batch": section.name if section else (batch.batch_name if batch else ""),
            "Subject": subject.name if subject else "",
            "Subject Type": subject.type if subject else "",
            "Teacher": teacher.name if teacher else "",
            "Room": room.name if room else "",
            "Room Type": room.type if room else ""
        })
    
    df = pd.DataFrame(data)
    
    # Create multiple sheets
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name="Full Timetable", index=False)
        
        # Per-section sheets
        if "Section/Batch" in df.columns:
            for section_name in df["Section/Batch"].unique():
                if section_name:
                    section_df = df[df["Section/Batch"] == section_name]
                    section_df.to_excel(writer, sheet_name=section_name[:31], index=False)
        
        # Per-teacher sheets
        for teacher_name in df["Teacher"].unique():
            if teacher_name:
                teacher_df = df[df["Teacher"] == teacher_name]
                teacher_df.to_excel(writer, sheet_name=f"T_{teacher_name[:28]}", index=False)
        
        # Per-room sheets
        for room_name in df["Room"].unique():
            if room_name:
                room_df = df[df["Room"] == room_name]
                room_df.to_excel(writer, sheet_name=f"R_{room_name[:28]}", index=False)
    
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.read()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=timetable_run_{run_id}.xlsx"}
    )

def export_to_pdf(entries, db):
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from fastapi.responses import StreamingResponse
    import io
    
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    elements = []
    
    elements.append(Paragraph("Timetable Export", styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Build table data
    data = [["Day", "Period", "Section/Batch", "Subject", "Type", "Teacher", "Room"]]
    for e in entries:
        section = db.query(Section).filter(Section.id == e.section_id).first() if e.section_id else None
        batch = db.query(LabBatch).filter(LabBatch.id == e.batch_id).first() if e.batch_id else None
        subject = db.query(Subject).filter(Subject.id == e.subject_id).first()
        teacher = db.query(Teacher).filter(Teacher.id == e.teacher_id).first()
        room = db.query(Room).filter(Room.id == e.room_id).first()
        
        data.append([
            e.day, str(e.period),
            section.name if section else (batch.batch_name if batch else ""),
            subject.name if subject else "",
            subject.type if subject else "",
            teacher.name if teacher else "",
            room.name if room else ""
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