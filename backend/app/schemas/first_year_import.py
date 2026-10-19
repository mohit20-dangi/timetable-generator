from typing import List, Optional

from pydantic import BaseModel, Field


class PeriodRef(BaseModel):
    day: str
    period: int


class CandidateOut(BaseModel):
    teacher_id: str
    name: str
    initials: str


class TeacherHitOut(BaseModel):
    code: str
    status: str  # matched | ambiguous | unread
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None
    candidates: List[CandidateOut] = []


class FacultyOut(BaseModel):
    code: str
    name: Optional[str] = None


class TileIn(BaseModel):
    """The class as printed on the central timetable, kept so the by-teacher
    and by-room views can draw the whole tile."""
    section: str = ""
    subject: str = ""
    batches: List[str] = []
    faculty: List[FacultyOut] = []
    room_text: str = ""
    start: str = ""
    end: str = ""


class PreviewRowOut(BaseModel):
    id: str
    page: int
    section: str
    day: str
    start: str
    end: str
    periods: List[PeriodRef]
    subject: str
    cell_text: str
    teachers: List[TeacherHitOut]
    room_text: str
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    faculty: List[FacultyOut] = []
    batches: List[str] = []


class PageOut(BaseModel):
    page: int
    section: str
    cells: int
    warnings: List[str]


class UnmatchedCodeOut(BaseModel):
    code: str
    count: int
    name: Optional[str] = None


class UnreadableCellOut(BaseModel):
    page: str
    section: str
    day: str
    start: str
    end: str
    subject: str
    text: str


class FirstYearPreviewResponse(BaseModel):
    pages: List[PageOut]
    rows: List[PreviewRowOut]
    unmatched_codes: List[UnmatchedCodeOut]
    unreadable: List[UnreadableCellOut]
    warnings: List[str]


class ApplyRow(BaseModel):
    periods: List[PeriodRef] = Field(min_length=1)
    teacher_ids: List[str] = []
    room_id: Optional[str] = None
    reason: str = ""
    tile: Optional[TileIn] = None


class FirstYearApplyRequest(BaseModel):
    department_id: str
    rows: List[ApplyRow]


class FirstYearLockOut(BaseModel):
    id: int
    resource_type: str
    resource_id: str
    resource_name: str
    day: str
    period: int
    reason: Optional[str] = None


class FirstYearApplyResponse(BaseModel):
    teacher_locks: int
    room_locks: int


class ManualLockRequest(BaseModel):
    """One hand-entered lock: a teacher or room busy at one or more periods."""
    department_id: str
    resource_type: str = Field(pattern="^(teacher|room)$")
    resource_id: str
    periods: List[PeriodRef] = Field(min_length=1)
    reason: str = ""
    # Optional tile details, so a hand-entered lock also shows as a full class
    # in the by-teacher / by-room views.
    subject: str = ""
    section: str = ""
    batches: List[str] = []
    faculty_text: str = ""   # free text, e.g. "RKD, AS"
    room_text: str = ""


class FirstYearTileOut(BaseModel):
    """One first-year class as it appears for ONE of our teachers or rooms:
    `periods` is only the slots that resource is actually locked for."""
    tile_id: int
    resource_type: str  # teacher | room
    resource_id: str
    day: str
    periods: List[int]
    section: str
    subject: str
    batches: List[str]
    faculty: List[FacultyOut]
    room_text: str
    start: str
    end: str
