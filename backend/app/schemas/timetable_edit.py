"""Request/response shapes for the manual timetable editor
(app/routers/timetable_editor.py, app/services/timetable_editor.py)."""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from app.schemas.timetable import ConflictDetail, TimetableRunResponse


class MoveOp(BaseModel):
    type: Literal["move"] = "move"
    session_group: str
    day: str
    period: int


class SwapOp(BaseModel):
    type: Literal["swap"] = "swap"
    session_group_a: str
    session_group_b: str


class ChangeTeacherOp(BaseModel):
    type: Literal["change_teacher"] = "change_teacher"
    session_group: str
    teacher_id: str
    # "all_sessions" re-assigns every block of the same subject+audience so
    # the one-teacher-per-subject rule stays satisfied.
    scope: Literal["session", "all_sessions"] = "all_sessions"


class ChangeRoomOp(BaseModel):
    type: Literal["change_room"] = "change_room"
    session_group: str
    room_id: str


class DeleteOp(BaseModel):
    type: Literal["delete"] = "delete"
    session_group: str


class AddOp(BaseModel):
    type: Literal["add"] = "add"
    section_id: Optional[str] = None
    batch_id: Optional[str] = None
    subject_id: str
    teacher_id: str
    room_id: str
    day: str
    period: int
    duration: int = Field(default=1, ge=1, le=6)


class LockOp(BaseModel):
    type: Literal["lock"] = "lock"
    session_group: str


class UnlockOp(BaseModel):
    type: Literal["unlock"] = "unlock"
    session_group: str


EditOperation = Annotated[
    Union[MoveOp, SwapOp, ChangeTeacherOp, ChangeRoomOp, DeleteOp, AddOp, LockOp, UnlockOp],
    Field(discriminator="type"),
]


class EditCheckRequest(BaseModel):
    operations: List[EditOperation] = Field(min_length=1)


class EditApplyRequest(EditCheckRequest):
    reason: Optional[str] = None


class EditCheckResponse(BaseModel):
    ok: bool
    violations: List[ConflictDetail] = []
    changed_groups: List[str] = []


class EditApplyResponse(EditCheckResponse):
    run_id: int


class DraftResponse(BaseModel):
    run: TimetableRunResponse
    created: bool


class SlotStatus(BaseModel):
    day: str
    period: int
    ok: bool
    reasons: List[str] = []
    # A block of the viewed entity that starts in this slot, and whether
    # exchanging places with it is conflict-free.
    occupant_group: Optional[str] = None
    swap_ok: Optional[bool] = None
    swap_reasons: List[str] = []


class SlotMapResponse(BaseModel):
    session_group: str
    slots: List[SlotStatus]


class ResourceOption(BaseModel):
    id: str
    name: str
    free: bool
    reasons: List[str] = []


class OptionsResponse(BaseModel):
    session_group: str
    teachers: List[ResourceOption]
    rooms: List[ResourceOption]


class FreeSlot(BaseModel):
    day: str
    period: int


class HistoryItem(BaseModel):
    id: int
    action: str
    reason: Optional[str] = None
    actor_user_id: Optional[int] = None
    created_at: Optional[str] = None
    undone: bool = False


class HistoryResponse(BaseModel):
    items: List[HistoryItem]
    can_undo: bool
    can_redo: bool
