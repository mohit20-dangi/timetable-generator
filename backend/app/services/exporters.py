"""Timetable exporters: Excel, PDF, and iCalendar.

The previous build's PDF exporter silently dropped period rows that were
empty for every day (see the Run #28 export reviewed during planning) -
which hides exactly the gaps an admin most needs to see. Every exporter
here renders every configured period, whether or not it has any entries.

Phase 4.1/4.2: the printed PDF/Excel must match the reference department
timetable format - department header block, multi-period blocks merged
into one cell (via `GeneratedEntry.session_group`), stacked cell content
(code / batch / initials+room) instead of a pipe-joined string, and
subject-code / faculty-initials legend tables.
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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from icalendar import Calendar, Event
from sqlalchemy.orm import Session

from app.models import (
    GeneratedEntry, Section, Subject, SubjectType, Teacher, Room, TimeSlot, LabBatch,
    AcademicYear, AcademicTerm, Department, TimetableRun,
)
from app.solver.calendar import DAY_ORDER

HEADER_FILL = "1E3A5F"
LUNCH_FILL = "F3F4F6"


def _minutes(value) -> int:
    if value is None:
        return 0
    if hasattr(value, "hour"):
        return value.hour * 60 + value.minute
    parts = str(value).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _fetch_reference_data(db: Session) -> dict:
    return {
        "subjects": {s.id: s for s in db.query(Subject).all()},
        "subject_type_colors": {st.id: st.colour_hex for st in db.query(SubjectType).all()},
        "teachers": {t.id: t for t in db.query(Teacher).all()},
        "rooms": {r.id: r for r in db.query(Room).all()},
        "sections": {s.id: s for s in db.query(Section).all()},
        "batches": {b.id: b for b in db.query(LabBatch).all()},
    }


def _entity_label(ref: dict, db: Session, entity_type: str, entity_id: str) -> str:
    if entity_type == "section":
        section = ref["sections"].get(entity_id)
        if not section:
            return entity_id
        year = db.query(AcademicYear).filter(AcademicYear.id == section.year_id).first()
        return f"{year.name} {section.name}" if year else section.name
    if entity_type == "teacher":
        teacher = ref["teachers"].get(entity_id)
        return teacher.name if teacher else entity_id
    room = ref["rooms"].get(entity_id)
    return room.name if room else entity_id


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

    ref = _fetch_reference_data(db)

    grid: Dict[tuple, List[GeneratedEntry]] = {}
    for e in entries:
        grid.setdefault((e.day, e.period), []).append(e)

    slot_lookup = {(s.day, s.period_index): s for s in slots}

    # Phase 2.5: a per-day lunch band, only meaningful for a single
    # section's own timetable (a teacher/room view spans sections that may
    # belong to different years with different lunch windows).
    lunch_by_day: Dict[str, tuple] = {}
    if entity_type == "section":
        section = ref["sections"].get(entity_id)
        year = db.query(AcademicYear).filter(AcademicYear.id == section.year_id).first() if section else None
        if year and year.lunch_windows:
            lunch_by_day = {
                day: (_minutes(window[0]), _minutes(window[1]))
                for day, window in year.lunch_windows.items()
                if window and len(window) == 2
            }

    return {
        "days": days, "periods": periods, "grid": grid, "slot_lookup": slot_lookup,
        "lunch_by_day": lunch_by_day, "entity_label": _entity_label(ref, db, entity_type, entity_id),
        **ref,
    }


def _is_lunch_cell(ctx: dict, day: str, period: int) -> bool:
    window = ctx["lunch_by_day"].get(day)
    if not window:
        return False
    slot = ctx["slot_lookup"].get((day, period))
    if not slot:
        return False
    slot_start, slot_end = _minutes(slot.start_time), _minutes(slot.end_time)
    lunch_start, lunch_end = window
    return slot_start < lunch_end and lunch_start < slot_end


def _cell_blocks(entries: List[GeneratedEntry], ctx: dict, entity_type: str) -> List[List[str]]:
    """One "block" of stacked lines per entry - parallel batches/electives
    at the same slot each get their own block, all inside the same cell
    (Phase 4.1), instead of one pipe-joined line per entry."""
    blocks = []
    for e in entries:
        subject = ctx["subjects"].get(e.subject_id)
        code = subject.code if subject and subject.code else (e.subject_id or "")
        lines = [code]
        if entity_type != "section":
            who = ctx["sections"].get(e.section_id)
            if who:
                lines.append(who.name)
            elif e.batch_id:
                batch = ctx["batches"].get(e.batch_id)
                lines.append(batch.batch_name if batch else e.batch_id)
        else:
            if e.batch_id:
                batch = ctx["batches"].get(e.batch_id)
                lines.append(batch.batch_name if batch else e.batch_id)
        detail_parts = []
        if entity_type != "teacher":
            teacher = ctx["teachers"].get(e.teacher_id)
            detail_parts.append(teacher.initials if teacher and teacher.initials else (e.teacher_id or ""))
        if entity_type != "room":
            room = ctx["rooms"].get(e.room_id)
            detail_parts.append(room.name if room else (e.room_id or ""))
        if detail_parts:
            lines.append(" · ".join(p for p in detail_parts if p))
        blocks.append(lines)
    return blocks


def _subject_type(entries: List[GeneratedEntry], ctx: dict) -> Optional[str]:
    if not entries:
        return None
    subject = ctx["subjects"].get(entries[0].subject_id)
    return subject.type if subject else None


def _session_group_signature(entries: List[GeneratedEntry]):
    """None when the cell is empty (nothing to merge); otherwise a value
    that's identical for two periods iff they belong to the exact same
    scheduled block(s) - used to vertically merge a multi-period session
    (e.g. a 2-hour lab) into one cell instead of printing it once per row."""
    if not entries:
        return None
    return tuple(sorted(e.session_group or f"__row_{e.id}" for e in entries))


def _day_row_spans(ctx: dict, day: str) -> List[tuple]:
    """(start_index, end_index) pairs, as 0-based positions into
    ctx["periods"], of consecutive periods that should be vertically
    merged into one cell for this day."""
    periods = ctx["periods"]
    spans = []
    i = 0
    while i < len(periods):
        entries = ctx["grid"].get((day, periods[i]), [])
        sig = _session_group_signature(entries)
        if sig is None:
            i += 1
            continue
        j = i
        while j + 1 < len(periods) and _session_group_signature(ctx["grid"].get((day, periods[j + 1]), [])) == sig:
            j += 1
        if j > i:
            spans.append((i, j))
        i = j + 1
    return spans


def _legend_data(ctx: dict, entries_seen: List[GeneratedEntry]):
    subject_ids = sorted({e.subject_id for e in entries_seen if e.subject_id})
    teacher_ids = sorted({e.teacher_id for e in entries_seen if e.teacher_id})
    subject_rows = []
    for sid in subject_ids:
        subject = ctx["subjects"].get(sid)
        subject_rows.append((subject.code if subject and subject.code else sid, subject.name if subject else sid))
    teacher_rows = []
    for tid in teacher_ids:
        teacher = ctx["teachers"].get(tid)
        teacher_rows.append((teacher.initials if teacher and teacher.initials else tid, teacher.name if teacher else tid))
    return subject_rows, teacher_rows


def _department_name(db: Session, run_id: int) -> str:
    run = db.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    if not run or not run.department_id:
        return ""
    department = db.query(Department).filter(Department.id == run.department_id).first()
    return department.name if department else ""


def export_xlsx(db: Session, run_id: int, rank: int, entity_type: str, entity_id: str, title: str) -> bytes:
    """Single-entity export (one section/teacher/room). For "every section
    in a year" see export_xlsx_year, which calls this once per section and
    combines the sheets into one workbook (Phase 4.2)."""
    wb = Workbook()
    ws = wb.active
    _write_xlsx_sheet(wb, ws, db, run_id, rank, entity_type, entity_id, title)
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _write_xlsx_sheet(wb: Workbook, ws, db: Session, run_id: int, rank: int, entity_type: str, entity_id: str, title: str) -> None:
    ctx = _gather_grid(db, run_id, rank, entity_type, entity_id)
    department_name = _department_name(db, run_id)
    ws.title = (ctx["entity_label"] or "Timetable")[:31] or "Timetable"

    header_lines = [l for l in [department_name, title, ctx["entity_label"]] if l]
    for i, line in enumerate(header_lines, start=1):
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=1 + len(ctx["days"]))
        cell = ws.cell(row=i, column=1, value=line)
        cell.font = Font(size=14 if i == 1 else 11, bold=(i != len(header_lines)), color="1E3A5F")
        cell.alignment = Alignment(horizontal="center")
        ws.row_dimensions[i].height = 22

    header_row = len(header_lines) + 2
    ws.cell(row=header_row, column=1, value="Period / Time").font = Font(bold=True, color="FFFFFF")
    ws.cell(row=header_row, column=1).fill = PatternFill("solid", fgColor=HEADER_FILL)
    for col, day in enumerate(ctx["days"], start=2):
        cell = ws.cell(row=header_row, column=col, value=day)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center")

    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    day_spans = {day: _day_row_spans(ctx, day) for day in ctx["days"]}
    span_start_for = {}  # (day, period_index) -> start_period_index, for rows covered by a vertical merge
    for day, spans in day_spans.items():
        for start, end in spans:
            for idx in range(start, end + 1):
                span_start_for[(day, idx)] = start

    row = header_row + 1
    grid_first_row = row
    entries_seen: List[GeneratedEntry] = []
    for period_idx, period in enumerate(ctx["periods"]):
        sample_slot = next((ctx["slot_lookup"].get((d, period)) for d in ctx["days"] if (d, period) in ctx["slot_lookup"]), None)
        label = f"Period {period}"
        if sample_slot:
            label += f"\n{sample_slot.start_time.strftime('%H:%M')}-{sample_slot.end_time.strftime('%H:%M')}"
        cell = ws.cell(row=row, column=1, value=label)
        cell.font = Font(bold=True)
        cell.border = border
        cell.alignment = Alignment(wrap_text=True, vertical="center")

        col = 2
        while col < 2 + len(ctx["days"]):
            day = ctx["days"][col - 2]
            entries = ctx["grid"].get((day, period), [])
            if not entries and _is_lunch_cell(ctx, day, period):
                span_start = col
                while (
                    col < 2 + len(ctx["days"])
                    and not ctx["grid"].get((ctx["days"][col - 2], period), [])
                    and _is_lunch_cell(ctx, ctx["days"][col - 2], period)
                ):
                    col += 1
                cell = ws.cell(row=row, column=span_start, value="Lunch")
                cell.border = border
                cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                cell.fill = PatternFill("solid", fgColor=LUNCH_FILL)
                cell.font = Font(italic=True, color="6B7280")
                if col - 1 > span_start:
                    ws.merge_cells(start_row=row, start_column=span_start, end_row=row, end_column=col - 1)
                    for c in range(span_start, col):
                        ws.cell(row=row, column=c).border = border
                continue

            covered_from = span_start_for.get((day, period_idx))
            if covered_from is not None and covered_from != period_idx:
                # Part of a vertical merge whose content already printed on
                # the span's first row - leave this cell blank, bordered.
                cell = ws.cell(row=row, column=col)
                cell.border = border
                col += 1
                continue

            entries_seen.extend(entries)
            blocks = _cell_blocks(entries, ctx, entity_type)
            text = "\n\n".join("\n".join(lines) for lines in blocks)
            cell = ws.cell(row=row, column=col, value=text)
            cell.border = border
            cell.alignment = Alignment(wrap_text=True, vertical="center")
            subject_type = _subject_type(entries, ctx)
            color = ctx["subject_type_colors"].get(subject_type) if subject_type else None
            if color:
                cell.fill = PatternFill("solid", fgColor=color)

            if covered_from == period_idx:
                span_end = next(end for (start, end) in day_spans[day] if start == period_idx)
                ws.merge_cells(start_row=row, start_column=col, end_row=row + (span_end - period_idx), end_column=col)
                for r in range(row, row + (span_end - period_idx) + 1):
                    ws.cell(row=r, column=col).border = border
            col += 1
        row += 1

    ws.column_dimensions["A"].width = 18
    for col in range(2, 2 + len(ctx["days"])):
        ws.column_dimensions[get_column_letter(col)].width = 26
    for r in range(grid_first_row, row):
        ws.row_dimensions[r].height = 48
    ws.freeze_panes = ws.cell(row=header_row + 1, column=2)

    # ---- legend tables ----
    subject_rows, teacher_rows = _legend_data(ctx, entries_seen)
    legend_row = row + 2
    if subject_rows:
        ws.cell(row=legend_row, column=1, value="Subject Code").font = Font(bold=True)
        ws.cell(row=legend_row, column=2, value="Subject Name").font = Font(bold=True)
        for i, (code, name) in enumerate(subject_rows, start=1):
            ws.cell(row=legend_row + i, column=1, value=code)
            ws.cell(row=legend_row + i, column=2, value=name)
    if teacher_rows:
        col_offset = 4
        ws.cell(row=legend_row, column=col_offset, value="Initials").font = Font(bold=True)
        ws.cell(row=legend_row, column=col_offset + 1, value="Faculty Name").font = Font(bold=True)
        for i, (initials, name) in enumerate(teacher_rows, start=1):
            ws.cell(row=legend_row + i, column=col_offset, value=initials)
            ws.cell(row=legend_row + i, column=col_offset + 1, value=name)

    sig_row = legend_row + max(len(subject_rows), len(teacher_rows)) + 3
    sig_col = 1 + len(ctx["days"])
    ws.cell(row=sig_row, column=sig_col, value="______________________")
    ws.cell(row=sig_row + 1, column=sig_col, value=f"Head, {department_name} Dept." if department_name else "Head of Department")


def export_xlsx_year(db: Session, run_id: int, rank: int, year_id: str, title: str) -> bytes:
    """One sheet per section in the year, in one workbook (Phase 4.2)."""
    sections = db.query(Section).filter(Section.year_id == year_id).order_by(Section.name).all()
    if not sections:
        raise ValueError("This year has no sections to export.")
    wb = Workbook()
    wb.remove(wb.active)
    for section in sections:
        ws = wb.create_sheet()
        _write_xlsx_sheet(wb, ws, db, run_id, rank, "section", section.id, title)
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


_PDF_STYLES = getSampleStyleSheet()


def _pdf_styles(scale: float) -> dict:
    """Cell/legend/spacer styling for a given shrink-to-fit scale (1.0 = full size)."""
    cell_font = 6.5 * scale
    time_font = 7 * scale
    legend_font = 7 * scale
    cell_style = ParagraphStyle("cell", parent=_PDF_STYLES["Normal"], fontSize=cell_font, leading=cell_font * 1.25, alignment=TA_CENTER)
    return {
        "cell": cell_style,
        "lunch": ParagraphStyle("lunch", parent=cell_style, fontName="Helvetica-Oblique", textColor=colors.HexColor("#6B7280")),
        "time": ParagraphStyle("time", parent=cell_style, fontSize=time_font, leading=time_font * 1.25, fontName="Helvetica-Bold"),
        "legend": ParagraphStyle("legend", parent=_PDF_STYLES["Normal"], fontSize=legend_font, leading=legend_font * 1.3),
        "cell_pad": max(1, round(2 * scale)),
        "spacer_top": max(2, 6 * scale),
        "spacer_mid": max(2, 10 * scale),
        "spacer_sig": max(4, 24 * scale),
    }


def _build_pdf_elements(ctx: dict, department_name: Optional[str], term: Optional["AcademicTerm"], usable_width: float, scale: float, entity_type: str) -> list:
    styles = _pdf_styles(scale)
    _CELL_STYLE, _LUNCH_STYLE, _TIME_STYLE = styles["cell"], styles["lunch"], styles["time"]

    elements = []
    if department_name:
        elements.append(Paragraph(f"Department of {department_name}", _PDF_STYLES["Title"]))
    if term:
        elements.append(Paragraph(f"Session: {term.name}", ParagraphStyle("session", parent=_PDF_STYLES["Normal"], alignment=TA_CENTER)))
    elements.append(Paragraph("Tentative Time Table", ParagraphStyle("subtitle", parent=_PDF_STYLES["Heading2"], alignment=TA_CENTER)))
    elements.append(Paragraph(ctx["entity_label"], ParagraphStyle("class", parent=_PDF_STYLES["Heading3"], alignment=TA_CENTER)))
    if term:
        elements.append(Paragraph(
            f"w.e.f. {term.start_date.strftime('%d/%m/%Y')}",
            ParagraphStyle("wef", parent=_PDF_STYLES["Normal"], alignment=TA_RIGHT),
        ))
    elements.append(Spacer(1, styles["spacer_top"]))

    header = [Paragraph("Time", _TIME_STYLE)] + [Paragraph(day, _TIME_STYLE) for day in ctx["days"]]
    data = [header]

    day_spans = {day: _day_row_spans(ctx, day) for day in ctx["days"]}
    span_start_for = {}
    for day, spans in day_spans.items():
        for start, end in spans:
            for idx in range(start, end + 1):
                span_start_for[(day, idx)] = start

    entries_seen: List[GeneratedEntry] = []
    for period_idx, period in enumerate(ctx["periods"]):
        sample_slot = next((ctx["slot_lookup"].get((d, period)) for d in ctx["days"] if (d, period) in ctx["slot_lookup"]), None)
        time_label = f"P{period}<br/>{sample_slot.start_time.strftime('%H:%M')}-{sample_slot.end_time.strftime('%H:%M')}" if sample_slot else f"P{period}"
        row = [Paragraph(time_label, _TIME_STYLE)]
        for day in ctx["days"]:
            entries = ctx["grid"].get((day, period), [])
            if not entries and _is_lunch_cell(ctx, day, period):
                row.append(Paragraph("Lunch", _LUNCH_STYLE))
                continue
            covered_from = span_start_for.get((day, period_idx))
            if covered_from is not None and covered_from != period_idx:
                row.append("")  # covered by a SPAN from an earlier row
                continue
            entries_seen.extend(entries)
            blocks = _cell_blocks(entries, ctx, entity_type)
            html = "<br/><br/>".join("<br/>".join(lines) for lines in blocks)
            row.append(Paragraph(html, _CELL_STYLE) if html else "")
        data.append(row)

    col_widths = [22 * mm] + [(usable_width - 22 * mm) / max(len(ctx["days"]), 1)] * len(ctx["days"])
    table = Table(data, repeatRows=1, colWidths=col_widths)
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), styles["cell_pad"]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), styles["cell_pad"]),
    ]
    for row_idx, period in enumerate(ctx["periods"], start=1):
        col_idx = 1
        while col_idx <= len(ctx["days"]):
            day = ctx["days"][col_idx - 1]
            entries = ctx["grid"].get((day, period), [])
            if not entries and _is_lunch_cell(ctx, day, period):
                span_start = col_idx
                while (
                    col_idx <= len(ctx["days"])
                    and not ctx["grid"].get((ctx["days"][col_idx - 1], period), [])
                    and _is_lunch_cell(ctx, ctx["days"][col_idx - 1], period)
                ):
                    col_idx += 1
                style_commands.append(("BACKGROUND", (span_start, row_idx), (col_idx - 1, row_idx), colors.HexColor(f"#{LUNCH_FILL}")))
                if col_idx - 1 > span_start:
                    style_commands.append(("SPAN", (span_start, row_idx), (col_idx - 1, row_idx)))
                continue

            period_idx = row_idx - 1
            covered_from = span_start_for.get((day, period_idx))
            if covered_from is not None:
                span_end = next(end for (start, end) in day_spans[day] if start == covered_from)
                if covered_from == period_idx and span_end > period_idx:
                    style_commands.append(("SPAN", (col_idx, row_idx), (col_idx, row_idx + (span_end - period_idx))))
                subject_type = _subject_type(ctx["grid"].get((day, ctx["periods"][covered_from]), []), ctx)
                color = ctx["subject_type_colors"].get(subject_type) if subject_type else None
                if color and covered_from == period_idx:
                    style_commands.append(("BACKGROUND", (col_idx, row_idx), (col_idx, row_idx + (span_end - period_idx)), colors.HexColor(f"#{color}")))
                col_idx += 1
                continue

            subject_type = _subject_type(entries, ctx)
            color = ctx["subject_type_colors"].get(subject_type) if subject_type else None
            if color:
                style_commands.append(("BACKGROUND", (col_idx, row_idx), (col_idx, row_idx), colors.HexColor(f"#{color}")))
            col_idx += 1
    table.setStyle(TableStyle(style_commands))
    elements.append(table)
    elements.append(Spacer(1, styles["spacer_mid"]))

    # ---- legend tables, side by side ----
    subject_rows, teacher_rows = _legend_data(ctx, entries_seen)
    legend_style = styles["legend"]
    if subject_rows:
        subj_data = [[Paragraph("<b>Subject Code</b>", legend_style), Paragraph("<b>Subject Name</b>", legend_style)]]
        subj_data += [[Paragraph(code, legend_style), Paragraph(name, legend_style)] for code, name in subject_rows]
        subj_table = Table(subj_data, colWidths=[usable_width * 0.12, usable_width * 0.33])
        subj_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    else:
        subj_table = Paragraph("", legend_style)

    if teacher_rows:
        teach_data = [[Paragraph("<b>Initials</b>", legend_style), Paragraph("<b>Faculty Name</b>", legend_style)]]
        teach_data += [[Paragraph(initials, legend_style), Paragraph(name, legend_style)] for initials, name in teacher_rows]
        teach_table = Table(teach_data, colWidths=[usable_width * 0.12, usable_width * 0.33])
        teach_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    else:
        teach_table = Paragraph("", legend_style)

    legend_row_table = Table([[subj_table, teach_table]], colWidths=[usable_width * 0.5, usable_width * 0.5])
    legend_row_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(legend_row_table)

    # ---- signature line, bottom right ----
    elements.append(Spacer(1, styles["spacer_sig"]))
    sig_style = ParagraphStyle("sig", parent=_PDF_STYLES["Normal"], alignment=TA_RIGHT, fontSize=max(6, 9 * scale))
    elements.append(Paragraph("______________________", sig_style))
    elements.append(Paragraph(f"Head, {department_name} Dept." if department_name else "Head of Department", sig_style))

    return elements


def _elements_height(elements: list, usable_width: float) -> float:
    total = 0.0
    for flowable in elements:
        _, h = flowable.wrap(usable_width, 0xFFFFFF)
        total += h
    return total


def export_pdf(
    db: Session, run_id: int, rank: int, entity_type: str, entity_id: str, title: str,
    term: Optional["AcademicTerm"] = None,
) -> bytes:
    """Renders the grid, subject/faculty legends, and signature line onto a single page.

    The table height varies with how many periods/days an institution configures,
    so we shrink fonts/padding/spacing in steps until everything fits one page
    rather than letting ReportLab overflow the legend onto a second page.
    """
    ctx = _gather_grid(db, run_id, rank, entity_type, entity_id)
    department_name = _department_name(db, run_id)
    page_width, page_height = landscape(A4)
    margin = 8 * mm
    usable_width = page_width - 2 * margin
    available_height = page_height - 2 * margin

    scale = 1.0
    elements = _build_pdf_elements(ctx, department_name, term, usable_width, scale, entity_type)
    while _elements_height(elements, usable_width) > available_height and scale > 0.55:
        scale = max(0.55, scale - 0.1)
        elements = _build_pdf_elements(ctx, department_name, term, usable_width, scale, entity_type)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=(page_width, page_height),
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin,
    )
    doc.build(elements)
    return buffer.getvalue()


def _build_ics_events(cal: Calendar, entries: List[GeneratedEntry], ctx: dict, term: Optional["AcademicTerm"], weeks: int, run_id: int):
    range_start = term.start_date if term else date_cls.today()
    weekday_index = {day: idx for idx, day in enumerate(DAY_ORDER[:7])}
    grid: Dict[tuple, List[GeneratedEntry]] = {}
    for e in entries:
        grid.setdefault((e.day, e.period), []).append(e)

    for (day, period), day_entries in grid.items():
        slot = ctx["slot_lookup"].get((day, period))
        if not slot or day not in weekday_index:
            continue
        days_ahead = (weekday_index[day] - range_start.weekday()) % 7
        first_date = range_start + timedelta(days=days_ahead)
        start_dt = datetime.combine(first_date, slot.start_time)
        end_dt = datetime.combine(first_date, slot.end_time)
        rrule = {"freq": "weekly", "until": datetime.combine(term.end_date, slot.end_time)} if term else {"freq": "weekly", "count": weeks}

        for entry in day_entries:
            event = Event()
            subject = ctx["subjects"].get(entry.subject_id)
            event.add("summary", subject.name if subject else entry.subject_id)
            event.add("dtstart", start_dt)
            event.add("dtend", end_dt)
            event.add("rrule", rrule)
            teacher = ctx["teachers"].get(entry.teacher_id)
            room = ctx["rooms"].get(entry.room_id)
            if room:
                event.add("location", room.name)
            if teacher:
                event.add("description", f"Teacher: {teacher.name}")
            event.add("uid", f"{run_id}-{entry.id}@timetable-generator")
            cal.add_component(event)


def export_ics(
    db: Session, run_id: int, rank: int, entity_type: str, entity_id: str,
    weeks: int = 15, term: Optional["AcademicTerm"] = None,
) -> bytes:
    """Weekly-recurring calendar events for one run. When the run is linked
    to an AcademicTerm (Phase 1.7), events start on the term's first
    matching weekday and recur until its end_date - the real semester, not
    a guessed weeks count. Without a term, falls back to the previous
    behaviour: start from the next occurrence of each weekday and recur
    for a fixed `weeks` count."""
    ctx = _gather_grid(db, run_id, rank, entity_type, entity_id)
    entries = [e for cell in ctx["grid"].values() for e in cell]
    cal = Calendar()
    cal.add("prodid", "-//Timetable Generator//EN")
    cal.add("version", "2.0")
    _build_ics_events(cal, entries, ctx, term, weeks, run_id)
    return cal.to_ical()


def export_ics_from_entries(
    db: Session, entries: List[GeneratedEntry], entity_type: str,
    weeks: int = 15, term: Optional["AcademicTerm"] = None,
) -> bytes:
    """Phase 4.3: the student/faculty "My Timetable" calendar feed - built
    directly from an arbitrary (already-filtered-to-one-person) entry list
    that may span several published runs, rather than one run+entity like
    the admin export above."""
    ref = _fetch_reference_data(db)
    slots = db.query(TimeSlot).all()
    ctx = {**ref, "slot_lookup": {(s.day, s.period_index): s for s in slots}}
    cal = Calendar()
    cal.add("prodid", "-//Timetable Generator//EN")
    cal.add("version", "2.0")
    _build_ics_events(cal, entries, ctx, term, weeks, run_id=0)
    return cal.to_ical()
