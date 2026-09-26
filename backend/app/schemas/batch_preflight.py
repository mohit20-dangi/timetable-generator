from pydantic import BaseModel
from typing import List, Optional


class BatchPreflightIssue(BaseModel):
    severity: str  # blocking | warning
    message: str
    kind: Optional[str] = None  # rooms | teachers


class BatchPreflightResponse(BaseModel):
    """Answers "can this subject's lab batches actually run under their
    configured batch_scheduling_mode?" before the admin ever clicks
    Generate - same purpose as ElectivePreflightResponse, for the parallel
    /merged batch feature (Phase 2.9)."""
    feasible: bool
    mode: str  # independent | parallel | sequential | merged
    batch_count: int
    combined_strength: int
    rooms_available_in_common_slot: int
    qualified_teachers: int
    issues: List[BatchPreflightIssue]
