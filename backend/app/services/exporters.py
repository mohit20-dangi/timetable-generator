"""Timetable exporters: Excel, PDF, and iCalendar.

The previous build's PDF exporter silently dropped period rows that were
empty for every day (see the Run #28 export reviewed during planning) -
which hides exactly the gaps an admin most needs to see. Every exporter
here renders every configured period, whether or not it has any entries.
"""
import io
from datetime import datetime, timedelta, date as date_cls
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from icalendar import Calendar, Event
from sqlalchemy.orm import Session

from app.models import GeneratedEntry, Section, Subject, Teacher, Room, TimeSlot, LabBatch
from app.solver.calendar import DAY_ORDER

SUBJECT_COLORS = {
    "theory": "DBEAFE",  # light blue
    "lab": "D1FAE5",     # light green
    "tutorial": "EDE9FE",  # light purple
}
HEADER_FILL = "1E3A5F"


def _gather_grid(db: Session, run_id: int, rank: int, entity_type: str, entity_id: str):
    entries = (
        db.query(GeneratedEntry)
        .filter(GeneratedEntry.timetable_run_id == run_id, GeneratedEntry.alternative_rank == rank)
        .all()
    )
    if entity_type == "section":
        batch_ids = {b.id for b in db.query(LabBatch).filter(LabBatch.section_id == entity_id).all()}
        entries = [e for e in entries if e.section_id == entity_id or e.batch_id in batch_ids]
    elif entity_type == "teacher":
        entries = [e for e in entries if e.teacher_id == entity_id]
    elif entity_type == "room":
        entries = [e for e in entries if e.room_id == entity_id]

    slots = sorted(db.query(TimeSlot).all(), key=lambda t: (DAY_ORDER.index(t.day) if t.day in DAY_ORDER else 99, t.period_index))
    days = sorted({s.day for s in slots}, key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 99)
    periods = sorted({s.period_index for s in slots})

    subjects = {s.id: s for s in db.query(Subject).all()}
    teachers = {t.id: t for t in db.query(Teacher).all()}
    rooms = {r.id: r for r in db.query(Room).all()}
    sections = {s.id: s for s in db.query(Section).all()}
    batches = {b.id: b for b in db.query(LabBatch).all()}

    grid: Dict[tuple, List[GeneratedEntry]] = {}
    for e in entries:
        grid.setdefault((e.day, e.period), []).append(e)

    slot_lookup = {(s.day, s.period_index): s for s in slots}

    return {
        "days": days, "periods": periods, "grid": grid, "slot_lookup": slot_lookup,
        "subjects": subjects, "teachers": teachers, "rooms": rooms, "sections": sections, "batches": batches,
    }


def _cell_text(entries: List[GeneratedEntry], ctx: dict, entity_type: str) -> str:
    lines = []
    for e in entries:
        subject = ctx["subjects"].get(e.subject_id)
        subject_name = subject.name if subject else e.subject_id
        parts = [subject_name]
        if entity_type != "section":
            who = ctx["sections"].get(e.section_id)
            if who:
                parts.append(who.name)
            elif e.batch_id:
                batch = ctx["batches"].get(e.batch_id)
                parts.append(batch.batch_name if batch else e.batch_id)
        if entity_type != "teacher":
            teacher = ctx["teachers"].get(e.teacher_id)
            parts.append(teacher.name if teacher else e.teacher_id)
        if entity_type != "room":
            room = ctx["rooms"].get(e.room_id)
            parts.append(room.name if room else e.room_id)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _subject_type(entries: List[GeneratedEntry], ctx: dict) -> Optional[str]:
    if not entries:
        return None
    subject = ctx["subjects"].get(entries[0].subject_id)
    return subject.type if subject else None


def export_xlsx(db: Session, run_id: int, rank: int, entity_type: str, entity_id: str, title: str) -> bytes:
    ctx = _gather_grid(db, run_id, rank, entity_type, entity_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Timetable"

    ws.merge_cells("A1:H1")
    ws["A1"] = title
    ws["A1"].font = Font(size=16, bold=True, color="1E3A5F")
    ws.row_dimensions[1].height = 28

    header_row = 3
    ws.cell(row=header_row, column=1, value="Period / Time").font = Font(bold=True, color="FFFFFF")
    ws.cell(row=header_row, column=1).fill = PatternFill("solid", fgColor=HEADER_FILL)
    for col, day in enumerate(ctx["days"], start=2):
        cell = ws.cell(row=header_row, column=col, value=day)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center")

    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    row = header_row + 1
    # Render EVERY configured period, even ones that are empty across every
    # day - this is the direct fix for the previous exporter's row-dropping.
    for period in ctx["periods"]:
        sample_slot = next((ctx["slot_lookup"].get((d, period)) for d in ctx["days"] if (d, period) in ctx["slot_lookup"]), None)
        label = f"Period {period}"
        if sample_slot:
            label += f"\n{sample_slot.start_time.strftime('%H:%M')}-{sample_slot.end_time.strftime('%H:%M')}"
        cell = ws.cell(row=row, column=1, value=label)
        cell.font = Font(bold=True)
        cell.border = border
        cell.alignment = Alignment(wrap_text=True, vertical="center")

        for col, day in enumerate(ctx["days"], start=2):
            entries = ctx["grid"].get((day, period), [])
            text = _cell_text(entries, ctx, entity_type)
            cell = ws.cell(row=row, column=col, value=text)
            cell.border = border
            cell.alignment = Alignment(wrap_text=True, vertical="center")
            subject_type = _subject_type(entries, ctx)
            if subject_type and subject_type in SUBJECT_COLORS:
                cell.fill = PatternFill("solid", fgColor=SUBJECT_COLORS[subject_type])
        row += 1

    ws.column_dimensions["A"].width = 18
    for col in range(2, 2 + len(ctx["days"])):
        ws.column_dimensions[get_column_letter(col)].width = 26
    for r in range(header_row, row):
        ws.row_dimensions[r].height = 48

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def export_pdf(db: Session, run_id: int, rank: int, entity_type: str, entity_id: str, title: str) -> bytes:
    ctx = _gather_grid(db, run_id, rank, entity_type, entity_id)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm)
    styles = getSampleStyleSheet()
    elements = [Paragraph(title, styles["Title"]), Spacer(1, 6)]

    header = ["Time"] + ctx["days"]
    data = [header]
    cell_meta = []  # (row_idx, col_idx, subject_type) for coloring, 1-indexed within table body

    for period in ctx["periods"]:
        sample_slot = next((ctx["slot_lookup"].get((d, period)) for d in ctx["days"] if (d, period) in ctx["slot_lookup"]), None)
        time_label = f"P{period}\n{sample_slot.start_time.strftime('%H:%M')}" if sample_slot else f"P{period}"
        row = [time_label]
        for day in ctx["days"]:
            entries = ctx["grid"].get((day, period), [])
            row.append(_cell_text(entries, ctx, entity_type))
        data.append(row)

    table = Table(data, repeatRows=1)
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]
    for row_idx, period in enumerate(ctx["periods"], start=1):
        for col_idx, day in enumerate(ctx["days"], start=1):
            entries = ctx["grid"].get((day, period), [])
            subject_type = _subject_type(entries, ctx)
            hex_color = {"theory": "#DBEAFE", "lab": "#D1FAE5", "tutorial": "#EDE9FE"}.get(subject_type)
            if hex_color:
                style_commands.append(("BACKGROUND", (col_idx, row_idx), (col_idx, row_idx), colors.HexColor(hex_color)))
    table.setStyle(TableStyle(style_commands))
    elements.append(table)
    doc.build(elements)
    return buffer.getvalue()


def export_ics(db: Session, run_id: int, rank: int, entity_type: str, entity_id: str, weeks: int = 15) -> bytes:
    """Weekly-recurring calendar events, starting from the next occurrence
    of each entry's weekday. Not tied to a specific AcademicTerm's real
    date range yet (see AcademicTerm.teaching_weeks for that data, not
    currently linked to a TimetableRun) - documented simplification for v1.
    """
    ctx = _gather_grid(db, run_id, rank, entity_type, entity_id)
    cal = Calendar()
    cal.add("prodid", "-//Timetable Generator//EN")
    cal.add("version", "2.0")

    today = date_cls.today()
    weekday_index = {day: idx for idx, day in enumerate(DAY_ORDER[:7])}

    for (day, period), entries in ctx["grid"].items():
        slot = ctx["slot_lookup"].get((day, period))
        if not slot or day not in weekday_index:
            continue
        days_ahead = (weekday_index[day] - today.weekday()) % 7
        first_date = today + timedelta(days=days_ahead)
        start_dt = datetime.combine(first_date, slot.start_time)
        end_dt = datetime.combine(first_date, slot.end_time)

        for entry in entries:
            event = Event()
            subject = ctx["subjects"].get(entry.subject_id)
            event.add("summary", subject.name if subject else entry.subject_id)
            event.add("dtstart", start_dt)
            event.add("dtend", end_dt)
            event.add("rrule", {"freq": "weekly", "count": weeks})
            teacher = ctx["teachers"].get(entry.teacher_id)
            room = ctx["rooms"].get(entry.room_id)
            location_parts = [p for p in [room.name if room else None] if p]
            if location_parts:
                event.add("location", ", ".join(location_parts))
            description_parts = []
            if teacher:
                description_parts.append(f"Teacher: {teacher.name}")
            event.add("description", "\n".join(description_parts))
            event.add("uid", f"{run_id}-{entry.id}@timetable-generator")
            cal.add_component(event)

    return cal.to_ical()
