import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.dependencies import DEPT_ADMIN, HOD, SUPERADMIN, get_current_user
from app.auth.scope import is_superadmin, scoped
from app.services.department_calendar import department_time_slots
from app.db import get_db
from app.llm.client import claude_client
from app.models import Room, SavedFilter, Section, Subject, Teacher, TimeSlot, TimetableRun, User
from app.routers.timetable import _get_run_scoped
from app.schemas.custom_filter import (
    CustomFilterEvaluateRequest, CustomFilterEvaluateResponse, CustomFilterParseRequest,
    CustomFilterParseResponse, FilterCell, FilterSpec, FreeRoom, SavedFilterCreate, SavedFilterResponse,
)
from app.schemas.timetable import TimetableEntryResponse
from app.services.custom_filter import ME, evaluate_for_user

router = APIRouter(prefix="/api/custom-filters", tags=["Custom Filters"])


def _resolve_run(db: Session, user: User, run_id: Optional[int]) -> Optional[TimetableRun]:
    """Teachers only ever see published timetables, so they can't point a
    filter at one specific (possibly unpublished) run - that view is for
    admins/HODs, department-scoped exactly like every other run endpoint."""
    if run_id is None:
        return None
    if user.role not in (SUPERADMIN, DEPT_ADMIN, HOD):
        raise HTTPException(status_code=403, detail="Only admins and HODs can filter a specific run.")
    return _get_run_scoped(db, run_id, user)


def _user_department(db: Session, user: User) -> Optional[str]:
    """Accounts carry a department_id; a teacher login created before that
    may only have it through its linked Teacher row."""
    if user.department_id:
        return user.department_id
    if user.teacher_id:
        teacher = db.query(Teacher).filter(Teacher.id == user.teacher_id).first()
        return teacher.department_id if teacher else None
    return None


def _build_catalog(db: Session, user: User) -> dict:
    """What the AI may refer to: only the user's own department's data."""
    slots = department_time_slots(db, _user_department(db, user))
    rooms = scoped(db.query(Room), Room, user).all()
    subjects = scoped(db.query(Subject), Subject, user).all()
    teachers = scoped(db.query(Teacher), Teacher, user).all()
    sections = scoped(db.query(Section), Section, user).all()
    return {
        "teachers": [{"id": t.id, "name": t.name, "initials": t.initials} for t in teachers],
        "sections": [{"id": s.id, "name": s.name, "year_id": s.year_id} for s in sections],
        "subjects": [{"id": s.id, "name": s.name, "type": s.type} for s in subjects],
        "rooms": [{"id": r.id, "name": r.name, "type": r.type, "capacity": r.capacity} for r in rooms],
        "room_types": sorted({r.type for r in rooms if r.type}),
        "subject_types": sorted({s.type for s in subjects if s.type}),
        "days": sorted({s.day for s in slots}),
        "time_range": (
            [min(s.start_time for s in slots).strftime("%H:%M"), max(s.end_time for s in slots).strftime("%H:%M")]
            if slots else None
        ),
    }


def _ground_spec(raw: dict, catalog: dict):
    """Keeps only ids/types that really exist; everything else is reported,
    never silently kept - a hallucinated id would otherwise quietly turn a
    narrow filter into an empty (or, worse, unfiltered) one."""
    known = {
        "teacher_ids": {t["id"] for t in catalog["teachers"]} | {ME},
        "section_ids": {s["id"] for s in catalog["sections"]},
        "subject_ids": {s["id"] for s in catalog["subjects"]},
        "room_ids": {r["id"] for r in catalog["rooms"]},
        "room_types": set(catalog["room_types"]),
        "subject_types": set(catalog["subject_types"]),
    }
    dropped: List[str] = []
    cleaned = dict(raw)
    for field, allowed in known.items():
        values = raw.get(field) or []
        if not isinstance(values, list):
            values = []
        kept = [v for v in values if v in allowed]
        dropped.extend(f"{field}: {v}" for v in values if v not in allowed)
        cleaned[field] = kept
    return cleaned, dropped


@router.post("/parse", response_model=CustomFilterParseResponse)
def parse_filter(
    request: CustomFilterParseRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """AI-assisted only: turns plain English into a FilterSpec. Nothing is
    evaluated here - the client calls /evaluate with the (editable) spec."""
    _resolve_run(db, user, request.run_id)
    if not request.query.strip():
        raise HTTPException(status_code=422, detail="Describe the view you need.")
    catalog = _build_catalog(db, user)
    try:
        parsed = claude_client.parse_filter_query(request.query, catalog)
        cleaned, dropped = _ground_spec(parsed.get("spec") or {}, catalog)
        spec = FilterSpec(**cleaned)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"The AI request failed for model '{claude_client.model}'. Try rephrasing, or try again.",
        ) from e
    return CustomFilterParseResponse(
        title=(parsed.get("title") or "Custom filter")[:80],
        spec=spec,
        explanation=parsed.get("explanation") or "",
        unsupported=[str(u) for u in parsed.get("unsupported", [])],
        dropped_ids=dropped,
    )


@router.post("/evaluate", response_model=CustomFilterEvaluateResponse)
def evaluate_filter(
    request: CustomFilterEvaluateRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    run = _resolve_run(db, user, request.run_id)
    cells = evaluate_for_user(db, user, request.spec, run)
    return CustomFilterEvaluateResponse(cells=[
        FilterCell(
            day=c["day"], period=c["period"],
            entries=[TimetableEntryResponse.model_validate(e) for e in c["entries"]],
            free_rooms=[FreeRoom(id=r.id, name=r.name, capacity=r.capacity, type=r.type) for r in c["free_rooms"]],
        )
        for c in cells
    ])


@router.get("/saved", response_model=List[SavedFilterResponse])
def list_saved(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(SavedFilter)
    if not is_superadmin(user):
        query = query.filter(or_(SavedFilter.department_id.is_(None), SavedFilter.department_id == _user_department(db, user)))
    return query.order_by(SavedFilter.created_at.desc()).all()


@router.post("/saved", response_model=SavedFilterResponse)
def save_filter(
    request: SavedFilterCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    if not request.name.strip():
        raise HTTPException(status_code=422, detail="Give the filter a name.")
    # Only the superadmin may publish a filter to everyone (department NULL)
    # or to another department; everyone else's stay in their own.
    department_id = request.department_id if is_superadmin(user) else _user_department(db, user)
    if department_id is None and not is_superadmin(user):
        # NULL would make it visible to every department.
        raise HTTPException(status_code=422, detail="Your account isn't linked to a department, so it can't save shared filters.")
    saved = SavedFilter(
        id=str(uuid.uuid4()),
        name=request.name.strip(),
        description=request.description,
        original_query=request.original_query,
        spec=request.spec.model_dump(),
        department_id=department_id,
        created_by=user.id,
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


@router.delete("/saved/{filter_id}")
def delete_saved(filter_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    saved = db.query(SavedFilter).filter(SavedFilter.id == filter_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved filter not found")
    own_department_admin = user.role == DEPT_ADMIN and saved.department_id == user.department_id
    if not (is_superadmin(user) or own_department_admin or saved.created_by == user.id):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can delete this filter.")
    db.delete(saved)
    db.commit()
    return {"deleted": filter_id}
