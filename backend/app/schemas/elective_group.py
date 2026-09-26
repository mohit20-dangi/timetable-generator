from pydantic import BaseModel, Field
from typing import List, Optional


class ElectiveGroupBase(BaseModel):
    name: str
    offered_subject_ids: List[str] = Field(default_factory=list)
    must_be_parallel: bool = True


class ElectiveGroupCreate(ElectiveGroupBase):
    id: str
    department_id: str


class ElectiveGroupResponse(ElectiveGroupBase):
    id: str
    department_id: str

    class Config:
        from_attributes = True


class ElectivePreflightIssue(BaseModel):
    severity: str  # blocking | warning
    message: str
    # What's actually short - lets the UI offer the specific fix (add a
    # room, offer fewer options, let them run at different times) instead
    # of one paragraph the admin has to parse themselves.
    kind: Optional[str] = None  # rooms | teachers


class ElectivePreflightResponse(BaseModel):
    feasible: bool
    offered_count: int
    rooms_available_in_common_slot: int
    qualified_teachers: int
    issues: List[ElectivePreflightIssue]
