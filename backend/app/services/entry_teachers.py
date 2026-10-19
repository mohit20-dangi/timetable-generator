"""One place that answers "which teachers are actually in this class?".

A GeneratedEntry keeps its first teacher in `teacher_id` and any further
ones (a lab with Subject.teachers_required > 1) in the `co_teacher_ids`
JSON list. Every reader that reasons about teacher load, clashes,
availability or "show me my timetable" must count ALL of them, or a
co-taught lab silently becomes invisible to half the app: the second
supervisor could be double-booked, over their weekly cap, or missing from
their own printed timetable, and nothing would notice.

Readers that only need a label for a cell (exports' detail line) may keep
using teacher_id - that's a display choice, not a correctness one.
"""
from typing import Any, Iterable, List


def co_teacher_ids(entry: Any) -> List[str]:
    """The extra teachers alone, tolerating the NULL that pre-migration
    rows and hand-built fixtures leave in the column."""
    raw = getattr(entry, "co_teacher_ids", None)
    if not raw:
        return []
    if isinstance(raw, str):  # a stringified list from a raw SQL insert
        return [t for t in raw.split(",") if t]
    return [t for t in raw if t]


def entry_teacher_ids(entry: Any) -> List[str]:
    """Primary teacher first, then co-teachers, de-duplicated and with
    NULLs dropped. Order is stable so callers can use [0] as "the" teacher."""
    ids: List[str] = []
    for tid in [getattr(entry, "teacher_id", None), *co_teacher_ids(entry)]:
        if tid and tid not in ids:
            ids.append(tid)
    return ids


def entry_has_teacher(entry: Any, teacher_id: str) -> bool:
    return teacher_id in entry_teacher_ids(entry)


def entries_touching_teacher(entries: Iterable[Any], teacher_id: str) -> List[Any]:
    return [e for e in entries if entry_has_teacher(e, teacher_id)]
