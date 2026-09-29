from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from pydantic import BaseModel
from typing import Any, Dict, List
from app.db import get_database
from app.auth.dependencies import get_current_admin
from app.llm.client import nvidia_client
from app.services.timetable_edit import build_edit_context, resolve_operations, simulate, find_conflicts

router = APIRouter(prefix="/api/timetable/runs", tags=["Timetable Edit"])


class NLEditRequest(BaseModel):
    instruction: str


class ResolvedOp(BaseModel):
    entry_index: int
    field_changes: Dict[str, Any] = {}
    delete: bool = False
    description: str


class NLEditPreviewResponse(BaseModel):
    explanation: str
    resolved_operations: List[ResolvedOp]
    parse_errors: List[str]
    conflicts: List[str]
    applicable: bool


def _get_completed_run(db: Database, run_id: int) -> dict:
    run = db.timetable_runs.find_one({"_id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Timetable run not found")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail="Only a completed run can be edited")
    return run


@router.post("/{run_id}/edit-nl/preview", response_model=NLEditPreviewResponse)
def preview_nl_edit(
    run_id: int,
    request: NLEditRequest,
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    run = _get_completed_run(db, run_id)
    context = build_edit_context(db, run["entries"])

    try:
        llm_result = nvidia_client.parse_timetable_edit(request.instruction, context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM parsing failed: {str(e)}")

    if llm_result.get("unclear") or not llm_result.get("operations"):
        return NLEditPreviewResponse(
            explanation=llm_result.get("explanation") or "Could not understand the requested change.",
            resolved_operations=[],
            parse_errors=[],
            conflicts=[],
            applicable=False,
        )

    resolved, errors = resolve_operations(run["entries"], llm_result["operations"], context)

    conflicts: List[str] = []
    if resolved and not errors:
        simulated = simulate(run["entries"], resolved)
        conflicts = find_conflicts(simulated, context)

    return NLEditPreviewResponse(
        explanation=llm_result.get("explanation", ""),
        resolved_operations=resolved,
        parse_errors=errors,
        conflicts=conflicts,
        applicable=bool(resolved) and not errors and not conflicts,
    )


@router.post("/{run_id}/edit-nl/apply")
def apply_nl_edit(
    run_id: int,
    resolved_operations: List[ResolvedOp],
    db: Database = Depends(get_database),
    _admin: dict = Depends(get_current_admin),
):
    run = _get_completed_run(db, run_id)
    context = build_edit_context(db, run["entries"])

    ops = [op.model_dump() for op in resolved_operations]
    if not ops:
        raise HTTPException(status_code=400, detail="No operations to apply")

    # Re-validate against the run's CURRENT entries (not just what the preview saw) -
    # the preview may be stale if another edit landed in between.
    simulated = simulate(run["entries"], ops)
    conflicts = find_conflicts(simulated, context)
    if conflicts:
        raise HTTPException(status_code=409, detail={"message": "This edit would create conflicts", "conflicts": conflicts})

    db.timetable_runs.update_one({"_id": run_id}, {"$set": {"entries": simulated}})
    return {"message": "Timetable updated", "entries": simulated}
