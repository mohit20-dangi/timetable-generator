"""Conflict-gated manual editing of a generated timetable.

Every edit - a drag-and-drop move, a teacher/room change, an add/delete, an
AI-proposed change - is expressed as a list of operations (app/schemas/
timetable_edit.py), applied to an IN-MEMORY copy of the run's rank-1
entries, and then held to exactly the rules generation is held to:
app/services/schedule_validator.validate_entries (clashes, capacity, lunch,
availability, teacher caps, ...), plus checks only an edit can break
(teacher qualification, room eligibility, locks, bookings held by OTHER
published runs or reservations, hard admin rules).

The gate is "no NEW violations": a run that already carries an issue can
still be edited, but no edit may make things worse. Nothing is written
unless the gate passes (see commit_changes).
"""
import re
import uuid
from dataclasses import dataclass, field as dc_field, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import (
    AuditLog, GeneratedEntry, LabBatch, Reservation, Room, Section, Subject, Teacher,
    TeacherSubject, TimeSlot, TimetableRun,
)
from app.services.entry_teachers import co_teacher_ids, entry_teacher_ids
from app.schemas.timetable import ConflictDetail
from app.schemas.timetable_edit import (
    AddOp, ChangeRoomOp, ChangeTeacherOp, DeleteOp, LockOp, MoveOp, SwapOp, UnlockOp,
)
from app.services.schedule_validator import ValidationRefs, validate_entries
from app.services.department_calendar import department_time_slots
from app.solver.calendar import build_slot_calendar
from app.solver.types import ScheduledSession
from app.solver.validator import _validate_custom_rules

EDIT_ACTIONS = ("timetable_edit", "timetable_undo", "timetable_redo")
DRAFT_SUMMARY = "Draft for manual editing"


@dataclass
class DraftEntry:
    id: int
    session_group: Optional[str]
    day: str
    period: int
    section_id: Optional[str]
    batch_id: Optional[str]
    subject_id: Optional[str]
    teacher_id: Optional[str]
    room_id: Optional[str]
    # Extra teachers on a co-taught lab (Subject.teachers_required > 1).
    # The editor never reassigns these - ChangeTeacherOp only ever touches
    # the lead - but it must carry them through every edit, snapshot and
    # save, or editing anything about a co-taught lab would silently drop
    # its second supervisor.
    co_teacher_ids: List[str] = dc_field(default_factory=list)
    is_locked: bool = False
    is_manual: bool = False
    timetable_run_id: Optional[int] = None
    alternative_rank: int = 1


@dataclass
class Restore:
    """Internal op (undo/redo): put these groups back exactly as recorded.
    A group mapped to [] is removed."""
    snapshot: Dict[str, List[dict]]


def gk(e) -> str:
    """The block a row belongs to (legacy rows without a session_group are
    their own one-row block)."""
    return e.session_group or f"row:{e.id}"


def _from_row(e: GeneratedEntry) -> DraftEntry:
    return DraftEntry(
        id=e.id, session_group=e.session_group, day=e.day, period=e.period,
        section_id=e.section_id, batch_id=e.batch_id, subject_id=e.subject_id,
        teacher_id=e.teacher_id, room_id=e.room_id, co_teacher_ids=co_teacher_ids(e),
        is_locked=bool(e.is_locked), is_manual=bool(e.is_manual),
        timetable_run_id=e.timetable_run_id, alternative_rank=e.alternative_rank or 1,
    )


def load_entries(db: Session, run_id: int) -> List[DraftEntry]:
    rows = (
        db.query(GeneratedEntry)
        .filter(GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == 1)
        .all()
    )
    return [_from_row(r) for r in rows]


def _snap(e: DraftEntry) -> dict:
    return {
        "session_group": gk(e), "day": e.day, "period": e.period, "section_id": e.section_id,
        "batch_id": e.batch_id, "subject_id": e.subject_id, "teacher_id": e.teacher_id,
        "co_teacher_ids": list(e.co_teacher_ids or []),
        "room_id": e.room_id, "is_locked": e.is_locked, "is_manual": e.is_manual,
    }


def _group_snapshot(entries: List[DraftEntry], groups) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for e in entries:
        if gk(e) in groups:
            out.setdefault(gk(e), []).append(_snap(e))
    return out


# --------------------------------------------------------------------------
# Context: everything an edit needs that doesn't change between operations
# --------------------------------------------------------------------------
class EditContext:
    def __init__(self, db: Session, run: TimetableRun):
        self.db = db
        self.run = run
        self.entries: List[DraftEntry] = load_entries(db, run.id)
        self.slots = build_slot_calendar([
            {"day": t.day, "period_index": t.period_index, "start_time": t.start_time, "end_time": t.end_time}
            for t in department_time_slots(db, run.department_id)
        ])
        self.by_dp = {(s.day, s.period_index): s for s in self.slots}
        self.by_index = {s.index: s for s in self.slots}
        self._external = None
        self._custom = None
        self._baseline = None
        self._batch_section = None
        self._lookups = None
        self._refs = None

    def lookups(self):
        """Reference tables that don't change while one request simulates
        many candidate edits (slot-map simulates one per slot)."""
        if self._lookups is None:
            db = self.db
            self._lookups = SimpleNamespace(
                qualified={(r.teacher_id, r.subject_id) for r in db.query(TeacherSubject).all()},
                rooms={r.id: r for r in db.query(Room).all()},
                teachers={t.id: t for t in db.query(Teacher).all()},
                subjects={s.id: s for s in db.query(Subject).all()},
            )
        return self._lookups

    # -- slots -----------------------------------------------------------
    def slot_of(self, e):
        return self.by_dp.get((e.day, e.period))

    def block(self, entries: List[DraftEntry], group: str) -> List[DraftEntry]:
        rows = [e for e in entries if gk(e) == group]
        rows.sort(key=lambda e: self.slot_of(e).index if self.slot_of(e) else 10**6)
        return rows

    def contiguous(self, anchor, length: int) -> Optional[list]:
        positions = [anchor]
        current = anchor
        while len(positions) < length:
            nxt = self.by_index.get(current.index + 1)
            if not nxt or nxt.day != current.day or nxt.start_minutes != current.end_minutes:
                return None
            positions.append(nxt)
            current = nxt
        return positions

    # -- lookups ---------------------------------------------------------
    @property
    def batch_section(self) -> Dict[str, str]:
        if self._batch_section is None:
            self._batch_section = {b.id: b.section_id for b in self.db.query(LabBatch).all()}
        return self._batch_section

    def section_of(self, e) -> Optional[str]:
        return e.section_id or (self.batch_section.get(e.batch_id) if e.batch_id else None)

    # -- bookings held by other published runs / reservations -------------
    def external_bookings(self) -> Dict[Tuple[str, str, str, int], str]:
        if self._external is not None:
            return self._external
        db, run = self.db, self.run
        lineage = {run.id}
        parent = run.parent_run_id
        while parent and parent not in lineage:
            lineage.add(parent)
            p = db.query(TimetableRun).filter(TimetableRun.id == parent).first()
            parent = p.parent_run_id if p else None
        our_sections = {self.section_of(e) for e in self.entries if self.section_of(e)}
        booked: Dict[Tuple[str, str, str, int], str] = {}
        for other in db.query(TimetableRun).filter(TimetableRun.is_published.is_(True)).all():
            if other.id in lineage:
                continue
            rows = db.query(GeneratedEntry).filter(
                GeneratedEntry.timetable_run_id == other.id, GeneratedEntry.alternative_rank == 1
            ).all()
            for r in rows:
                if self.section_of(r) in our_sections:
                    continue  # publishing this run replaces that one for these sections
                label = f"published timetable #{other.id}"
                for tid in entry_teacher_ids(r):
                    booked[("teacher", tid, r.day, r.period)] = label
                if r.room_id:
                    booked[("room", r.room_id, r.day, r.period)] = label
        for res in db.query(Reservation).filter(Reservation.department_id == run.department_id).all():
            if res.source_run_id in lineage:
                continue
            booked[(res.resource_type, res.resource_id, res.day, res.period)] = res.reason or "a reservation"
        self._external = booked
        return booked

    # -- hard admin rules --------------------------------------------------
    def custom_rules(self):
        if self._custom is None:
            self._custom = ([], [])
            try:
                from app.solver.data_loader import load_department_problem
                problem, _ = load_department_problem(
                    self.db, self.run.department_id, self.run.year_ids, self.run.section_ids,
                    self.run.scope_mode or "fit_into_existing",
                )
                self._custom = ([r for r in problem.custom_rules if r.hard], problem.fixed_bookings)
            except Exception:  # noqa: BLE001 - rules are an extra gate, never a reason to break editing
                pass
        return self._custom

    def custom_violations(self, entries: List[DraftEntry]):
        rules, fixed = self.custom_rules()
        if not rules:
            return []
        sessions, ranges = [], {}
        for g in {gk(e) for e in entries}:
            rows = self.block(entries, g)
            slots = [self.slot_of(r) for r in rows]
            if not all(slots):
                continue
            first = rows[0]
            sessions.append(ScheduledSession(
                demand_id=g, subject_id=first.subject_id or "",
                audience_type="batch" if first.batch_id else "section",
                audience_id=first.batch_id or first.section_id or "",
                parent_section_id=self.section_of(first) or "",
                start_slot_index=slots[0].index, duration=len(rows),
                room_id=first.room_id or "", teacher_id=first.teacher_id or "",
            ))
            ranges[g] = (slots[0].index, slots[-1].index, slots[0].day)
        stub = SimpleNamespace(custom_rules=rules, fixed_bookings=fixed)
        return _validate_custom_rules(stub, sessions, self.by_index, {}, ranges)

    # -- baseline ----------------------------------------------------------
    def all_violations(self, entries: List[DraftEntry]):
        if self._refs is None:
            self._refs = ValidationRefs(self.db, self.run.department_id)
        return list(validate_entries(self.db, entries, self._refs)) + list(self.custom_violations(entries))

    def baseline(self):
        if self._baseline is None:
            self._baseline = _index(self.all_violations(self.entries))
        return self._baseline


# --------------------------------------------------------------------------
# Violation diffing: only NEW (or worsened) violations block an edit
# --------------------------------------------------------------------------
_ID_RE = re.compile(r"\b(?:entries|Entry) [-\d, ]+")
_COUNT_RE = re.compile(r"(?:scheduled|has|teaches on) (\d+)")


def _is_counted(vtype: str) -> bool:
    return vtype.endswith("_CAP") or vtype.startswith(("CUSTOM_MAX", "CUSTOM_TEACHER"))


def _sig(v) -> Tuple[str, str]:
    msg = _ID_RE.sub("entry", v.message)
    if _is_counted(v.type):
        msg = _COUNT_RE.sub(lambda m: m.group(0).rsplit(" ", 1)[0] + " #", msg)
    return (v.type, msg)


def _count(v) -> int:
    m = _COUNT_RE.search(v.message)
    return int(m.group(1)) if m else 0


def _index(violations) -> Dict[Tuple[str, str], int]:
    return {_sig(v): _count(v) for v in violations}


def _introduced(base, violations) -> list:
    out = []
    for v in violations:
        sig = _sig(v)
        if sig not in base or (_is_counted(v.type) and _count(v) > base[sig]):
            out.append(v)
    return out


# --------------------------------------------------------------------------
# Applying operations to an in-memory copy
# --------------------------------------------------------------------------
@dataclass
class SimResult:
    entries: List[DraftEntry]
    changed_groups: List[str]
    conflicts: List[ConflictDetail]

    @property
    def ok(self) -> bool:
        return not self.conflicts


def _err(errors, type_, message):
    errors.append(ConflictDetail(type=type_, message=message))


def _audience(e) -> Tuple[Optional[str], str]:
    return (e.subject_id, e.batch_id or e.section_id or "")


def _apply(ctx: EditContext, entries: List[DraftEntry], ops) -> Tuple[List[DraftEntry], set, list]:
    entries = [replace(e) for e in entries]
    changed: set = set()
    errors: list = []
    temp_id = [-1]

    def need_block(g):
        rows = ctx.block(entries, g)
        if not rows:
            _err(errors, "NOT_FOUND", f"Class block '{g}' was not found in this timetable.")
        return rows

    def locked(rows, what):
        if any(r.is_locked for r in rows):
            _err(errors, "LOCKED", f"This class is locked - unlock it before you {what} it.")
            return True
        return False

    def place(rows, positions):
        for r, s in zip(rows, positions):
            r.day, r.period = s.day, s.period_index
            r.is_manual = True

    def exists(model, id_, type_, label):
        if not ctx.db.query(model).filter(model.id == id_).first():
            _err(errors, type_, f"{label} '{id_}' does not exist.")
            return False
        return True

    for op in ops:
        if isinstance(op, MoveOp):
            rows = need_block(op.session_group)
            if not rows or locked(rows, "move"):
                continue
            anchor = ctx.by_dp.get((op.day, op.period))
            if not anchor:
                _err(errors, "SLOT_INVALID", f"{op.day} period {op.period} is not a configured time slot.")
                continue
            positions = ctx.contiguous(anchor, len(rows))
            if positions is None:
                _err(errors, "NOT_CONTIGUOUS", "That time doesn't have enough back-to-back periods for this class.")
                continue
            place(rows, positions)
            changed.add(op.session_group)

        elif isinstance(op, SwapOp):
            a, b = need_block(op.session_group_a), need_block(op.session_group_b)
            if not a or not b or locked(a, "swap") or locked(b, "swap"):
                continue
            sa, sb = ctx.slot_of(a[0]), ctx.slot_of(b[0])
            pa = ctx.contiguous(sb, len(a)) if sb else None
            pb = ctx.contiguous(sa, len(b)) if sa else None
            if pa is None or pb is None:
                _err(errors, "NOT_CONTIGUOUS", "These two classes can't swap - one doesn't fit where the other sits.")
                continue
            place(a, pa)
            place(b, pb)
            changed |= {op.session_group_a, op.session_group_b}

        elif isinstance(op, ChangeTeacherOp):
            rows = need_block(op.session_group)
            if not rows or not exists(Teacher, op.teacher_id, "UNKNOWN_TEACHER", "Teacher"):
                continue
            if op.scope == "all_sessions":
                key = _audience(rows[0])
                targets = [e for e in entries if _audience(e) == key]
            else:
                targets = rows
            if locked(targets, "reassign"):
                continue
            for e in targets:
                e.teacher_id = op.teacher_id
                e.is_manual = True
                changed.add(gk(e))

        elif isinstance(op, ChangeRoomOp):
            rows = need_block(op.session_group)
            if not rows or locked(rows, "change the room of") or not exists(Room, op.room_id, "UNKNOWN_ROOM", "Room"):
                continue
            for e in rows:
                e.room_id = op.room_id
                e.is_manual = True
            changed.add(op.session_group)

        elif isinstance(op, DeleteOp):
            rows = need_block(op.session_group)
            if not rows or locked(rows, "delete"):
                continue
            entries = [e for e in entries if gk(e) != op.session_group]
            changed.add(op.session_group)

        elif isinstance(op, AddOp):
            if bool(op.section_id) == bool(op.batch_id):
                _err(errors, "BAD_AUDIENCE", "Choose either a section or a lab batch for the new class.")
                continue
            if op.section_id and not exists(Section, op.section_id, "UNKNOWN_SECTION", "Section"):
                continue
            if op.batch_id and op.batch_id not in ctx.batch_section:
                _err(errors, "UNKNOWN_BATCH", f"Lab batch '{op.batch_id}' does not exist.")
                continue
            if not (exists(Subject, op.subject_id, "UNKNOWN_SUBJECT", "Subject")
                    and exists(Teacher, op.teacher_id, "UNKNOWN_TEACHER", "Teacher")
                    and exists(Room, op.room_id, "UNKNOWN_ROOM", "Room")):
                continue
            anchor = ctx.by_dp.get((op.day, op.period))
            positions = ctx.contiguous(anchor, op.duration) if anchor else None
            if positions is None:
                _err(errors, "NOT_CONTIGUOUS", "That time isn't a configured slot with enough back-to-back periods.")
                continue
            group = f"manual:{uuid.uuid4().hex[:12]}"
            for s in positions:
                entries.append(DraftEntry(
                    id=temp_id[0], session_group=group, day=s.day, period=s.period_index,
                    section_id=op.section_id, batch_id=op.batch_id, subject_id=op.subject_id,
                    teacher_id=op.teacher_id, room_id=op.room_id, is_manual=True,
                    timetable_run_id=ctx.run.id,
                ))
                temp_id[0] -= 1
            changed.add(group)

        elif isinstance(op, (LockOp, UnlockOp)):
            rows = need_block(op.session_group)
            for e in rows:
                e.is_locked = isinstance(op, LockOp)
            if rows:
                changed.add(op.session_group)

        elif isinstance(op, Restore):
            entries = [e for e in entries if gk(e) not in op.snapshot]
            for g, rows in op.snapshot.items():
                for r in rows:
                    entries.append(DraftEntry(
                        id=temp_id[0], session_group=g, timetable_run_id=ctx.run.id,
                        day=r["day"], period=r["period"], section_id=r.get("section_id"),
                        batch_id=r.get("batch_id"), subject_id=r.get("subject_id"),
                        teacher_id=r.get("teacher_id"), room_id=r.get("room_id"),
                        co_teacher_ids=list(r.get("co_teacher_ids") or []),
                        is_locked=bool(r.get("is_locked")), is_manual=bool(r.get("is_manual")),
                    ))
                    temp_id[0] -= 1
                changed.add(g)
    return entries, changed, errors


def _room_problem(ctx: EditContext, room: Room, subject: Optional[Subject]) -> Optional[str]:
    """Why this room can never host this subject for this department, or None."""
    dept = ctx.run.department_id
    accessible = (
        room.department_id is None or room.department_id == dept
        or (room.shared_with_departments and dept in room.shared_with_departments)
    )
    if not accessible:
        return f"Room {room.name} belongs to another department and isn't shared with this one."
    if subject is None:
        return None
    if subject.requires_room_type and room.type != subject.requires_room_type:
        return f"{subject.name} needs a {subject.requires_room_type} room, but {room.name} is a {room.type} room."
    missing = set(subject.requires_equipment or []) - set(room.equipment or [])
    if missing:
        return f"Room {room.name} is missing required equipment: {', '.join(sorted(missing))}."
    return None


def _edit_only_checks(ctx: EditContext, new: List[DraftEntry], changed: set) -> list:
    """Rules the persisted-run validator can't see because it only looks at
    one run's rows: who may teach what, which rooms suit a subject, and
    what other published runs/reservations already hold."""
    errors: list = []
    original: Dict[str, List[DraftEntry]] = {}
    for e in ctx.entries:
        original.setdefault(gk(e), []).append(e)
    external = ctx.external_bookings()
    lk = ctx.lookups()
    qualified, rooms, teachers, subjects = lk.qualified, lk.rooms, lk.teachers, lk.subjects

    for g in changed:
        rows = [e for e in new if gk(e) == g]
        if not rows:
            continue
        old = original.get(g, [])
        first, old_first = rows[0], (old[0] if old else None)
        subject = subjects.get(first.subject_id)
        if (old_first is None or old_first.teacher_id != first.teacher_id) and first.teacher_id \
                and (first.teacher_id, first.subject_id) not in qualified:
            t = teachers.get(first.teacher_id)
            _err(errors, "TEACHER_NOT_QUALIFIED",
                 f"{t.name if t else first.teacher_id} is not qualified to teach "
                 f"{subject.name if subject else first.subject_id}.")
        if (old_first is None or old_first.room_id != first.room_id) and first.room_id in rooms:
            problem = _room_problem(ctx, rooms[first.room_id], subject)
            if problem:
                _err(errors, "ROOM_NOT_ELIGIBLE", problem)
        old_keys = {(e.day, e.period, e.teacher_id, e.room_id) for e in old}
        for e in rows:
            if (e.day, e.period, e.teacher_id, e.room_id) in old_keys:
                continue
            for tid in entry_teacher_ids(e):
                tb = external.get(("teacher", tid, e.day, e.period))
                if tb:
                    t = teachers.get(tid)
                    _err(errors, "TEACHER_BOOKED_ELSEWHERE",
                         f"{t.name if t else tid} is already teaching on {e.day} period {e.period} ({tb}).")
            rb = external.get(("room", e.room_id, e.day, e.period))
            if rb:
                r = rooms.get(e.room_id)
                _err(errors, "ROOM_BOOKED_ELSEWHERE",
                     f"Room {r.name if r else e.room_id} is already booked on {e.day} period {e.period} ({rb}).")
    return errors


def _dedupe(conflicts):
    seen, out = set(), []
    for c in conflicts:
        if (c.type, c.message) not in seen:
            seen.add((c.type, c.message))
            out.append(c)
    return out


def simulate(ctx: EditContext, ops) -> SimResult:
    """Dry-run `ops`. `conflicts` empty means the edit is allowed."""
    new, changed, errors = _apply(ctx, ctx.entries, ops)
    if errors:
        return SimResult(ctx.entries, [], _dedupe(errors))
    if not changed:
        return SimResult(new, [], [])
    conflicts = _edit_only_checks(ctx, new, changed)
    # Pure lock/unlock changes can't introduce a schedule violation.
    if not all(isinstance(o, (LockOp, UnlockOp)) for o in ops):
        introduced = _introduced(ctx.baseline(), ctx.all_violations(new))
        conflicts += [ConflictDetail(type=v.type, message=v.message) for v in introduced]
    return SimResult(new, sorted(changed), _dedupe(conflicts))


# --------------------------------------------------------------------------
# Persisting
# --------------------------------------------------------------------------
def describe_ops(ctx: EditContext, ops) -> str:
    names = {s.id: s.name for s in ctx.db.query(Subject).all()}
    by_group = {gk(e): e for e in ctx.entries}

    def label(g):
        e = by_group.get(g)
        return names.get(e.subject_id, e.subject_id) if e else g

    parts = []
    for op in ops:
        if isinstance(op, MoveOp):
            parts.append(f"Moved {label(op.session_group)} to {op.day} period {op.period}")
        elif isinstance(op, SwapOp):
            parts.append(f"Swapped {label(op.session_group_a)} with {label(op.session_group_b)}")
        elif isinstance(op, ChangeTeacherOp):
            parts.append(f"Changed teacher of {label(op.session_group)} to {op.teacher_id}")
        elif isinstance(op, ChangeRoomOp):
            parts.append(f"Changed room of {label(op.session_group)} to {op.room_id}")
        elif isinstance(op, DeleteOp):
            parts.append(f"Deleted {label(op.session_group)}")
        elif isinstance(op, AddOp):
            parts.append(f"Added {names.get(op.subject_id, op.subject_id)} on {op.day} period {op.period}")
        elif isinstance(op, LockOp):
            parts.append(f"Locked {label(op.session_group)}")
        elif isinstance(op, UnlockOp):
            parts.append(f"Unlocked {label(op.session_group)}")
    return "; ".join(parts)


def commit_changes(
    db: Session, ctx: EditContext, result: SimResult, user_id: Optional[int],
    reason: Optional[str], action: str = "timetable_edit",
):
    """Writes a SimResult that already passed the gate, in place, and logs it."""
    changed = set(result.changed_groups)
    before = _group_snapshot(ctx.entries, changed)
    after = _group_snapshot(result.entries, changed)
    # A group that only exists on one side is recorded as [] on the other so
    # undo/redo knows to remove/restore it.
    for g in changed:
        before.setdefault(g, [])
        after.setdefault(g, [])
    old_ids = [e.id for e in ctx.entries if gk(e) in changed]
    if old_ids:
        db.query(GeneratedEntry).filter(GeneratedEntry.id.in_(old_ids)).delete(synchronize_session=False)
    for e in result.entries:
        if gk(e) in changed:
            db.add(GeneratedEntry(
                timetable_run_id=ctx.run.id, alternative_rank=1, session_group=gk(e), day=e.day,
                period=e.period, section_id=e.section_id, batch_id=e.batch_id, subject_id=e.subject_id,
                teacher_id=e.teacher_id, room_id=e.room_id, co_teacher_ids=list(e.co_teacher_ids or []),
                is_locked=e.is_locked, is_manual=e.is_manual,
            ))
    db.add(AuditLog(
        actor_user_id=user_id, action=action, entity_type="timetable_run", entity_id=str(ctx.run.id),
        before=before, after=after, reason=reason,
    ))
    db.commit()


# --------------------------------------------------------------------------
# History / undo / redo (replayed from the audit log)
# --------------------------------------------------------------------------
def history_stacks(db: Session, run_id: int):
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "timetable_run", AuditLog.entity_id == str(run_id),
                AuditLog.action.in_(EDIT_ACTIONS))
        .order_by(AuditLog.id)
        .all()
    )
    undo_stack, redo_stack = [], []
    for r in rows:
        if r.action == "timetable_edit":
            undo_stack.append(r)
            redo_stack.clear()
        elif r.action == "timetable_undo" and undo_stack:
            redo_stack.append(undo_stack.pop())
        elif r.action == "timetable_redo" and redo_stack:
            undo_stack.append(redo_stack.pop())
    return rows, undo_stack, redo_stack


def undo_or_redo(db: Session, ctx: EditContext, user_id: Optional[int], redo: bool) -> Optional[SimResult]:
    """None if there is nothing to undo/redo; otherwise the SimResult
    (conflicts non-empty = blocked by the gate, nothing written)."""
    _rows, undo_stack, redo_stack = history_stacks(db, ctx.run.id)
    stack = redo_stack if redo else undo_stack
    if not stack:
        return None
    target = stack[-1]
    snapshot = (target.after if redo else target.before) or {}
    groups = set((target.before or {}).keys()) | set((target.after or {}).keys())
    result = simulate(ctx, [Restore(snapshot={g: snapshot.get(g, []) for g in groups})])
    if result.ok:
        commit_changes(
            db, ctx, result, user_id, ("Redo: " if redo else "Undo: ") + (target.reason or ""),
            action="timetable_redo" if redo else "timetable_undo",
        )
    return result


# --------------------------------------------------------------------------
# Draft sessions
# --------------------------------------------------------------------------
def ensure_draft(db: Session, run: TimetableRun, user_id: Optional[int]) -> Tuple[TimetableRun, bool]:
    """A published run is never edited: fork (once) an unpublished draft and
    edit that. An unpublished run is its own draft."""
    if not run.is_published:
        return run, False
    existing = (
        db.query(TimetableRun)
        .filter(TimetableRun.parent_run_id == run.id, TimetableRun.is_published.is_(False),
                TimetableRun.change_summary == DRAFT_SUMMARY)
        .order_by(TimetableRun.id.desc()).first()
    )
    if existing:
        return existing, False
    draft = TimetableRun(
        department_id=run.department_id, constraint_profile_id=run.constraint_profile_id,
        status="completed", scope_mode=run.scope_mode, year_ids=run.year_ids,
        section_ids=run.section_ids, num_alternatives=1, parent_run_id=run.id,
        term_id=run.term_id, change_summary=DRAFT_SUMMARY, created_by=user_id,
        solver_output=run.solver_output, subject_overrides=run.subject_overrides,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.flush()
    for e in load_entries(db, run.id):
        db.add(GeneratedEntry(
            timetable_run_id=draft.id, alternative_rank=1, session_group=gk(e), day=e.day, period=e.period,
            section_id=e.section_id, batch_id=e.batch_id, subject_id=e.subject_id,
            teacher_id=e.teacher_id, room_id=e.room_id, co_teacher_ids=list(e.co_teacher_ids or []),
            is_locked=e.is_locked, is_manual=e.is_manual,
        ))
    db.commit()
    db.refresh(draft)
    return draft, True


# --------------------------------------------------------------------------
# Assistance for the UI: where can this go / who can teach it / which room
# --------------------------------------------------------------------------
def _reasons(result: SimResult) -> List[str]:
    return [c.message for c in result.conflicts]


def free_slots_for(ctx: EditContext, group: str, limit: int = 5) -> List[Tuple[str, int]]:
    block = ctx.block(ctx.entries, group)
    if not block:
        return []
    current = (block[0].day, block[0].period)
    out = []
    for slot in ctx.slots:
        if (slot.day, slot.period_index) == current:
            continue
        if simulate(ctx, [MoveOp(session_group=group, day=slot.day, period=slot.period_index)]).ok:
            out.append((slot.day, slot.period_index))
            if len(out) >= limit:
                break
    return out


def slot_map(ctx: EditContext, group: str, view: Optional[str] = None, entity_id: Optional[str] = None):
    """For every configured slot: can the block move there, and - if a
    block of the viewed entity starts there - could the two swap?"""
    if not ctx.block(ctx.entries, group):
        return None

    def in_view(e) -> bool:
        if not view or not entity_id:
            return False
        if view == "section":
            return ctx.section_of(e) == entity_id
        if view == "teacher":
            return entity_id in entry_teacher_ids(e)
        return e.room_id == entity_id

    occupants: Dict[Tuple[str, int], str] = {}
    seen = set()
    for e in ctx.entries:
        g = gk(e)
        if g == group or g in seen or not in_view(e):
            continue
        seen.add(g)
        first = ctx.block(ctx.entries, g)[0]
        occupants[(first.day, first.period)] = g

    out = []
    for slot in ctx.slots:
        res = simulate(ctx, [MoveOp(session_group=group, day=slot.day, period=slot.period_index)])
        item = {"day": slot.day, "period": slot.period_index, "ok": res.ok, "reasons": _reasons(res)}
        occ = occupants.get((slot.day, slot.period_index))
        if occ:
            sw = simulate(ctx, [SwapOp(session_group_a=group, session_group_b=occ)])
            item.update(occupant_group=occ, swap_ok=sw.ok, swap_reasons=_reasons(sw))
        out.append(item)
    return out


def resource_options(ctx: EditContext, group: str, scope: str = "all_sessions"):
    """Qualified teachers and suitable rooms for this block, each marked
    free or blocked (with why)."""
    block = ctx.block(ctx.entries, group)
    if not block:
        return None
    first = block[0]
    subject = ctx.db.query(Subject).filter(Subject.id == first.subject_id).first()
    qualified_ids = {
        r.teacher_id for r in ctx.db.query(TeacherSubject).filter(TeacherSubject.subject_id == first.subject_id).all()
    }
    if first.teacher_id:
        qualified_ids.add(first.teacher_id)
    teachers = []
    for t in ctx.db.query(Teacher).filter(Teacher.id.in_(qualified_ids)).order_by(Teacher.name).all():
        if t.id == first.teacher_id:
            teachers.append({"id": t.id, "name": t.name, "free": True, "reasons": []})
            continue
        res = simulate(ctx, [ChangeTeacherOp(session_group=group, teacher_id=t.id, scope=scope)])
        teachers.append({"id": t.id, "name": t.name, "free": res.ok, "reasons": _reasons(res)})
    rooms = []
    for r in ctx.db.query(Room).order_by(Room.name).all():
        if r.id == first.room_id:
            rooms.append({"id": r.id, "name": r.name, "free": True, "reasons": []})
            continue
        if _room_problem(ctx, r, subject):
            continue  # wrong type / equipment / department: not an option at all
        res = simulate(ctx, [ChangeRoomOp(session_group=group, room_id=r.id)])
        rooms.append({"id": r.id, "name": r.name, "free": res.ok, "reasons": _reasons(res)})
    return teachers, rooms
