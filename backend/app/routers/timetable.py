import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import db as db_module
from app.db import get_db
from app.core.config import settings
from app.models import (
    TimetableRun, GeneratedEntry, ConstraintProfile, Department, LabBatch,
    Section, User,
)
from app.schemas import (
    TimetableGenerateRequest, TimetableRunResponse, TimetableEntryResponse,
    EditEntryRequest, EditEntryResponse, ConflictDetail, SuggestedSlot,
    ValidationResponse, ValidationIssue, AlternativesResponse, AlternativeSummary,
    AlternativeDetailResponse,
)
from app.auth.dependencies import get_current_user, require_admin
from app.solver.data_loader import load_department_problem
from app.solver.engine import solve_with_alternatives
from app.solver.calendar import build_slot_calendar
from app.solver import diagnostics as diag
from app.solver.weights import resolve_weights
from app.services.schedule_validator import validate_persisted_run
from app.services import exporters
from app.llm.client import claude_client

router = APIRouter(prefix="/api/timetable", tags=["Timetable"])


def _expand_sessions_to_entries(sessions, slots_by_index) -> List[dict]:
    """One SessionDemand of duration D becomes D GeneratedEntry rows (one
    per occupied period), all sharing session_group so an edit or export
    can treat them as a single block."""
    rows = []
    for session in sessions:
        idx = session.start_slot_index
        current = slots_by_index[idx]
        occupied = [idx]
        while len(occupied) < session.duration:
            nxt = slots_by_index.get(idx + 1)
            if nxt is None or nxt.day != current.day or nxt.start_minutes != current.end_minutes:
                break
            idx += 1
            occupied.append(idx)
            current = nxt
        for slot_index in occupied:
            slot = slots_by_index[slot_index]
            rows.append({
                "session_group": session.demand_id,
                "day": slot.day,
                "period": slot.period_index,
                "section_id": session.parent_section_id if session.audience_type == "section" else None,
                "batch_id": session.audience_id if session.audience_type == "batch" else None,
                "subject_id": session.subject_id,
                "teacher_id": session.teacher_id,
                "room_id": session.room_id,
            })
    return rows


def _run_generation(run_id: int):
    # Read app.db.SessionLocal as a live module attribute (not a name bound
    # at import time) so tests can monkeypatch it to an isolated database
    # and have this background task actually use it.
    db = db_module.SessionLocal()
    try:
        run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
        if not run:
            return
        run.status = "solving"
        db.commit()

        soft_weights = {}
        if run.constraint_profile_id:
            profile = db.query(ConstraintProfile).filter(ConstraintProfile.id == run.constraint_profile_id).first()
            if profile and profile.soft_constraint_weights:
                soft_weights = resolve_weights(profile.soft_constraint_weights)

        problem, warnings = load_department_problem(
            db, run.department_id, run.year_ids, run.section_ids, run.scope_mode, soft_weights,
        )

        if not problem.demands:
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.solver_output = {"objective_value": 0, "alternatives": [], "warnings": warnings, "sessions_scheduled": 0}
            db.commit()
            return

        issues = diag.preflight_checks(problem)
        blocking = [i for i in issues if i.severity == "blocking"]
        if blocking:
            run.status = "failed"
            run.completed_at = datetime.utcnow()
            report = {
                "solver_status": "PREFLIGHT_BLOCKED",
                "summary": {"demands": len(problem.demands)},
                "issues": [{"id": i.id, "severity": i.severity, "fact": i.fact, "suggestion": i.suggestion} for i in blocking],
            }
            deterministic_text = diag.format_diagnostics(report)
            run.llm_explanation = _maybe_enhance_explanation(deterministic_text)
            run.solver_output = {"diagnostics": report, "warnings": warnings}
            db.commit()
            return

        results = solve_with_alternatives(
            problem, max_seconds=settings.SOLVER_MAX_SECONDS,
            num_workers=settings.SOLVER_NUM_WORKERS, num_alternatives=run.num_alternatives,
        )
        primary = results[0]

        if primary.status not in ("OPTIMAL", "FEASIBLE"):
            run.status = "failed"
            run.completed_at = datetime.utcnow()
            report = diag.explain_infeasibility(problem, primary.status)
            deterministic_text = diag.format_diagnostics(report)
            run.llm_explanation = _maybe_enhance_explanation(deterministic_text)
            run.solver_output = {"diagnostics": report, "warnings": warnings}
            db.commit()
            return

        slots_by_index = {s.index: s for s in problem.slots}
        for rank, result in enumerate(results, start=1):
            rows = _expand_sessions_to_entries(result.sessions, slots_by_index)
            for row in rows:
                db.add(GeneratedEntry(timetable_run_id=run.id, alternative_rank=rank, **row))
        db.commit()

        # Defense in depth: independently re-validate what was just
        # persisted before ever reporting "completed" to the admin.
        violations = validate_persisted_run(db, run.id, alternative_rank=1)
        if violations:
            run.status = "failed"
            run.llm_explanation = (
                "Generation produced a schedule that failed independent validation - this should "
                "not happen and has been blocked rather than shown. Please report this. Details: "
                + "; ".join(f"{v.type}: {v.message}" for v in violations[:10])
            )
            run.completed_at = datetime.utcnow()
            db.commit()
            return

        run.status = "completed"
        run.completed_at = datetime.utcnow()
        run.solver_output = {
            "objective_value": primary.objective_value,
            "alternatives": [{"rank": i + 1, "objective_value": r.objective_value} for i, r in enumerate(results)],
            "warnings": warnings,
            "sessions_scheduled": len(primary.sessions),
        }
        db.commit()
    except Exception as exc:  # noqa: BLE001 - a run must never hang in "solving" forever
        run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.llm_explanation = f"Generation failed with an internal error: {exc}"
            run.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _maybe_enhance_explanation(deterministic_text: str) -> str:
    if not settings.ANTHROPIC_API_KEY:
        return deterministic_text
    try:
        return claude_client.explain_infeasibility(deterministic_text)
    except Exception:
        return deterministic_text


@router.post("/generate", response_model=TimetableRunResponse)
def generate_timetable(
    request: TimetableGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if not db.query(Department).filter(Department.id == request.department_id).first():
        raise HTTPException(status_code=400, detail="department_id does not exist")
    if request.constraint_profile_id and not db.query(ConstraintProfile).filter(
        ConstraintProfile.id == request.constraint_profile_id
    ).first():
        raise HTTPException(status_code=400, detail="constraint_profile_id does not exist")

    run = TimetableRun(
        department_id=request.department_id,
        constraint_profile_id=request.constraint_profile_id,
        status="pending",
        scope_mode=request.scope_mode,
        year_ids=request.year_ids,
        section_ids=request.section_ids,
        num_alternatives=request.num_alternatives,
        created_by=admin.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(_run_generation, run.id)
    return run


@router.get("/runs", response_model=List[TimetableRunResponse])
def list_runs(
    department_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = db.query(TimetableRun).order_by(TimetableRun.created_at.desc())
    if department_id:
        query = query.filter(TimetableRun.department_id == department_id)
    return query.all()


@router.get("/runs/{run_id}", response_model=TimetableRunResponse)
def get_run(run_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/entries", response_model=List[TimetableEntryResponse])
def get_entries(run_id: int, rank: int = 1, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return (
        db.query(GeneratedEntry)
        .filter(GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == rank)
        .all()
    )


@router.get("/runs/{run_id}/validate", response_model=ValidationResponse)
def validate_run(run_id: int, rank: int = 1, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    violations = validate_persisted_run(db, run_id, alternative_rank=rank)
    return ValidationResponse(
        valid=len(violations) == 0,
        issues=[ValidationIssue(type=v.type, message=v.message) for v in violations],
    )


@router.get("/runs/{run_id}/alternatives", response_model=AlternativesResponse)
def get_alternatives(run_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    alt_meta = (run.solver_output or {}).get("alternatives", [])
    summaries = []
    prev_map = None
    for item in alt_meta:
        rank = item["rank"]
        entries = (
            db.query(GeneratedEntry)
            .filter(GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == rank)
            .all()
        )
        current_map = {e.session_group: (e.day, e.period) for e in entries}
        diversity = 0
        if prev_map is not None:
            for key, value in current_map.items():
                if prev_map.get(key) != value:
                    diversity += 1
        summaries.append(AlternativeSummary(
            rank=rank, objective_value=item.get("objective_value") or 0, diversity_from_previous=diversity,
        ))
        prev_map = current_map
    return AlternativesResponse(alternatives=summaries)


@router.get("/runs/{run_id}/alternatives/{rank}", response_model=AlternativeDetailResponse)
def get_alternative_detail(run_id: int, rank: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    alt_meta = {item["rank"]: item for item in (run.solver_output or {}).get("alternatives", [])}
    if rank not in alt_meta:
        raise HTTPException(status_code=404, detail="Alternative not found")
    entries = (
        db.query(GeneratedEntry)
        .filter(GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == rank)
        .all()
    )
    return AlternativeDetailResponse(rank=rank, objective_value=alt_meta[rank].get("objective_value") or 0, entries=entries)


@router.post("/runs/{run_id}/alternatives/{rank}/use", response_model=TimetableRunResponse)
def use_alternative(run_id: int, rank: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    parent = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Run not found")
    entries = (
        db.query(GeneratedEntry)
        .filter(GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == rank)
        .all()
    )
    if not entries:
        raise HTTPException(status_code=404, detail="Alternative not found")

    new_run = TimetableRun(
        department_id=parent.department_id, constraint_profile_id=parent.constraint_profile_id,
        status="completed", scope_mode=parent.scope_mode, year_ids=parent.year_ids,
        section_ids=parent.section_ids, num_alternatives=1, parent_run_id=parent.id,
        change_summary=f"Promoted alternative #{rank} from run #{run_id}",
        completed_at=datetime.utcnow(), created_by=admin.id,
        solver_output={"objective_value": (parent.solver_output or {}).get("alternatives", [{}])[rank - 1].get("objective_value")
                       if (parent.solver_output or {}).get("alternatives") else None},
    )
    db.add(new_run)
    db.flush()
    for e in entries:
        db.add(GeneratedEntry(
            timetable_run_id=new_run.id, alternative_rank=1, session_group=e.session_group,
            day=e.day, period=e.period, section_id=e.section_id, batch_id=e.batch_id,
            subject_id=e.subject_id, teacher_id=e.teacher_id, room_id=e.room_id,
        ))
    db.commit()
    db.refresh(new_run)
    return new_run


@router.get("/runs/{run_id}/explain")
def explain_run(run_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"explanation": run.llm_explanation or "No explanation is available for this run."}


@router.post("/runs/{run_id}/publish", response_model=TimetableRunResponse)
def publish_run(run_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "completed":
        raise HTTPException(status_code=400, detail="Only a completed run can be published")

    entries = db.query(GeneratedEntry).filter(
        GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == 1,
    ).all()
    section_ids = {e.section_id for e in entries if e.section_id}
    batch_section_map = {
        b.id: b.section_id for b in db.query(LabBatch).filter(
            LabBatch.id.in_([e.batch_id for e in entries if e.batch_id])
        ).all()
    }
    for e in entries:
        if e.batch_id and e.batch_id in batch_section_map:
            section_ids.add(batch_section_map[e.batch_id])

    if section_ids:
        other_published = (
            db.query(TimetableRun)
            .filter(TimetableRun.is_published.is_(True), TimetableRun.id != run_id)
            .all()
        )
        for other in other_published:
            other_entries = db.query(GeneratedEntry).filter(
                GeneratedEntry.timetable_run_id == other.id, GeneratedEntry.alternative_rank == 1,
            ).all()
            other_sections = {e.section_id for e in other_entries if e.section_id}
            if other_sections & section_ids:
                other.is_published = False

    run.is_published = True
    run.published_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run


@router.get("/runs/{run_id}/versions", response_model=List[TimetableRunResponse])
def get_versions(run_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    all_runs = {r.id: r for r in db.query(TimetableRun).all()}
    root_id = run.id
    seen_up = set()
    current = run
    while current.parent_run_id and current.parent_run_id not in seen_up:
        seen_up.add(current.parent_run_id)
        current = all_runs.get(current.parent_run_id)
        if not current:
            break
        root_id = current.id

    lineage = {root_id}
    changed = True
    while changed:
        changed = False
        for r in all_runs.values():
            if r.parent_run_id in lineage and r.id not in lineage:
                lineage.add(r.id)
                changed = True

    return sorted([all_runs[i] for i in lineage], key=lambda r: r.created_at)


@router.get("/runs/{from_run_id}/compare/{to_run_id}")
def compare_runs(from_run_id: int, to_run_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    from_entries = db.query(GeneratedEntry).filter(
        GeneratedEntry.timetable_run_id == from_run_id, GeneratedEntry.alternative_rank == 1,
    ).all()
    to_entries = db.query(GeneratedEntry).filter(
        GeneratedEntry.timetable_run_id == to_run_id, GeneratedEntry.alternative_rank == 1,
    ).all()
    from_map = {e.session_group: e for e in from_entries}
    to_map = {e.session_group: e for e in to_entries}

    changes = []
    for key in set(from_map) | set(to_map):
        a, b = from_map.get(key), to_map.get(key)
        if a and not b:
            changes.append({"type": "removed", "session_group": key, "description": f"{a.subject_id} removed"})
        elif b and not a:
            changes.append({"type": "added", "session_group": key, "description": f"{b.subject_id} added"})
        elif (a.day, a.period, a.room_id, a.teacher_id) != (b.day, b.period, b.room_id, b.teacher_id):
            changes.append({
                "type": "changed", "session_group": key,
                "description": f"{a.subject_id}: {a.day} P{a.period} -> {b.day} P{b.period}",
            })
    return {"changes": changes}


@router.get("/me")
def my_timetable(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    published_runs = db.query(TimetableRun).filter(TimetableRun.is_published.is_(True)).all()
    entries: List[GeneratedEntry] = []
    for run in published_runs:
        run_entries = db.query(GeneratedEntry).filter(
            GeneratedEntry.timetable_run_id == run.id, GeneratedEntry.alternative_rank == 1,
        ).all()
        if user.role == "FACULTY" and user.teacher_id:
            entries.extend([e for e in run_entries if e.teacher_id == user.teacher_id])
        elif user.role == "STUDENT" and user.section_id:
            batch_ids = {b.id for b in db.query(LabBatch).filter(LabBatch.section_id == user.section_id).all()}
            entries.extend([e for e in run_entries if e.section_id == user.section_id or e.batch_id in batch_ids])
    return [TimetableEntryResponse.model_validate(e) for e in entries]


@router.post("/runs/{run_id}/edit", response_model=EditEntryResponse)
def edit_entry(run_id: int, request: EditEntryRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    all_entries = db.query(GeneratedEntry).filter(
        GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == 1,
    ).all()
    target = next((
        e for e in all_entries
        if e.day == request.target.day and e.period == request.target.period
        and e.subject_id == request.target.subject_id
        and (e.section_id == request.target.section_id or e.batch_id == request.target.batch_id)
    ), None)
    if not target:
        raise HTTPException(status_code=404, detail="Target entry not found")

    block = [e for e in all_entries if e.session_group == target.session_group]
    block_len = len(block)
    new_room_id = request.new_room_id or target.room_id
    new_teacher_id = request.new_teacher_id or target.teacher_id

    from app.models import TimeSlot
    slots = build_slot_calendar([
        {"day": t.day, "period_index": t.period_index, "start_time": t.start_time, "end_time": t.end_time}
        for t in db.query(TimeSlot).all()
    ])
    slot_by_day_period = {(s.day, s.period_index): s for s in slots}
    slots_by_index = {s.index: s for s in slots}
    anchor = slot_by_day_period.get((request.new_day, request.new_period))
    if not anchor:
        raise HTTPException(status_code=400, detail="new_day/new_period is not a configured time slot")

    new_slot_indices = [anchor.index]
    current = anchor
    while len(new_slot_indices) < block_len:
        nxt = slots_by_index.get(current.index + 1)
        if not nxt or nxt.day != current.day or nxt.start_minutes != current.end_minutes:
            break
        new_slot_indices.append(nxt.index)
        current = nxt
    if len(new_slot_indices) < block_len:
        return EditEntryResponse(status="conflict", conflicts=[
            ConflictDetail(type="LUNCH_BREAK", message="The new time doesn't have enough contiguous periods for this block.")
        ])

    new_positions = [(slots_by_index[i].day, slots_by_index[i].period_index) for i in new_slot_indices]
    other_entries = [e for e in all_entries if e.session_group != target.session_group]

    conflicts: List[ConflictDetail] = []
    for day, period in new_positions:
        for e in other_entries:
            if e.day != day or e.period != period:
                continue
            if e.room_id == new_room_id:
                conflicts.append(ConflictDetail(type="ROOM_CLASH", message=f"Room {new_room_id} is busy on {day} period {period}."))
            if e.teacher_id == new_teacher_id:
                conflicts.append(ConflictDetail(type="TEACHER_CLASH", message=f"Teacher {new_teacher_id} is busy on {day} period {period}."))
            if target.section_id and e.section_id == target.section_id:
                conflicts.append(ConflictDetail(type="SECTION_CLASH", message=f"Section {target.section_id} is busy on {day} period {period}."))
            if target.batch_id and e.batch_id == target.batch_id:
                conflicts.append(ConflictDetail(type="BATCH_CLASH", message=f"Batch {target.batch_id} is busy on {day} period {period}."))

    if conflicts and not request.auto_resolve:
        suggestions = []
        for candidate_start in sorted(slots_by_index.keys()):
            candidate_indices = list(range(candidate_start, candidate_start + block_len))
            if any(i not in slots_by_index for i in candidate_indices):
                continue
            candidate_positions = [(slots_by_index[i].day, slots_by_index[i].period_index) for i in candidate_indices]
            has_conflict = any(
                e.room_id == new_room_id and (e.day, e.period) in candidate_positions
                or e.teacher_id == new_teacher_id and (e.day, e.period) in candidate_positions
                for e in other_entries
            )
            if not has_conflict:
                suggestions.append(SuggestedSlot(day=candidate_positions[0][0], period=candidate_positions[0][1]))
            if len(suggestions) >= 3:
                break
        return EditEntryResponse(status="conflict", conflicts=conflicts, suggested_slots=suggestions)

    for e, (day, period) in zip(block, new_positions):
        e.day = day
        e.period = period
        e.room_id = new_room_id
        e.teacher_id = new_teacher_id
    db.commit()

    updated_run = TimetableRunResponse.model_validate(run)
    return EditEntryResponse(status="applied", new_run=updated_run)


@router.get("/runs/{run_id}/export")
def export_run(
    run_id: int,
    format: str = "xlsx",
    rank: int = 1,
    view: str = "section",
    entity_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if view not in ("section", "teacher", "room"):
        raise HTTPException(status_code=400, detail="view must be section, teacher, or room")
    if not entity_id:
        first_entry = db.query(GeneratedEntry).filter(
            GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == rank,
        ).first()
        if not first_entry:
            raise HTTPException(status_code=404, detail="No entries to export for this run")
        entity_id = {"section": first_entry.section_id, "teacher": first_entry.teacher_id, "room": first_entry.room_id}[view]

    title = f"Weekly Timetable | Run #{run_id}"
    if format == "xlsx":
        content = exporters.export_xlsx(db, run_id, rank, view, entity_id, title)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"timetable_run_{run_id}.xlsx"
    elif format == "pdf":
        content = exporters.export_pdf(db, run_id, rank, view, entity_id, title)
        media_type = "application/pdf"
        filename = f"timetable_run_{run_id}.pdf"
    elif format == "ics":
        content = exporters.export_ics(db, run_id, rank, view, entity_id)
        media_type = "text/calendar"
        filename = f"timetable_run_{run_id}.ics"
    else:
        raise HTTPException(status_code=400, detail="format must be xlsx, pdf, or ics")

    return StreamingResponse(
        io.BytesIO(content), media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
