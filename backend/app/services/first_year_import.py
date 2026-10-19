"""First-year central timetable import: OCR geometry -> preview -> hard locks.

The central office allots the first-year timetable, so our solver never sees
those classes - but some of them are taught by OUR teachers and held in OUR
rooms. This module reads the scanned PDF (via the PaddleOCR worker in
app/ocr) and works out which (teacher|room, day, period) the solver must
treat as already booked. Everything here is plain logic over the worker's JSON
so it can be unit-tested without any OCR installed.

Why geometry and not the OCR's table HTML: PP-StructureV3's cell BOXES are
accurate on these bordered, merged-cell grids, but its HTML scrambles merged
cells. So we take the boxes plus the OCR text lines and derive each cell's day
(x position under the day header) and hours (y overlap with the time labels)
ourselves.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

DAYS = {"monday": "Mon", "tuesday": "Tue", "wednesday": "Wed",
        "thursday": "Thu", "friday": "Fri", "saturday": "Sat"}
TIME_RE = re.compile(r"(\d{1,2})[:.]?(\d{2})\s*[-–]\s*(\d{1,2})[:.]?(\d{2})")
# Subject codes look like CO34_CN / CO_IoT / HUM3401. The OCR often drops the
# underscore (CO34IS), so it is optional.
SUBJECT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])CO\d{0,2}[_\s]*[A-Za-z]{2,}(?![A-Za-z])|(?<![A-Za-z0-9])HUM\d+")
SECTION_RE = re.compile(r"(?i)B\.?\s*Tech\.?\s*([IVX]+)\s*([A-Z])(?![A-Za-z])")
BATCH_RE = re.compile(r"[ABab]\d")
# Symbols the OCR emits when it half-reads a letter ("\T$" for "VT").
DAMAGE_CHARS = set("\\$|{}~^`_[]")
# A cell needs this fraction of a time band to count as occupying it: scan
# skew and sliver boxes move cell edges by a few pixels.
BAND_OVERLAP = 0.4


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def normalize_code(raw: str) -> str:
    """Faculty codes carry marker characters in the PDF (ANS", PM', SR") that
    are not part of the code; drop everything but letters."""
    return re.sub(r"[^A-Za-z]", "", raw or "").upper()


def normalize_subject(raw: str) -> str:
    """CO34_OS, whatever the OCR did to the underscore: "CO34OS", "CO34 OS",
    "CO34__OS" all become "CO34_OS"; "CO_IoT" keeps its shape."""
    text = re.sub(r"[_\s]+", "_", raw.strip()).upper()
    match = re.fullmatch(r"(CO\d{0,2})_?([A-Z]{2,})", text)
    return f"{match.group(1)}_{match.group(2)}" if match else text


def _to_24h(hour: int) -> int:
    return hour + 12 if hour < 8 else hour  # the timetable runs 08:00-18:00


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# --------------------------------------------------------------------------
# geometry -> cells
# --------------------------------------------------------------------------
@dataclass
class RawCell:
    page: int
    section: str
    day: str
    start: str  # "HH:MM"
    end: str
    subject: str
    lines: List[str]

    @property
    def text(self) -> str:
        return " ".join(self.lines)


@dataclass
class PageResult:
    page: int
    section: str
    cells: List[RawCell] = field(default_factory=list)
    legend: Dict[str, str] = field(default_factory=dict)  # code -> full name
    warnings: List[str] = field(default_factory=list)


def _union(a: List[float], b: List[float]) -> List[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _merge_slivers(cells: List[List[float]], pitch: float) -> List[List[float]]:
    """The detector sometimes cuts one cell into a thin sliver plus a body;
    glue slivers to the box they touch in the same column so a cell's hours
    are not cut short."""
    cells = [list(c) for c in cells]
    changed = True
    while changed:
        changed = False
        for a in cells:
            if a[3] - a[1] >= 0.6 * pitch:
                continue
            for b in cells:
                if b is a:
                    continue
                overlap = min(a[2], b[2]) - max(a[0], b[0])
                touching = abs(a[3] - b[1]) < 10 or abs(b[3] - a[1]) < 10
                if overlap > 0.8 * min(a[2] - a[0], b[2] - b[0]) and touching:
                    b[:] = _union(a, b)
                    cells.remove(a)
                    changed = True
                    break
            if changed:
                break
    return cells


def _glue_continuations(cells: List[List[float]], text_of) -> List[List[float]]:
    """A box with text but no subject is the lower half of a cell the
    detector cut in two (subject line above, faculty/room below): merge it
    into the subject-bearing box directly above it."""
    cells = [list(c) for c in cells]
    for c in list(cells):
        body = text_of(c)
        if not body or SUBJECT_RE.search(body) or "LUNCH" in body.upper():
            continue
        for a in cells:
            if a is c or not SUBJECT_RE.search(text_of(a)):
                continue
            overlap = min(a[2], c[2]) - max(a[0], c[0])
            if overlap > 0.7 * min(a[2] - a[0], c[2] - c[0]) and abs(a[3] - c[1]) < 12:
                a[:] = _union(a, c)
                cells.remove(c)
                break
    return cells


def parse_section(texts: Sequence[str]) -> Optional[str]:
    match = SECTION_RE.search(" ".join(texts))
    return f"{match.group(1).upper()}-{match.group(2).upper()}" if match else None


def parse_legend(lines: Sequence[Tuple[float, float, str]], below_y: float) -> Dict[str, str]:
    """The faculty list under the grid: `CODE  Full Name` pairs. Each name is
    paired with the nearest short code to its left on the same printed row
    (scan skew means rows cannot be found by binning y)."""
    below = [(x, y, t.strip()) for x, y, t in lines if y > below_y]
    codes = [(x, y, t) for x, y, t in below
             if re.fullmatch(r"[A-Za-z]{1,4}[\"'″’*]*", t)]
    legend: Dict[str, str] = {}
    for x, y, text in below:
        if " " not in text:
            continue
        left = [(x - cx, code) for cx, cy, code in codes if cx < x and abs(cy - y) <= 10]
        if left:
            _, code = min(left)
            clean = normalize_code(code)
            if clean and clean not in legend:
                legend[clean] = text
    return legend


def extract_page(page: dict, fallback_section: str) -> PageResult:
    """One OCR worker page -> day/time/text cells."""
    texts: List[str] = page["texts"]
    boxes = page["boxes"]
    lines = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, t) for t, b in zip(texts, boxes)]
    section = parse_section(texts) or fallback_section
    result = PageResult(page=page["page"], section=section)
    cells = [[float(v) for v in c] for c in page["cells"]]

    heads = [(x, y, DAYS[re.sub(r"[^a-z]", "", t.lower())]) for x, y, t in lines
             if re.sub(r"[^a-z]", "", t.lower()) in DAYS]
    times = sorted((y, _to_24h(int(m.group(1)))) for _, y, t in lines for m in [TIME_RE.search(t)] if m)
    if not heads or len(times) < 2:
        result.warnings.append("Timetable grid not recognised (no day headers / time labels found).")
        return result

    day_ranges: Dict[str, Tuple[float, float]] = {}
    for x, y, day in heads:
        containing = [c for c in cells if c[0] <= x <= c[2] and c[1] <= y <= c[3]]
        if containing:
            box = min(containing, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
            day_ranges[day] = (box[0], box[2])
    if len(day_ranges) < 4:
        result.warnings.append("Could not locate the day columns on this page.")
        return result

    ys = [t[0] for t in times]
    pitch = (ys[-1] - ys[0]) / (len(ys) - 1)
    table_bottom = ys[-1] + pitch / 2 + 4
    head_y = max(y for _, y, _ in heads)
    first_x = min(r[0] for r in day_ranges.values())
    result.legend = parse_legend(lines, table_bottom)

    # one horizontal band per time label, cut half-way between labels; the
    # lunch band is dropped because nothing is ever scheduled in it
    lunch_ys = [y for _, y, t in lines if "LUNCH" in t.upper()]
    bands: Dict[int, Tuple[float, float]] = {}
    for k, (label_y, hour) in enumerate(times):
        low = (times[k - 1][0] + label_y) / 2 if k else label_y - pitch / 2
        high = (label_y + times[k + 1][0]) / 2 if k + 1 < len(times) else label_y + pitch / 2
        if not any(low <= y <= high for y in lunch_ys):
            bands[hour] = (low, high)

    def text_lines(box: List[float]) -> List[str]:
        inside = sorted((y, x, t) for x, y, t in lines if box[0] <= x <= box[2] and box[1] <= y <= box[3])
        return [t for _, _, t in inside]

    def text_of(box: List[float]) -> str:
        return " ".join(text_lines(box))

    in_table = [c for c in cells if (c[1] + c[3]) / 2 <= table_bottom]
    in_table = _merge_slivers(in_table, pitch)
    in_table = _glue_continuations(in_table, text_of)

    for box in in_table:
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if cy < head_y + 10 or cx < first_x:
            continue
        day = next((d for d, (x0, x1) in day_ranges.items() if x0 <= cx <= x1), None)
        if day is None:
            continue
        body_lines = text_lines(box)
        body = " ".join(body_lines)
        subject_match = SUBJECT_RE.search(body)
        if not subject_match or "LUNCH" in body.upper():
            continue  # header cells and empty cells carry no subject
        hours = [h for h, (low, high) in bands.items()
                 if min(box[3], high) - max(box[1], low) >= BAND_OVERLAP * (high - low)]
        if not hours:
            continue
        result.cells.append(RawCell(
            page=page["page"], section=section, day=day,
            start=f"{min(hours):02d}:00", end=f"{max(hours) + 1:02d}:00",
            subject=normalize_subject(subject_match.group(0)), lines=body_lines,
        ))
    if not result.cells:
        result.warnings.append("No timetable cells were read from this page.")
    return result


# --------------------------------------------------------------------------
# cell text -> teachers / room
# --------------------------------------------------------------------------
@dataclass
class ParsedCell:
    codes: List[str]       # clean alphabetic tokens that may be faculty codes
    damaged: List[str]     # tokens the OCR half-read ("\T$", "A_$")
    room_text: str
    batches: List[str] = field(default_factory=list)  # lab batch tags printed on the cell ("A1", "A2")
    # Every faculty code printed on the class, in order - ours, other
    # departments', and ones the page legend mis-spells - for the tile.
    printed: List[str] = field(default_factory=list)


def _tokens(line: str) -> List[str]:
    return [t for t in re.split(r"[\s,\"'*″’]+", line) if t]


def _comma_listed(line: str) -> List[str]:
    """Letter-only tokens that sit in a comma-separated list ("RKD, AS,") or
    carry the guest-faculty quote marker (ANS", PM'). The OCR sometimes loses
    the comma, so the marker counts on its own. A room name on the same line
    ("... AVLC") has neither, which is how a faculty list is told apart from a
    trailing room."""
    found = []
    for match in re.finditer(r"[A-Za-z]+", line):
        before = line[:match.start()].rstrip("\"'*″’ ")
        after = line[match.end():].lstrip("\"'*″’")
        marked = line[match.end():match.end() + 1] in ("\"", "'", "″", "’")  # guest-faculty marker
        if before.endswith(",") or after.startswith(",") or marked:
            found.append(match.group(0).upper())
    return found


def parse_cell_text(lines: Sequence[str], recognised: Set[str]) -> ParsedCell:
    """Split a cell's OCR lines into faculty codes and the room.

    The PDF prints: subject, batch tags, faculty codes (may wrap over lines),
    then the room last - sometimes on the same line as the last codes.
    `recognised` is every code we know is a faculty code (our initials plus the
    page's faculty legend); the room is what follows the last such line.
    """
    codes: List[str] = []
    damaged: List[str] = []
    batches: List[str] = []
    printed: List[str] = []
    last_code_line = -1
    subject_line = -1
    per_line: List[List[str]] = [_tokens(line) for line in lines]
    for index, line in enumerate(lines):
        if subject_line < 0 and SUBJECT_RE.search(line):
            subject_line = last_code_line = index
            batches += [re.sub(r"[^A-Za-z0-9]", "", t).upper() for t in per_line[index]
                        if BATCH_RE.fullmatch(re.sub(r"[^A-Za-z0-9]", "", t))]
            continue  # everything on the subject line is subject/batch text
        for token in per_line[index]:
            stripped = re.sub(r"[^A-Za-z0-9]", "", token)
            if not stripped:
                continue
            if BATCH_RE.fullmatch(stripped):
                batches.append(stripped.upper())
                last_code_line = max(last_code_line, index)
                continue
            # stray symbols hugging the ends ("RV$", "{NS") are scan noise
            # around an otherwise readable code; symbols inside are damage
            original = token
            token = token.strip("".join(DAMAGE_CHARS))
            if not token:
                continue
            clean = normalize_code(token)
            inner_damage = any(c in DAMAGE_CHARS for c in token)
            listed = clean in _comma_listed(line)
            if listed and not inner_damage and clean == stripped.upper() and len(clean) <= 5:
                printed.append(clean)
            if not inner_damage and clean == stripped.upper() and clean in recognised:
                codes.append(clean)
                if clean not in printed:
                    printed.append(clean)
                last_code_line = max(last_code_line, index)
            elif clean and (inner_damage or (token != original and len(clean) <= 2)):
                # half-read: either symbols inside the token, or a short
                # fragment left once the edge noise is removed ("A_$" -> "A")
                damaged.append(original)
                last_code_line = max(last_code_line, index)

    room_text = " ".join(" ".join(t) for t in per_line[last_code_line + 1:]).strip()
    if not room_text and last_code_line > subject_line >= 0 or (not room_text and last_code_line > 0 and subject_line < 0):
        # room printed on the same line as the last codes ("DAM, NM,AS AVLC")
        leftover = [t for t in per_line[last_code_line]
                    if normalize_code(t) not in recognised
                    and not BATCH_RE.fullmatch(re.sub(r"[^A-Za-z0-9]", "", t))
                    and not any(c in DAMAGE_CHARS for c in t)]
        room_text = " ".join(leftover).strip()
    return ParsedCell(codes=codes, damaged=damaged, room_text=room_text.strip(" ,."),
                      batches=list(dict.fromkeys(batches)), printed=list(dict.fromkeys(printed)))


# --------------------------------------------------------------------------
# matching against our data
# --------------------------------------------------------------------------
@dataclass
class TeacherRef:
    id: str
    name: str
    initials: str


@dataclass
class RoomRef:
    id: str
    name: str


@dataclass
class SlotRef:
    day: str
    period_index: int
    start: time
    end: time


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def slots_for_span(slots: Iterable[SlotRef], day: str, start: str, end: str) -> List[SlotRef]:
    """Our bell-schedule periods the cell's clock span occupies. A period
    counts once a quarter of it lies inside the span: the central timetable's
    hours need not line up with our bells, and locking a slot too many costs
    little while locking one too few double-books a teacher."""
    s_min = int(start[:2]) * 60 + int(start[3:])
    e_min = int(end[:2]) * 60 + int(end[3:])
    hit = []
    for slot in slots:
        if slot.day != day:
            continue
        length = _minutes(slot.end) - _minutes(slot.start)
        overlap = min(e_min, _minutes(slot.end)) - max(s_min, _minutes(slot.start))
        if length > 0 and overlap >= 0.25 * length:
            hit.append(slot)
    return sorted(hit, key=lambda s: s.period_index)


@dataclass
class Candidate:
    teacher_id: str
    name: str
    initials: str


@dataclass
class TeacherHit:
    code: str
    status: str  # matched | ambiguous | unread
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None
    candidates: List[Candidate] = field(default_factory=list)


@dataclass
class PreviewRowData:
    id: str
    page: int
    section: str
    day: str
    start: str
    end: str
    periods: List[Tuple[str, int]]
    subject: str
    cell_text: str
    teachers: List[TeacherHit]
    room_text: str
    room_id: Optional[str]
    room_name: Optional[str]
    # The class as printed, for the by-teacher / by-room tile: every faculty
    # code on it (not only ours) with the page legend's full name, and batches.
    faculty: List[Tuple[str, Optional[str]]] = field(default_factory=list)
    batches: List[str] = field(default_factory=list)


@dataclass
class Preview:
    pages: List[PageResult]
    rows: List[PreviewRowData]
    unmatched_codes: List[Tuple[str, int, Optional[str]]]  # code, occurrences, legend name
    # Cells whose faculty text the OCR could not read and that resemble none of
    # our teachers - listed so the admin checks them on the PDF rather than
    # having a possible clash silently skipped.
    unreadable: List[Dict[str, str]]
    warnings: List[str]


def _index_teachers(teachers: Sequence[TeacherRef]) -> Dict[str, List[TeacherRef]]:
    index: Dict[str, List[TeacherRef]] = {}
    for teacher in teachers:
        code = normalize_code(teacher.initials)
        if code:
            index.setdefault(code, []).append(teacher)
    return index


def _resolve_code(code: str, index: Dict[str, List[TeacherRef]], legend: Dict[str, str]) -> Optional[TeacherHit]:
    owners = index.get(code)
    if not owners:
        return None
    if len(owners) == 1:
        return TeacherHit(code, "matched", owners[0].id, owners[0].name)
    # Initials shared by several of our teachers: the page's legend spells the
    # person out, use it to break the tie.
    legend_name = normalize_name(legend.get(code, ""))
    if legend_name:
        named = [t for t in owners if normalize_name(t.name).endswith(legend_name[-8:]) or legend_name in normalize_name(t.name)
                 or normalize_name(t.name) in legend_name]
        if len(named) == 1:
            return TeacherHit(code, "matched", named[0].id, named[0].name)
    return TeacherHit(code, "ambiguous", candidates=[Candidate(t.id, t.name, t.initials) for t in owners])


def _unread_candidates(token: str, index: Dict[str, List[TeacherRef]]) -> List[Candidate]:
    """A half-read token ("A_$") might be one of our codes missing a letter or
    carrying a wrong one; list the ones within one edit so the admin can say."""
    clean = normalize_code(token)
    if not clean:
        return []
    found = []
    for code, owners in index.items():
        if _edit_distance(clean, code) <= 1 and abs(len(clean) - len(code)) <= 1:
            found.extend(Candidate(t.id, t.name, t.initials) for t in owners)
    return found


def build_preview(
    pages: Sequence[dict],
    teachers: Sequence[TeacherRef],
    rooms: Sequence[RoomRef],
    slots: Sequence[SlotRef],
) -> Preview:
    index = _index_teachers(teachers)
    room_by_name = {normalize_name(r.name): r for r in rooms if normalize_name(r.name)}
    results: List[PageResult] = []
    rows: List[PreviewRowData] = []
    unmatched: Dict[str, List] = {}  # code -> [count, legend name]
    unreadable: List[Dict[str, str]] = []
    warnings: List[str] = []

    for position, page in enumerate(pages, start=1):
        result = extract_page(page, fallback_section=f"Page {position}")
        results.append(result)
        for warning in result.warnings:
            warnings.append(f"Page {result.page} ({result.section}): {warning}")
        recognised = set(index) | set(result.legend)
        for number, cell in enumerate(result.cells):
            parsed = parse_cell_text(cell.lines, recognised)
            hits: List[TeacherHit] = []
            seen: Set[str] = set()
            for code in parsed.codes:
                if code in seen:
                    continue
                seen.add(code)
                hit = _resolve_code(code, index, result.legend)
                if hit:
                    hits.append(hit)
                else:
                    entry = unmatched.setdefault(code, [0, result.legend.get(code)])
                    entry[0] += 1
            for token in parsed.damaged:
                candidates = _unread_candidates(token, index)
                if candidates:
                    hits.append(TeacherHit(token, "unread", candidates=candidates))
                else:
                    unreadable.append({
                        "page": str(result.page), "section": result.section, "day": cell.day,
                        "start": cell.start, "end": cell.end, "subject": cell.subject, "text": token,
                    })

            room = room_by_name.get(normalize_name(parsed.room_text))
            if not hits and not room:
                continue  # nothing of ours in this class
            periods = [(s.day, s.period_index) for s in slots_for_span(slots, cell.day, cell.start, cell.end)]
            if not periods:
                warnings.append(
                    f"Page {result.page} ({result.section}): {cell.subject} on {cell.day} "
                    f"{cell.start}-{cell.end} matches none of the configured time slots.")
                continue
            rows.append(PreviewRowData(
                id=f"{result.page}-{number}", page=result.page, section=result.section, day=cell.day,
                start=cell.start, end=cell.end, periods=periods, subject=cell.subject, cell_text=cell.text,
                teachers=hits, room_text=parsed.room_text,
                room_id=room.id if room else None, room_name=room.name if room else None,
                faculty=[(code, result.legend.get(code)) for code in parsed.printed],
                batches=parsed.batches,
            ))
    ordered = sorted(unmatched.items(), key=lambda kv: -kv[1][0])
    return Preview(
        pages=results, rows=rows,
        unmatched_codes=[(code, count, name) for code, (count, name) in ordered],
        unreadable=unreadable, warnings=warnings,
    )
