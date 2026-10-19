"""Manual timetable editing for ADMIN / HOD: every change is dry-run through
the same rules generation obeys (app/services/timetable_editor.py) and is
refused with a 409 + the list of conflicts if it would introduce any."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_timetable_manager
from app.db import get_db
from app.models import TimetableRun, User
from app.schemas.timetable import TimetableRunResponse
from app.schemas.timetable_edit import (
    DraftResponse, EditApplyRequest, EditApplyResponse, EditCheckRequest, EditCheckResponse,
    FreeSlot, HistoryItem, HistoryResponse, OptionsResponse, SlotMapResponse,
)
from app.services import timetable_editor as editor
from app.services.run_access import get_run_scoped

router = APIRouter(prefix="/api/timetable/runs/{run_id}/editor", tags=["Timetable editor"])


def _context(db: Session, run_id: int, user: User, require_draft: bool = False) -> editor.EditContext:
    run = get_run_scoped(db, run_id, user)
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="Only a completed timetable can be edited.")
    if require_draft and run.is_published:
        raise HTTPException(
            status_code=409,
            detail="This timetable is published and can't be changed directly - open a draft to edit it.",
        )
    return editor.EditContext(db, run)


def _conflict(result: editor.SimResult):
    raise HTTPException(status_code=409, detail={
        "message": "This change would create conflicts, so it was not applied.",
        "violations": [c.model_dump() for c in result.conflicts],
    })


@router.post("/draft", response_model=DraftResponse)
def open_draft(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_timetable_manager)):
    run = get_run_scoped(db, run_id, user)
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="Only a completed timetable can be edited.")
    draft, created = editor.ensure_draft(db, run, user.id)
    return DraftResponse(run=TimetableRunResponse.model_validate(draft), created=created)


@router.post("/check", response_model=EditCheckResponse)
def check(run_id: int, request: EditCheckRequest, db: Session = Depends(get_db),
          user: User = Depends(require_timetable_manager)):
    ctx = _context(db, run_id, user)
    result = editor.simulate(ctx, request.operations)
    return EditCheckResponse(ok=result.ok, violations=result.conflicts, changed_groups=result.changed_groups)


@router.post("/apply", response_model=EditApplyResponse)
def apply(run_id: int, request: EditApplyRequest, db: Session = Depends(get_db),
          user: User = Depends(require_timetable_manager)):
    ctx = _context(db, run_id, user, require_draft=True)
    result = editor.simulate(ctx, request.operations)
    if not result.ok:
        _conflict(result)
    if result.changed_groups:
        editor.commit_changes(
            db, ctx, result, user.id, request.reason or editor.describe_ops(ctx, request.operations),
        )
    return EditApplyResponse(ok=True, changed_groups=result.changed_groups, run_id=run_id)


@router.get("/slot-map", response_model=SlotMapResponse)
def get_slot_map(run_id: int, session_group: str, view: Optional[str] = None, entity_id: Optional[str] = None,
                 db: Session = Depends(get_db), user: User = Depends(require_timetable_manager)):
    slots = editor.slot_map(_context(db, run_id, user), session_group, view, entity_id)
    if slots is None:
        raise HTTPException(status_code=404, detail="Class not found")
    return SlotMapResponse(session_group=session_group, slots=slots)


@router.get("/options", response_model=OptionsResponse)
def get_options(run_id: int, session_group: str, scope: str = "all_sessions", db: Session = Depends(get_db),
                user: User = Depends(require_timetable_manager)):
    found = editor.resource_options(_context(db, run_id, user), session_group, scope)
    if found is None:
        raise HTTPException(status_code=404, detail="Class not found")
    teachers, rooms = found
    return OptionsResponse(session_group=session_group, teachers=teachers, rooms=rooms)


@router.get("/free-slots", response_model=list[FreeSlot])
def get_free_slots(run_id: int, session_group: str, limit: int = 5, db: Session = Depends(get_db),
                   user: User = Depends(require_timetable_manager)):
    slots = editor.free_slots_for(_context(db, run_id, user), session_group, limit)
    return [FreeSlot(day=d, period=p) for d, p in slots]


@router.get("/history", response_model=HistoryResponse)
def get_history(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_timetable_manager)):
    get_run_scoped(db, run_id, user)
    rows, undo_stack, redo_stack = editor.history_stacks(db, run_id)
    undone = {r.id for r in redo_stack}
    items = [
        HistoryItem(
            id=r.id, action=r.action, reason=r.reason, actor_user_id=r.actor_user_id,
            created_at=r.created_at.isoformat() if r.created_at else None, undone=r.id in undone,
        )
        for r in reversed(rows)
    ]
    return HistoryResponse(items=items, can_undo=bool(undo_stack), can_redo=bool(redo_stack))


def _undo_redo(run_id: int, db: Session, user: User, redo: bool) -> EditApplyResponse:
    ctx = _context(db, run_id, user, require_draft=True)
    result = editor.undo_or_redo(db, ctx, user.id, redo)
    if result is None:
        raise HTTPException(status_code=409, detail=f"Nothing to {'redo' if redo else 'undo'}.")
    if not result.ok:
        _conflict(result)
    return EditApplyResponse(ok=True, changed_groups=result.changed_groups, run_id=run_id)


@router.post("/undo", response_model=EditApplyResponse)
def undo(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_timetable_manager)):
    return _undo_redo(run_id, db, user, redo=False)


@router.post("/redo", response_model=EditApplyResponse)
def redo(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_timetable_manager)):
    return _undo_redo(run_id, db, user, redo=True)
