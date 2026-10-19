from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.timetable import TimetableEntryResponse

Day = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class FilterSpec(BaseModel):
    """The only thing the LLM ever produces for the Custom Filter tab - a
    structured, catalog-grounded description of a view, evaluated
    deterministically by app/services/custom_filter.py::evaluate.

    mode "classes": entries matching every non-empty list (AND across
    fields, OR within one field).
    mode "free_slots": (day, period) slots where EVERY listed teacher and
    section is free. If room_ids / room_types / min_room_capacity is set, a
    slot also needs at least one matching free room (the "schedule a
    seminar" case) and those rooms are listed on the cell.

    "$me" in teacher_ids resolves to the requesting user's teacher at
    evaluation time, so a saved "my free slots" filter works for anyone.
    """
    mode: Literal["classes", "free_slots"] = "classes"
    days: List[Day] = Field(default_factory=list)
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    teacher_ids: List[str] = Field(default_factory=list)
    section_ids: List[str] = Field(default_factory=list)
    subject_ids: List[str] = Field(default_factory=list)
    room_ids: List[str] = Field(default_factory=list)
    room_types: List[str] = Field(default_factory=list)
    subject_types: List[str] = Field(default_factory=list)
    min_room_capacity: Optional[int] = None

    @field_validator("time_from", "time_to")
    @classmethod
    def _valid_clock(cls, value):
        if value in (None, ""):
            return None
        parts = value.split(":")
        if len(parts) < 2 or not (parts[0].isdigit() and parts[1].isdigit()) \
                or not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
            raise ValueError("time must be HH:MM")
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"


class CustomFilterParseRequest(BaseModel):
    query: str
    run_id: Optional[int] = None


class CustomFilterParseResponse(BaseModel):
    title: str
    spec: FilterSpec
    explanation: str = ""
    unsupported: List[str] = Field(default_factory=list)
    dropped_ids: List[str] = Field(default_factory=list)


class CustomFilterEvaluateRequest(BaseModel):
    spec: FilterSpec
    run_id: Optional[int] = None


class FreeRoom(BaseModel):
    id: str
    name: str
    capacity: Optional[int] = None
    type: Optional[str] = None


class FilterCell(BaseModel):
    day: str
    period: int
    entries: List[TimetableEntryResponse] = Field(default_factory=list)
    free_rooms: List[FreeRoom] = Field(default_factory=list)


class CustomFilterEvaluateResponse(BaseModel):
    cells: List[FilterCell]


class SavedFilterCreate(BaseModel):
    name: str
    description: Optional[str] = None
    original_query: Optional[str] = None
    spec: FilterSpec
    department_id: Optional[str] = None


class SavedFilterResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    original_query: Optional[str] = None
    spec: FilterSpec
    department_id: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
