"""Remedial classes for low-attendance students: groups (what needs
remedial teaching), runs (a generated remedial timetable built around the
published main timetable) and their entries. See
app/solver/remedial_loader.py for how a run is built."""
import io
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import db as db_module
from app.auth.dependencies import get_current_user, require_timetable_manager
from app.auth.scope import department_of, get_scoped_or_404, scoped, target_department
from app.core.config import settings as app_settings
from app.db import get_db
from app.models import (
    GeneratedEntry, LabBatch, RemedialEntry, RemedialGroup, RemedialRun, Room, Section, Subject, Teacher,
    TimetableRun, User,
)
from app.schemas.remedial import (
    RemedialEntryResponse, RemedialGroupCreate, RemedialGroupResponse, RemedialRunCreate, RemedialRunResponse,
    RemedialSettings,
)
from app.services.department_calendar import department_time_slots
from app.solver import diagnostics as diag
from app.solver.calendar import occupied_indices
from app.solver.engine import solve_with_alternatives
from app.solver.remedial_loader import load_remedial_problem
from app.solver.remedial_model import extend_remedial_model
from app.solver.validator import validate_schedule

router = APIRouter(prefix="/api/remedial", tags=["Remedial"])


# ---------------------------------------------------------------- groups

def _department_or_400(admin: User, requested: Optional[str]) -> str:
    department_id = target_department(admin, requested)
    if not department_id:
        raise HTTPException(status_code=400, detail="Choose a department first")
    return department_id


def _validate_group(db: Session, payload: RemedialGroupCreate, department_id: str) -> None:
    if not db.get(Subject, payload.subject_id):
        raise HTTPException(status_code=400, detail="subject_id does not exist")
    for section_id in payload.section_ids:
        section = db.get(Section, section_id)
        if not section:
            raise HTTPException(status_code=400, detail=f"section {section_id} does not exist")
        if department_of(db, section) != department_id:
            raise HTTPException(status_code=400, detail=f"section {section_id} is not in this department")
    if payload.teacher_id and not db.get(Teacher, payload.teacher_id):
        raise HTTPException(status_code=400, detail="teacher_id does not exist")


@router.post("/groups", response_model=RemedialGroupResponse)
def create_group(
    payload: RemedialGroupCreate, db: Session = Depends(get_db), admin: User = Depends(require_timetable_manager),
):
    department_id = _department_or_400(admin, payload.department_id)
    if db.get(RemedialGroup, payload.id):
        raise HTTPException(status_code=409, detail="A remedial group with this id already exists")
    _validate_group(db, payload, department_id)
    group = RemedialGroup(**{**payload.model_dump(), "department_id": department_id})
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get("/groups", response_model=List[RemedialGroupResponse])
def list_groups(
    department_id: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return scoped(db.query(RemedialGroup), RemedialGroup, user, department_id).order_by(RemedialGroup.id).all()


@router.put("/groups/{group_id}", response_model=RemedialGroupResponse)
def update_group(
    group_id: str, payload: RemedialGroupCreate, db: Session = Depends(get_db),
    admin: User = Depends(require_timetable_manager),
):
    group = get_scoped_or_404(db, RemedialGroup, group_id, admin, "Remedial group")
    _validate_group(db, payload, group.department_id)
    for key, value in payload.model_dump(exclude={"id", "department_id"}).items():
        setattr(group, key, value)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/groups/{group_id}")
def delete_group(
    group_id: str, db: Session = Depends(get_db), admin: User = Depends(require_timetable_manager),
):
    group = get_scoped_or_404(db, RemedialGroup, group_id, admin, "Remedial group")
    db.delete(group)
    db.commit()
    return {"message": "Remedial group deleted"}


# ---------------------------------------------------------------- generation

def _failure_report(issues, solver_status: str, demands: int) -> dict:
    return {
        "solver_status": solver_status,
        "summary": {"demands": demands},
        "issues": [{"id": i.id, "severity": i.severity, "fact": i.fact, "suggestion": i.suggestion} for i in issues],
    }


def _run_remedial_generation(run_id: int) -> None:
    # Read SessionLocal as a live module attribute so tests can swap in an
    # isolated database (same reason as timetable._run_generation).
    db = db_module.SessionLocal()
    try:
        run = db.get(RemedialRun, run_id)
        if not run:
            return
        run.status = "solving"
        db.commit()
        settings = RemedialSettings(**(run.settings or {}))

        loaded = load_remedial_problem(db, run.department_id, settings)
        problem = loaded.problem
        blocking = [i for i in loaded.issues if i.severity == "blocking"]
        if not blocking:
            blocking = [i for i in diag.preflight_checks(problem) if i.severity == "blocking"]
        if blocking:
            report = _failure_report(blocking, "PREFLIGHT_BLOCKED", len(problem.demands))
            run.status = "failed"
            run.explanation = diag.format_diagnostics(report)
            run.solver_output = {"diagnostics": report, "warnings": loaded.warnings}
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        results = solve_with_alternatives(
            problem, max_seconds=settings.max_seconds, num_workers=app_settings.SOLVER_NUM_WORKERS,
            extend_model=lambda p, mv: extend_remedial_model(p, mv, loaded.context),
        )
        primary = results[0]
        if primary.status not in ("OPTIMAL", "FEASIBLE"):
            report = diag.explain_infeasibility(problem, primary.status, (primary.diagnostics or {}).get("error"))
            run.status = "failed"
            run.explanation = diag.format_diagnostics(report)
            run.solver_output = {"diagnostics": report, "warnings": loaded.warnings}
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        violations = validate_schedule(problem, primary.sessions)
        if violations:
            run.status = "failed"
            run.explanation = (
                "The remedial schedule failed independent validation and was blocked rather than shown. "
                "Details: " + "; ".join(f"{v.type}: {v.message}" for v in violations[:10])
            )
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        slots_by_index = {s.index: s for s in problem.slots}
        for session in primary.sessions:
            group_id = session.audience_id
            for slot_index in occupied_indices(session.start_slot_index, session.duration, slots_by_index):
                slot = slots_by_index[slot_index]
                db.add(RemedialEntry(
                    remedial_run_id=run.id, session_group=session.demand_id, day=slot.day, period=slot.period_index,
                    group_id=group_id, subject_id=session.subject_id, teacher_id=session.teacher_id,
                    room_id=session.room_id, in_remedial_slot=slot_index in loaded.context.remedial_slot_indices,
                ))
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        run.solver_output = {
            "objective_value": primary.objective_value, "warnings": loaded.warnings,
            "sessions_scheduled": len(primary.sessions),
        }
        db.commit()
    except Exception as exc:  # noqa: BLE001 - a run must never hang in "solving" forever
        db.rollback()
        run = db.get(RemedialRun, run_id)
        if run:
            run.status = "failed"
            run.explanation = f"Remedial generation failed with an internal error: {exc}"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@router.post("/runs", response_model=RemedialRunResponse)
def create_run(
    payload: RemedialRunCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
    admin: User = Depends(require_timetable_manager),
):
    department_id = _department_or_400(admin, payload.department_id)
    run = RemedialRun(
        department_id=department_id, status="pending", settings=payload.settings.model_dump(), created_by=admin.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    background_tasks.add_task(_run_remedial_generation, run.id)
    return run


@router.get("/runs", response_model=List[RemedialRunResponse])
def list_runs(
    department_id: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return scoped(db.query(RemedialRun), RemedialRun, user, department_id).order_by(RemedialRun.id.desc()).all()


@router.get("/runs/{run_id}", response_model=RemedialRunResponse)
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_scoped_or_404(db, RemedialRun, run_id, user, "Remedial run")


@router.get("/runs/{run_id}/entries", response_model=List[RemedialEntryResponse])
def get_run_entries(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_scoped_or_404(db, RemedialRun, run_id, user, "Remedial run")
    return (
        db.query(RemedialEntry).filter(RemedialEntry.remedial_run_id == run_id)
        .order_by(RemedialEntry.day, RemedialEntry.period).all()
    )


@router.post("/runs/{run_id}/publish", response_model=RemedialRunResponse)
def publish_run(run_id: int, db: Session = Depends(get_db), admin: User = Depends(require_timetable_manager)):
    run = get_scoped_or_404(db, RemedialRun, run_id, admin, "Remedial run")
    if run.status != "completed":
        raise HTTPException(status_code=400, detail="Only a completed remedial run can be published")
    # One published remedial timetable per department at a time.
    db.query(RemedialRun).filter(
        RemedialRun.department_id == run.department_id, RemedialRun.id != run.id,
    ).update({RemedialRun.is_published: False})
    run.is_published = True
    db.commit()
    db.refresh(run)
    return run


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db), admin: User = Depends(require_timetable_manager)):
    run = get_scoped_or_404(db, RemedialRun, run_id, admin, "Remedial run")
    if run.is_published:
        raise HTTPException(status_code=400, detail="Unpublish by publishing another run before deleting this one")
    db.delete(run)
    db.commit()
    return {"message": "Remedial run deleted"}


# ---------------------------------------------------------------- views

@router.get("/runs/{run_id}/section-view")
def section_view(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Per section the remedial run touches: its main (published) classes and
    its remedial classes, so the UI can show the remedial timetable as it
    sits around the main one."""
    run = get_scoped_or_404(db, RemedialRun, run_id, user, "Remedial run")
    entries = db.query(RemedialEntry).filter(RemedialEntry.remedial_run_id == run_id).all()
    groups = {g.id: g for g in db.query(RemedialGroup).filter(RemedialGroup.department_id == run.department_id).all()}
    section_ids = sorted({sid for g in groups.values() for sid in g.section_ids})
    sections = {s.id: s for s in db.query(Section).filter(Section.id.in_(section_ids)).all()}

    batch_parent = {b.id: b.section_id for b in db.query(LabBatch).all()}
    main_by_section = {sid: [] for sid in section_ids}
    published = (
        db.query(GeneratedEntry).join(TimetableRun, GeneratedEntry.timetable_run_id == TimetableRun.id)
        .filter(TimetableRun.is_published.is_(True), GeneratedEntry.alternative_rank == 1).all()
    )
    for e in published:
        owner = e.section_id or batch_parent.get(e.batch_id)
        if owner in main_by_section:
            main_by_section[owner].append({
                "day": e.day, "period": e.period, "subject_id": e.subject_id,
                "teacher_id": e.teacher_id, "room_id": e.room_id, "batch_id": e.batch_id,
            })

    def remedial_row(e):
        return {
            "day": e.day, "period": e.period, "group_id": e.group_id,
            "group_name": groups[e.group_id].name if e.group_id in groups else e.group_id,
            "subject_id": e.subject_id, "teacher_id": e.teacher_id, "room_id": e.room_id,
            "in_remedial_slot": e.in_remedial_slot,
        }

    result = []
    for sid in section_ids:
        result.append({
            "section_id": sid, "name": sections[sid].name if sid in sections else sid,
            "main": main_by_section[sid],
            "remedial": [remedial_row(e) for e in entries if e.group_id in groups and sid in groups[e.group_id].section_ids],
        })
    slots = department_time_slots(db, run.department_id, kind=None)
    return {
        "sections": result,
        "slots": [
            {"day": s.day, "period_index": s.period_index, "start_time": str(s.start_time)[:5],
             "end_time": str(s.end_time)[:5], "slot_kind": s.slot_kind or "regular"}
            for s in slots
        ],
    }


@router.get("/runs/{run_id}/export")
def export_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The remedial timetable as an Excel sheet, one row per class period."""
    from openpyxl import Workbook

    run = get_scoped_or_404(db, RemedialRun, run_id, user, "Remedial run")
    entries = db.query(RemedialEntry).filter(RemedialEntry.remedial_run_id == run_id).all()
    groups = {g.id: g for g in db.query(RemedialGroup).filter(RemedialGroup.department_id == run.department_id).all()}
    subjects = {s.id: s for s in db.query(Subject).all()}
    teachers = {t.id: t for t in db.query(Teacher).all()}
    rooms = {r.id: r for r in db.query(Room).all()}
    times = {(s.day, s.period_index): s for s in department_time_slots(db, run.department_id, kind=None)}
    day_rank = {d: i for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])}

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Remedial timetable"
    sheet.append(["Day", "Period", "Time", "Group", "Sections", "Subject", "Teacher", "Room", "Slot type"])
    for e in sorted(entries, key=lambda e: (day_rank.get(e.day, 99), e.period)):
        slot = times.get((e.day, e.period))
        group = groups.get(e.group_id)
        sheet.append([
            e.day, e.period, f"{str(slot.start_time)[:5]}-{str(slot.end_time)[:5]}" if slot else "",
            group.name if group else e.group_id, ", ".join(group.section_ids) if group else "",
            subjects[e.subject_id].name if e.subject_id in subjects else e.subject_id,
            teachers[e.teacher_id].name if e.teacher_id in teachers else e.teacher_id,
            rooms[e.room_id].name if e.room_id in rooms else e.room_id,
            "Remedial slot" if e.in_remedial_slot else "Free period in main timetable",
        ])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="remedial-timetable-{run_id}.xlsx"'},
    )
