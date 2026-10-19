"""Import the centrally-allotted first-year timetable PDF as hard locks.

Flow: POST /preview (upload PDF -> OCR -> proposed locks, nothing saved),
admin reviews/edits, POST /apply (replaces this department's first-year
locks). The locks are Reservation rows the solver already treats as frozen
bookings; see app/services/first_year_import.py for how the PDF is read.

Each class is also stored as a FirstYearTile (section, subject, batches,
faculty, room as printed) that its Reservation rows point at, so the
by-teacher / by-room timetable views can draw the whole class (GET /tiles).
"""
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.auth.dependencies import TEACHER, get_current_user, require_dept_admin
from app.auth.scope import assert_can_access, assert_can_manage
from app.db import get_db
from app.models import Department, FirstYearTile, Reservation, Room, Teacher, User
from app.models.reservation import FIRST_YEAR_SOURCE
from app.ocr.runner import OcrFailed, OcrUnavailable, run_ocr
from app.routers.rooms import _visible_rooms
from app.services.department_calendar import department_time_slots
from app.schemas.first_year_import import (
    CandidateOut, FacultyOut, FirstYearApplyRequest, FirstYearApplyResponse, FirstYearLockOut,
    FirstYearPreviewResponse, FirstYearTileOut, ManualLockRequest, PageOut, PeriodRef,
    PreviewRowOut, TeacherHitOut, TileIn, UnmatchedCodeOut, UnreadableCellOut,
)
from app.services.first_year_import import RoomRef, SlotRef, TeacherRef, build_preview

router = APIRouter(prefix="/api/first-year-import", tags=["First-Year Import"])

VALID_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat"}
MAX_PDF_BYTES = 30 * 1024 * 1024


def _department_or_404(db: Session, department_id: str) -> Department:
    department = db.query(Department).filter(Department.id == department_id).first()
    if not department:
        raise HTTPException(status_code=404, detail=f"Unknown department '{department_id}'")
    return department


def _department_rooms(db: Session, department_id: str) -> List[Room]:
    """The rooms this department may use - its own, central ones and rooms
    shared with it: the same set the solver can book, so a first-year class in
    any of them blocks it."""
    return _visible_rooms(db, department_id)


def _first_year_reservations(db: Session, department_id: str):
    return db.query(Reservation).filter(
        Reservation.department_id == department_id, Reservation.source == FIRST_YEAR_SOURCE)


def _delete_first_year(db: Session, department_id: str) -> int:
    removed = _first_year_reservations(db, department_id).delete(synchronize_session=False)
    db.query(FirstYearTile).filter(
        FirstYearTile.department_id == department_id, FirstYearTile.source == FIRST_YEAR_SOURCE,
    ).delete(synchronize_session=False)
    return removed


def _prune_tiles(db: Session, department_id: str) -> None:
    """A tile exists only to be drawn on its locks; drop the ones whose locks
    are all gone so the views never show a class that no longer blocks anything."""
    live = {tid for (tid,) in db.query(Reservation.tile_id).filter(
        Reservation.department_id == department_id, Reservation.tile_id.isnot(None)).distinct().all()}
    for tile in db.query(FirstYearTile).filter(FirstYearTile.department_id == department_id).all():
        if tile.id not in live:
            db.delete(tile)


def _new_tile(db: Session, department_id: str, tile: TileIn, day: str, periods: List[int]) -> FirstYearTile:
    row = FirstYearTile(
        department_id=department_id, section=tile.section, subject=tile.subject, batches=list(tile.batches),
        faculty=[f.model_dump() for f in tile.faculty], room_text=tile.room_text, day=day,
        periods=sorted(periods), start=tile.start, end=tile.end, source=FIRST_YEAR_SOURCE,
    )
    db.add(row)
    db.flush()  # need the id to point the reservations at it
    return row


def _contiguous_runs(periods: List[int]) -> List[List[int]]:
    runs: List[List[int]] = []
    for period in sorted(set(periods)):
        if runs and period == runs[-1][-1] + 1:
            runs[-1].append(period)
        else:
            runs.append([period])
    return runs


@router.post("/preview", response_model=FirstYearPreviewResponse)
async def preview_first_year_pdf(
    department_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    """Read the PDF and propose locks. Nothing is written to the database."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload the first-year timetable as a .pdf file")
    assert_can_manage(admin, department_id)
    _department_or_404(db, department_id)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF is larger than 30 MB")

    teachers = [TeacherRef(t.id, t.name, t.initials or "")
                for t in db.query(Teacher).filter(Teacher.department_id == department_id).all()]
    if not any(t.initials for t in teachers):
        raise HTTPException(
            status_code=422,
            detail="None of this department's teachers has initials set, so nothing can be matched. "
                   "Add initials in Setup -> Teachers first.")
    slots = [SlotRef(s.day, s.period_index, s.start_time, s.end_time) for s in department_time_slots(db, department_id)]
    if not slots:
        raise HTTPException(status_code=422, detail="No time slots are configured yet (Setup -> time slots).")
    rooms = [RoomRef(r.id, r.name) for r in _department_rooms(db, department_id)]

    try:
        pages = await run_in_threadpool(run_ocr, content)
    except OcrUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OcrFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    preview = build_preview(pages, teachers, rooms, slots)
    return FirstYearPreviewResponse(
        pages=[PageOut(page=p.page, section=p.section, cells=len(p.cells), warnings=p.warnings)
               for p in preview.pages],
        rows=[PreviewRowOut(
            id=r.id, page=r.page, section=r.section, day=r.day, start=r.start, end=r.end,
            periods=[PeriodRef(day=d, period=p) for d, p in r.periods], subject=r.subject,
            cell_text=r.cell_text, room_text=r.room_text, room_id=r.room_id, room_name=r.room_name,
            faculty=[FacultyOut(code=code, name=name) for code, name in r.faculty], batches=r.batches,
            teachers=[TeacherHitOut(
                code=h.code, status=h.status, teacher_id=h.teacher_id, teacher_name=h.teacher_name,
                candidates=[CandidateOut(teacher_id=c.teacher_id, name=c.name, initials=c.initials)
                            for c in h.candidates]) for h in r.teachers],
        ) for r in preview.rows],
        unmatched_codes=[UnmatchedCodeOut(code=c, count=n, name=name) for c, n, name in preview.unmatched_codes],
        unreadable=[UnreadableCellOut(**u) for u in preview.unreadable],
        warnings=preview.warnings,
    )


@router.post("/apply", response_model=FirstYearApplyResponse)
def apply_first_year_locks(
    payload: FirstYearApplyRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    """Replace the department's first-year locks with the confirmed rows.

    One transaction: the previous first-year rows are deleted and the new ones
    inserted together, so a failed request never leaves the department with
    half a lock set. Reservations from other sources are never touched.
    """
    assert_can_manage(admin, payload.department_id)
    _department_or_404(db, payload.department_id)
    teacher_ids = {t.id for t in db.query(Teacher).filter(Teacher.department_id == payload.department_id).all()}
    room_ids = {r.id for r in _department_rooms(db, payload.department_id)}
    period_ids = {(s.day, s.period_index) for s in department_time_slots(db, payload.department_id)}

    # (kind, resource_id, day, period) -> (reason, row index that first claimed it)
    wanted: Dict[Tuple[str, str, str, int], Tuple[str, int]] = {}
    for index, row in enumerate(payload.rows):
        targets = [("teacher", tid) for tid in row.teacher_ids]
        if row.room_id:
            targets.append(("room", row.room_id))
        for kind, resource_id in targets:
            known = teacher_ids if kind == "teacher" else room_ids
            if resource_id not in known:
                raise HTTPException(status_code=422, detail=f"Unknown {kind} '{resource_id}' for this department")
        for period in row.periods:
            if period.day not in VALID_DAYS or (period.day, period.period) not in period_ids:
                raise HTTPException(status_code=422, detail=f"Unknown time slot {period.day} period {period.period}")
            for kind, resource_id in targets:
                wanted.setdefault((kind, resource_id, period.day, period.period),
                                  (row.reason or "1st year (central)", index))

    _delete_first_year(db, payload.department_id)
    # one tile per (row, day) that owns at least one lock, created lazily
    tiles: Dict[Tuple[int, str], int] = {}
    for (kind, resource_id, day, period), (reason, index) in wanted.items():
        row = payload.rows[index]
        tile_id: Optional[int] = None
        if row.tile is not None:
            key = (index, day)
            if key not in tiles:
                day_periods = [p.period for p in row.periods if p.day == day]
                tiles[key] = _new_tile(db, payload.department_id, row.tile, day, day_periods).id
            tile_id = tiles[key]
        db.add(Reservation(
            department_id=payload.department_id, resource_type=kind, resource_id=resource_id,
            day=day, period=period, reason=reason, source=FIRST_YEAR_SOURCE, tile_id=tile_id,
        ))
    db.commit()
    return FirstYearApplyResponse(
        teacher_locks=sum(1 for k in wanted if k[0] == "teacher"),
        room_locks=sum(1 for k in wanted if k[0] == "room"),
    )


@router.post("/manual", response_model=FirstYearApplyResponse)
def add_manual_lock(
    payload: ManualLockRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    """Add hand-entered locks WITHOUT touching the existing ones - for classes
    the OCR missed, or when there is no PDF at all. Slots already locked for
    that resource are skipped, so entering the same thing twice is harmless."""
    assert_can_manage(admin, payload.department_id)
    _department_or_404(db, payload.department_id)
    if payload.resource_type == "teacher":
        known = {t.id for t in db.query(Teacher).filter(Teacher.department_id == payload.department_id).all()}
    else:
        known = {r.id for r in _department_rooms(db, payload.department_id)}
    if payload.resource_id not in known:
        raise HTTPException(status_code=422, detail=f"Unknown {payload.resource_type} '{payload.resource_id}' for this department")
    slots = {(s.day, s.period_index): s for s in department_time_slots(db, payload.department_id)}
    for period in payload.periods:
        if (period.day, period.period) not in slots:
            raise HTTPException(status_code=422, detail=f"Unknown time slot {period.day} period {period.period}")

    existing = {(r.day, r.period) for r in _first_year_reservations(db, payload.department_id).filter(
        Reservation.resource_type == payload.resource_type, Reservation.resource_id == payload.resource_id).all()}
    fresh = {(p.day, p.period) for p in payload.periods} - existing

    faculty = [FacultyOut(code=c.strip()) for c in payload.faculty_text.split(",") if c.strip()]
    added = 0
    for day in sorted({d for d, _ in fresh}, key=lambda d: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].index(d) if d in VALID_DAYS else 9):
        for run in _contiguous_runs([p for d, p in fresh if d == day]):
            tile = _new_tile(db, payload.department_id, TileIn(
                section=payload.section.strip(), subject=payload.subject.strip() or "1st year class",
                batches=[b.strip() for b in payload.batches if b.strip()], faculty=faculty,
                room_text=payload.room_text.strip(),
                start=slots[(day, run[0])].start_time.strftime("%H:%M"),
                end=slots[(day, run[-1])].end_time.strftime("%H:%M"),
            ), day, run)
            for period in run:
                db.add(Reservation(
                    department_id=payload.department_id, resource_type=payload.resource_type,
                    resource_id=payload.resource_id, day=day, period=period,
                    reason=payload.reason or "1st year (entered manually)", source=FIRST_YEAR_SOURCE,
                    tile_id=tile.id,
                ))
                added += 1
    db.commit()
    return FirstYearApplyResponse(
        teacher_locks=added if payload.resource_type == "teacher" else 0,
        room_locks=added if payload.resource_type == "room" else 0,
    )


@router.get("/tiles", response_model=List[FirstYearTileOut])
def list_first_year_tiles(
    department_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The first-year classes to draw in the by-teacher / by-room views: one
    entry per (class, locked teacher-or-room), carrying only the periods that
    resource is locked for. Read-only. Anyone in the department may read it; a
    TEACHER sees only their own classes, like the rest of their timetable."""
    assert_can_access(user, department_id)
    tiles = {t.id: t for t in db.query(FirstYearTile).filter(FirstYearTile.department_id == department_id).all()}
    grouped: Dict[Tuple[int, str, str], List[int]] = {}
    for r in _first_year_reservations(db, department_id).filter(Reservation.tile_id.isnot(None)).all():
        if user.role == TEACHER and not (r.resource_type == "teacher" and r.resource_id == user.teacher_id):
            continue
        if r.tile_id in tiles:
            grouped.setdefault((r.tile_id, r.resource_type, r.resource_id), []).append(r.period)
    out = []
    for (tile_id, kind, resource_id), periods in sorted(grouped.items()):
        t = tiles[tile_id]
        out.append(FirstYearTileOut(
            tile_id=t.id, resource_type=kind, resource_id=resource_id, day=t.day, periods=sorted(periods),
            section=t.section, subject=t.subject, batches=list(t.batches or []),
            faculty=[FacultyOut(**f) for f in (t.faculty or [])], room_text=t.room_text,
            start=t.start, end=t.end,
        ))
    return out


@router.get("", response_model=List[FirstYearLockOut])
def list_first_year_locks(
    department_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    assert_can_manage(admin, department_id)
    rows = _first_year_reservations(db, department_id).order_by(
        Reservation.resource_type, Reservation.resource_id, Reservation.day, Reservation.period).all()
    names = {t.id: t.name for t in db.query(Teacher).filter(Teacher.department_id == department_id).all()}
    names.update({r.id: r.name for r in _department_rooms(db, department_id)})
    return [FirstYearLockOut(
        id=r.id, resource_type=r.resource_type, resource_id=r.resource_id,
        resource_name=names.get(r.resource_id, r.resource_id), day=r.day, period=r.period, reason=r.reason,
    ) for r in rows]


@router.delete("/{lock_id}")
def delete_first_year_lock(
    lock_id: int,
    department_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    assert_can_manage(admin, department_id)
    removed = _first_year_reservations(db, department_id).filter(Reservation.id == lock_id).delete(
        synchronize_session=False)
    if not removed:
        raise HTTPException(status_code=404, detail="No such first-year lock")
    _prune_tiles(db, department_id)
    db.commit()
    return {"removed": removed}


@router.delete("")
def clear_first_year_locks(
    department_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
):
    assert_can_manage(admin, department_id)
    removed = _delete_first_year(db, department_id)
    db.commit()
    return {"removed": removed}
