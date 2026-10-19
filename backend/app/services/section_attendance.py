"""Repeater sections: students repeating a year form their own section, but
for most subjects they sit in another section's class (subject X with section
A, subject Y with section B) because the curriculum changed or they simply
failed those subjects. That is stored on SectionSubject.attends_with_section_id
(+ attends_with_batch_id for labs); this module is the single place that
reads it, shared by the solver's data loader, the persisted-run validator and
the timetable views.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import LabBatch, SectionSubject


@dataclass(frozen=True)
class Attendance:
    repeater_section_id: str
    host_section_id: str
    subject_id: str
    host_batch_id: Optional[str] = None


def list_attendance(db: Session, section_ids: Optional[Iterable[str]] = None) -> List[Attendance]:
    """Every attendance link; with `section_ids`, only links where that
    section is the repeater or the host."""
    query = db.query(SectionSubject).filter(SectionSubject.attends_with_section_id.isnot(None))
    if section_ids is not None:
        ids = list(section_ids)
        query = query.filter(or_(
            SectionSubject.section_id.in_(ids), SectionSubject.attends_with_section_id.in_(ids),
        ))
    return [
        Attendance(r.section_id, r.attends_with_section_id, r.subject_id, r.attends_with_batch_id)
        for r in query.all()
    ]


def attendance_map(db: Session) -> Dict[str, List[Attendance]]:
    """{repeater section id: the classes it attends}."""
    result: Dict[str, List[Attendance]] = {}
    for link in list_attendance(db):
        result.setdefault(link.repeater_section_id, []).append(link)
    return result


def by_host(links: Iterable[Attendance]) -> Dict[Tuple[str, str], List[Attendance]]:
    """{(host section id, subject id): links}, for "who sits in this class?"."""
    result: Dict[Tuple[str, str], List[Attendance]] = {}
    for link in links:
        result.setdefault((link.host_section_id, link.subject_id), []).append(link)
    return result


def default_batch_id(batch_ids: Iterable[str]) -> Optional[str]:
    """A lab link that names no batch means "the host's first batch". The
    choice must be the same everywhere (solver, validator, views), so it is
    the lowest batch id rather than whatever order a query happens to return."""
    ids = sorted(batch_ids)
    return ids[0] if ids else None


def default_batch_by_section(db: Session) -> Dict[str, Optional[str]]:
    by_section: Dict[str, List[str]] = {}
    for batch in db.query(LabBatch).all():
        by_section.setdefault(batch.section_id, []).append(batch.id)
    return {section_id: default_batch_id(ids) for section_id, ids in by_section.items()}


def repeaters_attending(
    links_by_host: Dict[Tuple[str, str], List[Attendance]],
    default_batch: Dict[str, Optional[str]],
    host_section_id: Optional[str], subject_id: Optional[str], batch_id: Optional[str],
) -> List[str]:
    """Repeater sections that sit in the class a persisted entry describes.
    `batch_id` is the entry's batch (None for a section-level class)."""
    if host_section_id is None or subject_id is None:
        return []
    repeaters = []
    for link in links_by_host.get((host_section_id, subject_id), []):
        if batch_id is None:
            attends = True
        else:
            attends = batch_id == (link.host_batch_id or default_batch.get(host_section_id))
        if attends:
            repeaters.append(link.repeater_section_id)
    return repeaters
