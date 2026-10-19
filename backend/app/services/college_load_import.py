"""Adapter for the department "teaching load" workbook a college's timetable
admin already maintains (e.g. 01_Load_july2026.xlsx) - a human-formatted
file with merged title rows, one sheet per revision of the subject/faculty
allotment, and teachers referred to only by initials with hours, like
"HM(6), KM(6)".

Rather than teaching the rest of the import pipeline a second format, this
module converts such a workbook into the app's own bulk-import sheets
(AcademicYears, Sections, Subjects, Teachers, ...). The converted workbook
then goes through exactly the same validation and upsert as a hand-filled
template, so the two formats can never drift apart.

What it reads:
  * faculty list sheet   - "Name" column + the initials column next to it.
  * latest allotment     - the newest "subject_facult..." sheet (by the
    dates in its header or title). Older revisions stay in the workbook
    for the admin's records but are ignored, so a subject that was moved
    to another teacher later isn't imported twice.
  * every "Name" column  - only to resolve initials the faculty list
    doesn't spell the same way (e.g. "SwM" for Swati Mishra).

What it does NOT read (not present in this format): rooms, time slots,
teacher availability, section strengths. Those are added separately.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from openpyxl import Workbook

from app.services.department_load_sheets import (
    CREDITS,
    ELECTIVE_WORD,
    DepartmentLoadSheets,
    LoadEntry,
    is_department_load_workbook,
    read_department_load,
)

ALLOTMENT_SHEET_PATTERN = re.compile(r"subject_?facult", re.IGNORECASE)
DATE_IN_CELL = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")
DATE_IN_TITLE = re.compile(r"(\d{1,2})\s*([A-Za-z]{3,9})\s*(\d{2,4})")
# "HM(6)", "KaM(1)", "McH(3+3)", "CO71222(02)" - an initials token with the
# hours allotted to that teacher in parentheses.
ALLOTMENT_ITEM = re.compile(r"([A-Za-z]+)\s*\(\s*(\d+)\s*(?:\+\s*(\d+))?\s*\)")
PATTERN_PART = re.compile(r"(\d*)\s*(Tut|L|P)", re.IGNORECASE)
COURSE_CODE = re.compile(r"([A-Z]{2})\s*(\d{5})")
ELECTIVE_NAME = re.compile(r"\b(?:Elective|E)\s*[-–:]?\s*(IV|III|II|I)\b")
ROMAN_NUMERALS = {"I", "II", "III", "IV", "V", "VI"}
TITLE_WORDS = {"dr", "prof", "shri", "smt", "mr", "mrs", "ms", "miss"}

# One practical credit ("1P") is a 2-period lab per batch per week in this
# format - the college's own load sheet counts "1P" as 2 periods x batches.
PERIODS_PER_PRACTICAL_CREDIT = 2
# The workbook never states how many lab batches a class splits into.
# These are the defaults the department's load sheet uses; the admin
# adjusts per section afterwards if a class differs.
DEFAULT_BATCHES_LETTERED_SECTION = 3
DEFAULT_BATCHES_OTHER_SECTION = 1
DEFAULT_SECTION_STRENGTH = 60
# Periods a week an NPTEL elective is given as self-study when nothing says.
DEFAULT_NPTEL_HOURS = 3


class CollegeLoadFormatError(ValueError):
    pass


@dataclass
class _Row:
    section_label: str
    code_raw: str
    name: str
    pattern: str
    theory: List[Tuple[str, int]]
    tutorial: List[Tuple[str, int]]
    lab: List[Tuple[str, int]]
    row_number: int
    # Set by the six-sheet route, where the Load Calculation states each
    # component's periods outright instead of leaving them to be read off
    # the teachers' hours.
    hours: Dict[str, int] = field(default_factory=dict)
    secondary_tutorial: List[Tuple[str, int]] = field(default_factory=list)
    secondary_lab: List[Tuple[str, int]] = field(default_factory=list)
    faculty: Dict[str, int] = field(default_factory=dict)      # teachers at once, per tutorial/lab
    expected: Dict[str, int] = field(default_factory=dict)     # periods x batches x faculty, per kind
    batches: Optional[int] = None
    enrolled: Optional[int] = None
    class_enrolled: Optional[int] = None
    nptel: bool = False


@dataclass
class ConversionResult:
    workbook: Workbook
    source_sheet: str
    warnings: List[str] = field(default_factory=list)
    # Values the converter had to invent because the workbook doesn't say
    # (a default section size, a teacher it couldn't identify, a subject
    # nobody is allotted to yet). On a re-import these must never overwrite
    # what an admin has since corrected by hand, so the import drops them
    # for records that already exist: {sheet: {record id: {field, ...}}}.
    soft_fields: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)
    # Sections whose lab batches were only a default split, not read from
    # student numbers - an existing section keeps the batches it has.
    soft_batch_sections: Set[str] = field(default_factory=set)


# ---------------------------------------------------------------- detection

def is_college_load_workbook(workbook: Any, canonical_sheet_names: Iterable[str]) -> bool:
    """A workbook that already has any of the app's own sheets is always
    read as the app's format - this adapter only kicks in for a workbook
    that has none of them but does have an allotment sheet."""
    if set(workbook.sheetnames) & set(canonical_sheet_names):
        return False
    return is_department_load_workbook(workbook) or any(
        ALLOTMENT_SHEET_PATTERN.search(name) for name in workbook.sheetnames
    )


# ------------------------------------------------------------ small helpers

def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def _slug(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _sheet_rows(workbook: Any, name: str) -> List[Tuple[Any, ...]]:
    return list(workbook[name].iter_rows(values_only=True))


def _parse_cell_date(text: str) -> Optional[date]:
    match = DATE_IN_CELL.search(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_title_date(title: str) -> Optional[date]:
    match = DATE_IN_TITLE.search(title)
    if not match:
        return None
    day, month_text, year_text = match.groups()
    year = int(year_text) + (2000 if len(year_text) == 2 else 0)
    for fmt in ("%b", "%B"):
        try:
            month = datetime.strptime(month_text[:3] if fmt == "%b" else month_text, fmt).month
            return date(year, month, int(day))
        except ValueError:
            continue
    return None


def _name_words(name: str) -> List[str]:
    words = re.sub(r"[^A-Za-z ]+", " ", name).split()
    return [w for w in words if w.lower() not in TITLE_WORDS]


def _normalise_name(name: str) -> str:
    return " ".join(w.lower() for w in _name_words(name))


def _is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def _parse_allotment(value: Any) -> List[Tuple[str, int]]:
    items = []
    for match in ALLOTMENT_ITEM.finditer(_text(value)):
        initials, first, second = match.groups()
        items.append((initials, int(first) + int(second or 0)))
    return items


def _parse_pattern(pattern: str) -> Dict[str, int]:
    """"3L+1Tut." -> {L: 3, Tut: 1}; a part with no number counts once, so
    "Tut.+P" is one tutorial and one practical credit."""
    counts = {"L": 0, "Tut": 0, "P": 0}
    for number, kind in PATTERN_PART.findall(pattern):
        key = "Tut" if kind.lower() == "tut" else kind.upper()
        counts[key] += int(number) if number else 1
    return counts


def _split_name_and_pattern(name: str) -> Tuple[str, str]:
    """Re-registration rows carry their L/T/P pattern inside the name, e.g.
    "Computer Networks(3L + P)"."""
    match = re.search(r"\(([^()]*(?:\d\s*L|Tut|\d\s*P|\bP\b)[^()]*)\)\s*$", name)
    if not match:
        return name.strip(), ""
    return name[: match.start()].strip(" -"), match.group(1)


def _acronym(name: str) -> str:
    tail = name.split(":", 1)[-1]
    words = [w for w in re.sub(r"[^A-Za-z ]+", " ", tail).split() if w.lower() not in {"and", "of", "the", "nptel"}]
    return "".join(w[0].upper() for w in words)[:8] or _slug(name)[:8]


def _component_name(name: str, kind: str, component_count: int) -> str:
    if component_count == 1:
        return name
    if kind == "lab":
        return name if name.lower().endswith("lab") else f"{name} Lab"
    return f"{name} ({kind.title()})"


# --------------------------------------------------------- sheet selection

def _allotment_header(rows: Sequence[Tuple[Any, ...]]) -> Optional[Tuple[int, Dict[str, int]]]:
    """Returns (header row index, column index by role) for the class-wise
    allotment table - the one with Class/Year, Subject Code and Theory/
    Tutorial/Lab columns."""
    for index, row in enumerate(rows[:15]):
        cells = [_text(value).lower() for value in row]
        columns: Dict[str, int] = {}
        for col, cell in enumerate(cells):
            if cell.startswith("class") and "section" not in columns:
                columns["section"] = col
            elif cell == "subject code" and "code" not in columns:
                columns["code"] = col
            elif cell.startswith("subject nomenclature") and "name" not in columns:
                columns["name"] = col
            elif cell == "theory" and "theory" not in columns:
                columns["theory"] = col
            elif cell.startswith("tutorial") and "tutorial" not in columns:
                columns["tutorial"] = col
            elif cell == "lab" and "lab" not in columns:
                columns["lab"] = col
        if {"section", "code", "name", "theory"} <= set(columns):
            columns.setdefault("pattern", columns["name"] + 1)
            columns.setdefault("serial", 0)
            return index, columns
    return None


def _latest_allotment_sheet(workbook: Any) -> Tuple[str, Optional[date]]:
    candidates = []
    for order, name in enumerate(workbook.sheetnames):
        if not ALLOTMENT_SHEET_PATTERN.search(name):
            continue
        rows = _sheet_rows(workbook, name)
        if _allotment_header(rows) is None:
            continue
        dates = [d for d in (_parse_cell_date(_text(v)) for row in rows[:6] for v in row if v) if d]
        title_date = _parse_title_date(name)
        if title_date:
            dates.append(title_date)
        candidates.append((max(dates) if dates else date.min, order, name))
    if not candidates:
        raise CollegeLoadFormatError(
            "No subject/faculty allotment sheet with Class/Year, Subject Code and Theory columns was found"
        )
    latest_date, _, name = max(candidates)
    return name, (latest_date if latest_date != date.min else None)


# ------------------------------------------------------------- reading rows

def _read_allotment_rows(workbook: Any, sheet_name: str) -> Tuple[List[_Row], List[str]]:
    rows = _sheet_rows(workbook, sheet_name)
    header_index, cols = _allotment_header(rows)  # type: ignore[misc]
    skipped: List[str] = []
    result: List[_Row] = []
    current_section: Optional[str] = None

    def cell(row: Tuple[Any, ...], role: str) -> Any:
        col = cols.get(role)
        return row[col] if col is not None and col < len(row) else None

    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        section_text = _text(cell(row, "section"))
        serial_text = _text(cell(row, "serial"))
        if section_text:
            current_section = section_text
        elif serial_text:
            # A new numbered block without a class label (PhD coursework,
            # courses taught to other departments) - not a section of ours.
            current_section = None

        code = _text(cell(row, "code"))
        name = _text(cell(row, "name"))
        if not code and not name:
            continue
        if current_section is None:
            skipped.append(name or code)
            continue

        section_label = current_section
        if re.search(r"RR\b", code.upper()):
            # Re-registration rows sit under the last regular block but are
            # a separate group of students.
            section_label = f"{_year_label(current_section)} RR"

        pattern = _text(cell(row, "pattern"))
        clean_name, name_pattern = _split_name_and_pattern(name)
        result.append(_Row(
            section_label=section_label,
            code_raw=code,
            name=clean_name.rstrip(" :-") or code,
            pattern=pattern or name_pattern,
            theory=_parse_allotment(cell(row, "theory")),
            tutorial=_parse_allotment(cell(row, "tutorial")),
            lab=_parse_allotment(cell(row, "lab")),
            row_number=offset,
        ))
    return result, skipped


def _year_label(section_label: str) -> str:
    parts = section_label.split()
    if len(parts) >= 2 and (parts[-1] == "RR" or (len(parts[-1]) == 1 and parts[-1] not in ROMAN_NUMERALS)):
        return " ".join(parts[:-1])
    return section_label


def _section_name(section_label: str) -> str:
    year = _year_label(section_label)
    return section_label[len(year):].strip() or "A"


def _read_faculty_list(workbook: Any) -> List[Tuple[str, str]]:
    """(name, initials) pairs from the faculty list: a "Name" header with
    the initials in the next column, read until the first blank or
    non-faculty sub-table (lab technicians, students)."""
    for sheet_name in workbook.sheetnames:
        if "faculty" not in sheet_name.lower() or ALLOTMENT_SHEET_PATTERN.search(sheet_name):
            continue
        rows = _sheet_rows(workbook, sheet_name)
        for index, row in enumerate(rows):
            cells = [_text(v).lower() for v in row]
            if "name" not in cells:
                continue
            name_col = cells.index("name")
            faculty = []
            for next_row in rows[index + 1:]:
                name = _text(next_row[name_col]) if name_col < len(next_row) else ""
                initials = _text(next_row[name_col + 1]) if name_col + 1 < len(next_row) else ""
                label = _text(next_row[0]).lower()
                if not name and not initials:
                    if faculty and not label:
                        break
                    if label:  # "Lab Technicians" sub-heading
                        break
                    continue
                if name and initials and re.fullmatch(r"[A-Za-z]+", initials):
                    faculty.append((name, initials))
            if faculty:
                return faculty
    return []


def _elective_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("nptel", ""))


def _read_elective_baskets(workbook: Any) -> Dict[str, str]:
    """{normalised subject name: elective roman numeral} from the elective
    list sheet, so a row named just "Data Science & Engineering" is still
    known to be an Elective-I option."""
    baskets: Dict[str, str] = {}
    for sheet_name in workbook.sheetnames:
        if "elective" not in sheet_name.lower():
            continue
        rows = _sheet_rows(workbook, sheet_name)
        header = next((i for i, row in enumerate(rows) if any(_text(v).lower() == "subjects" for v in row)), None)
        if header is None:
            continue
        subject_col = [_text(v).lower() for v in rows[header]].index("subjects")
        roman = None
        for row in rows[header + 1:]:
            match = ELECTIVE_NAME.search(_text(row[0]) if row else "")
            if match:
                roman = match.group(1)
            name = _text(row[subject_col]) if subject_col < len(row) else ""
            if roman and name:
                baskets.setdefault(_elective_key(name), roman)
    return baskets


def _read_student_counts(workbook: Any) -> Tuple[Dict[str, int], Dict[str, int]]:
    """({course code: students in a lecture}, {course code: students per lab
    batch}) from the faculty-wise allotment letters, where each Th/Tut/Lab
    column is followed by a "Number of Students(approx.)" column - e.g.
    "CO24404(2),CO71455(4)" next to "30,20". Read oldest sheet first so the
    latest revision's numbers win."""
    dated = []
    for order, sheet_name in enumerate(workbook.sheetnames):
        rows = _sheet_rows(workbook, sheet_name)
        header_index = next(
            (i for i, row in enumerate(rows[:15])
             if any(_text(v).lower().startswith("number of students") for v in row)),
            None,
        )
        if header_index is None:
            continue
        dates = [d for d in (_parse_cell_date(_text(v)) for row in rows[:6] for v in row if v) if d]
        dated.append((max(dates) if dates else date.min, order, rows, header_index))

    lecture: Dict[str, int] = {}
    lab: Dict[str, int] = {}
    for _date, _order, rows, header_index in sorted(dated, key=lambda item: item[:2]):
        header = [_text(v).lower() for v in rows[header_index]]
        pairs = [
            (col - 1, col, header[col - 1]) for col, cell in enumerate(header)
            if cell.startswith("number of students") and col > 0
        ]
        for row in rows[header_index + 1:]:
            for code_col, count_col, kind in pairs:
                if count_col >= len(row):
                    continue
                codes = [COURSE_CODE.search(item) for item in re.split(r"[,\n]", _text(row[code_col]).replace("\n", ","))]
                codes = [f"{m.group(1)}{m.group(2)}" for m in codes if m]
                counts = [int(c) for c in re.findall(r"\d+", _text(row[count_col]))]
                if not codes or not counts:
                    continue
                if len(counts) == 1:
                    counts = counts * len(codes)
                target = lab if kind.startswith("lab") else lecture if kind.startswith("th") else None
                if target is None:
                    continue
                for code, count in zip(codes, counts):
                    target[code] = count
    return lecture, lab


def _read_known_names(workbook: Any) -> List[str]:
    """Every person's name under a "Name" header anywhere in the workbook
    (choice list, faculty-wise tables, first-year load, ...)."""
    names: List[str] = []
    for sheet_name in workbook.sheetnames:
        rows = _sheet_rows(workbook, sheet_name)
        name_cols: List[int] = []
        for row in rows:
            for col, value in enumerate(row):
                if _text(value).lower() == "name" and col not in name_cols:
                    name_cols.append(col)
                    continue
            for col in name_cols:
                if col < len(row):
                    text = _text(row[col])
                    if len(_name_words(text)) >= 2 and not re.search(r"\d", text):
                        names.append(text)
    return names


# ------------------------------------------------------ teacher resolution

class _TeacherResolver:
    def __init__(self, faculty: List[Tuple[str, str]], other_names: List[str]):
        self.by_initials = {initials.lower(): (name, initials) for name, initials in faculty}
        # One entry per distinct person; near-identical spellings across
        # sheets ("Kirti Sahu" / "Kitri Sahu") collapse to the first seen,
        # so faculty-list spellings win.
        self.people: List[str] = []
        for name in [n for n, _ in faculty] + other_names:
            norm = _normalise_name(name)
            if not norm:
                continue
            if any(SequenceMatcher(None, norm, _normalise_name(p)).ratio() > 0.85 for p in self.people):
                continue
            self.people.append(name)
        self.faculty_by_norm = {_normalise_name(n): (n, i) for n, i in faculty}
        self.teachers: Dict[str, Dict[str, Any]] = {}
        self.cache: Dict[str, str] = {}
        self.warnings: List[str] = []
        # Teachers created from initials nobody could be matched to: their
        # "name" is just the initials until an admin renames them.
        self.placeholder_ids: Set[str] = set()
        for name, initials in faculty:
            self._add(name, initials)

    def _add(self, name: str, initials: str) -> str:
        teacher_id = f"T_{_slug(initials)}"
        existing = self.teachers.get(teacher_id)
        if existing and _normalise_name(existing["name"]) != _normalise_name(name):
            suffix = 2
            while f"{teacher_id}_{suffix}" in self.teachers:
                suffix += 1
            teacher_id = f"{teacher_id}_{suffix}"
        self.teachers.setdefault(teacher_id, {"id": teacher_id, "name": name, "initials": initials})
        return teacher_id

    def _id_for_person(self, name: str, token: str) -> str:
        norm = _normalise_name(name)
        if norm in self.faculty_by_norm:
            faculty_name, initials = self.faculty_by_norm[norm]
            return f"T_{_slug(initials)}"
        for teacher in self.teachers.values():
            if _normalise_name(teacher["name"]) == norm:
                return teacher["id"]
        return self._add(name, token)

    def resolve(self, token: str) -> str:
        key = token.lower()
        if key in self.cache:
            return self.cache[key]
        if key in self.by_initials:
            name, initials = self.by_initials[key]
            teacher_id = f"T_{_slug(initials)}"
        else:
            # An initials token matches a person when the first letter of
            # each of their name words appears in it in order, and the
            # whole token is spelled from their name in order - "SwM" is
            # Swati Mishra, "McH" is Meghna Chandel. Only a unique match
            # is trusted; a wrong teacher is worse than an unnamed one.
            matches = []
            for person in self.people:
                words = _name_words(person)
                initials = "".join(w[0] for w in words).lower()
                if key[0] == initials[0] and _is_subsequence(initials, key) and _is_subsequence(key, "".join(words).lower()):
                    matches.append(person)
            if len(matches) == 1:
                teacher_id = self._id_for_person(matches[0], token)
                self.warnings.append(f"Initials '{token}' matched to {matches[0]} by name - check this is right.")
            else:
                teacher_id = self._add(token, token)
                self.placeholder_ids.add(teacher_id)
                reason = f"could be {' or '.join(matches)}" if matches else "not found in any name list"
                self.warnings.append(
                    f"Initials '{token}' {reason} - imported as a teacher named '{token}'; rename it under Teachers."
                )
        self.cache[key] = teacher_id
        return teacher_id


# ----------------------------------------------------------------- building

def _resolve_department_name(workbook: Any) -> Optional[str]:
    for sheet_name in workbook.sheetnames[:5]:
        for row in _sheet_rows(workbook, sheet_name)[:5]:
            for value in row:
                text = _text(value)
                match = re.match(r"department of (.+)", text, re.IGNORECASE)
                if match:
                    return match.group(1)
    return None


def match_department(workbook: Any, departments: Sequence[Tuple[str, str]]) -> str:
    """Picks the department whose name covers the workbook's "Department of
    X" heading (e.g. "Computer Engineering" -> "Computer Science &
    Engineering"). With a single department there's nothing to choose."""
    heading = _resolve_department_name(workbook)
    if heading:
        wanted = {w.lower() for w in re.findall(r"[A-Za-z]+", heading) if w.lower() not in {"engg", "dept"}}
        wanted = {("engineering" if w.startswith("engi") else w) for w in wanted}
        for dept_id, dept_name in departments:
            have = {w.lower() for w in re.findall(r"[A-Za-z]+", dept_name)}
            if wanted and wanted <= have:
                return dept_id
    if len(departments) == 1:
        return departments[0][0]
    raise CollegeLoadFormatError(
        f"Could not tell which department this workbook belongs to (heading: '{heading or 'none'}'). "
        "Create or rename a department to match it under Settings, then import again."
    )


def _option_key(name: str) -> str:
    """"Elective-I: Artificial Intelligence" and "Artificial intelligence "
    are the same option."""
    return _elective_key(ELECTIVE_NAME.sub("", name))


def _person_token(resolver: "_TeacherResolver", name: str, initials: str) -> Optional[str]:
    """The initials an allocation/choice/first-year row's person goes by, from
    their Initials column or - when the sheet has none - by matching the name
    against the faculty list."""
    if initials and re.fullmatch(r"[A-Za-z]+", initials):
        return initials
    norm = _normalise_name(name)
    if not norm:
        return None
    if norm in resolver.faculty_by_norm:
        return resolver.faculty_by_norm[norm][1]
    best, best_ratio = None, 0.0
    for known, (_, known_initials) in resolver.faculty_by_norm.items():
        ratio = SequenceMatcher(None, norm, known).ratio()
        if ratio > best_ratio:
            best, best_ratio = known_initials, ratio
    if best_ratio >= 0.82:
        return best
    # a teacher the resolver already created by name ("KS" -> Kirti Sahu)
    for teacher in resolver.teachers.values():
        if SequenceMatcher(None, norm, _normalise_name(str(teacher["name"]))).ratio() >= 0.82:
            return str(teacher["initials"])
    return None


def _elective_slot(entry: LoadEntry) -> Optional[Tuple[str, Optional[int]]]:
    """A Load Calculation row that is just "Elective-I" (the periods the
    class gives to that elective), as opposed to a named option."""
    name = _split_name_and_pattern(entry.name)[0]
    match = ELECTIVE_WORD.search(name) or ELECTIVE_WORD.search(entry.code_raw)
    if not match or not ELECTIVE_WORD.search(name):
        return None
    rest = ELECTIVE_WORD.sub("", name)
    rest = re.sub(r"\([^)]*\)", " ", rest)
    rest = CREDITS.sub("", rest)
    if re.sub(r"[^A-Za-z]", "", rest):
        return None
    credits = CREDITS.search(entry.name)
    return match.group(1).upper(), (int(credits.group(1)) if credits else None)


def _rows_from_sheets(
    sheets: DepartmentLoadSheets, resolver: "_TeacherResolver", warnings: List[str]
) -> List[_Row]:
    """The six-sheet route: Load Calculation gives the subjects and their
    periods, Elective expands the elective slots, and the faculty-wise
    allocation says who teaches what."""
    rows: List[_Row] = []
    slot_rows: Dict[Tuple[str, Optional[int]], List[_Row]] = {}

    def label_of(entry: LoadEntry) -> str:
        year = entry.year_label
        if entry.section == "RR":
            return f"{_year_label(year)} RR"
        return f"{year} {entry.section}".strip() if entry.section and entry.section not in year.split() else year

    def new_row(entry: LoadEntry, name: str, code_raw: str) -> _Row:
        hours = {k: v for k, v in (("theory", entry.theory), ("tutorial", entry.tutorial), ("lab", entry.practical)) if v}
        row = _Row(
            section_label=label_of(entry), code_raw=code_raw, name=name, pattern="",
            theory=[], tutorial=[], lab=[], row_number=entry.row_number,
        )
        row.hours = hours
        row.faculty = {"tutorial": entry.tutorial_faculty, "lab": entry.practical_faculty}
        row.batches = entry.practical_batches or None if entry.practical else None
        row.enrolled = entry.enrolled
        row.class_enrolled = entry.class_enrolled
        row.expected = {
            "theory": entry.theory,
            "tutorial": entry.tutorial * max(1, entry.tutorial_batches) * entry.tutorial_faculty,
            "lab": entry.practical * max(1, entry.practical_batches) * entry.practical_faculty,
        }
        return row

    slot_entries: List[Tuple[LoadEntry, str, Optional[int]]] = []
    for entry in sheets.load:
        slot = _elective_slot(entry)
        if slot:
            slot_entries.append((entry, slot[0], slot[1]))
            continue
        clean_name, name_pattern = _split_name_and_pattern(entry.name)
        rows.append(new_row(entry, clean_name.rstrip(" :-") or entry.code_raw, entry.code_raw))

    # --- electives: every option offered in a class takes the slot's periods
    for entry, roman, credits in slot_entries:
        options = [
            o for o in sheets.electives
            if o.roman == roman and o.offered != "none"
            and (o.credits is None or credits is None or o.credits == credits)
            and (o.year_label is None or o.year_label.split()[0] == entry.year_label.split()[0])
            and (o.section is None or not entry.section or o.section == entry.section)
        ]
        if not options:
            warnings.append(
                f"Elective-{roman} ({label_of(entry)}) has no offered options on the Elective sheet - "
                "imported as one subject with no teacher."
            )
            rows.append(new_row(entry, f"Elective-{roman}", entry.code_raw or f"CO__{roman}"))
            continue
        for option in options:
            row = new_row(entry, f"Elective-{roman}: {option.name}", option.code or entry.code_raw or f"CO__{roman}")
            row.nptel = option.offered == "nptel"
            for initials in option.faculty:
                row.theory.append((initials, entry.theory or 1))
            rows.append(row)
        if not any(o.offered == "offline" for o in options):
            warnings.append(f"Elective-{roman} ({label_of(entry)}) is NPTEL only: it gets self-study periods, no class.")

    # --- allocation: who teaches what
    by_code: Dict[str, List[_Row]] = {}
    by_key: Dict[str, List[_Row]] = {}
    for row in rows:
        match = COURSE_CODE.search(row.code_raw)
        if match:
            by_code.setdefault(f"{match.group(1)}{match.group(2)}", []).append(row)
        by_key.setdefault(_option_key(row.name), []).append(row)
        by_key.setdefault(_acronym(row.name).lower(), []).append(row)

    for entry in sheets.allocation:
        token = _person_token(resolver, entry.name, entry.initials)
        if token is None:
            warnings.append(f"Allocation row '{entry.name}' is not on the Faculty List - skipped.")
            continue
        for item in entry.items:
            match = COURSE_CODE.search(item.label)
            candidates: List[_Row] = []
            if match:
                candidates = by_code.get(f"{match.group(1)}{match.group(2)}", [])
                suffix = re.sub(r"^[\s\-_:]+", "", item.label[match.end():]).strip().upper()
                if suffix:
                    candidates = [r for r in candidates if r.section_label.upper().endswith(f" {suffix}")
                                  or r.section_label.upper() == suffix]
            else:
                key = _option_key(item.label)
                candidates = by_key.get(key) or by_key.get(item.label.strip().lower()) or []
            candidates = [r for r in candidates if not r.nptel]
            if not candidates:
                warnings.append(f"{entry.name}: '{item.label}' is not a subject on the Load Calculation sheet - skipped.")
                continue
            for row in candidates:
                if not row.hours.get(item.kind):
                    warnings.append(
                        f"{entry.name}: '{item.label}' is allocated {item.kind} hours but the Load Calculation "
                        f"has none for {row.name} ({row.section_label}) - skipped."
                    )
                    continue
                target = {"theory": row.theory, "tutorial": row.secondary_tutorial if item.secondary else row.tutorial,
                          "lab": row.secondary_lab if item.secondary else row.lab}[item.kind]
                target.append((token, item.hours))
    return rows


def _match_choice(text: str, index: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The subject components a "can teach" entry like "CO24019T Th Computer
    Architecture" or "E-I CO34601 Data Science & Engineering" refers to."""
    code = COURSE_CODE.search(text)
    marker = re.search(r"[A-Z]{2}\s*\d{5}\s*([TP])\b|\b(Th|Pr)\b", text)
    letter = ((marker.group(1) or marker.group(2) or "")[:1].upper()) if marker else ""
    kinds = {"theory", "tutorial"} if letter == "T" else {"lab"} if letter == "P" else {"theory", "tutorial", "lab"}
    if code:
        plain = f"{code.group(1)}{code.group(2)}"
        found = [e for e in index if e["code"] == plain and e["kind"] in kinds]
        if found:
            return found
    cleaned = COURSE_CODE.sub("", ELECTIVE_NAME.sub("", text))
    cleaned = re.sub(r"\b(Th|Pr|T|P)\b", " ", cleaned)
    key = _elective_key(cleaned)
    if len(key) < 5:
        return []
    return [e for e in index if e["key"] == key and e["kind"] in kinds]


def convert_college_load_workbook(workbook: Any, department_id: str) -> ConversionResult:
    legacy = True
    try:
        sheet_name, sheet_date = _latest_allotment_sheet(workbook)
    except CollegeLoadFormatError:
        if not is_department_load_workbook(workbook):
            raise
        legacy = False
    sheets = read_department_load(workbook)
    warnings: List[str] = list(sheets.warnings)

    if legacy:
        rows, skipped = _read_allotment_rows(workbook, sheet_name)
        if not rows:
            raise CollegeLoadFormatError(f"{sheet_name}: no subject rows found under the Class/Year table")
        faculty = _read_faculty_list(workbook)
    else:
        sheet_name, sheet_date, skipped = sheets.found["load"], None, []
        faculty = [(f.name, f.initials) for f in sheets.faculty]
        if not faculty:
            raise CollegeLoadFormatError("The Faculty List sheet has no teachers (Name and Initials columns).")

    other_names = _read_known_names(workbook)
    other_names += [c.name for c in sheets.choices] + [a.name for a in sheets.allocation] + [f.name for f in sheets.first_year]
    resolver = _TeacherResolver(faculty, other_names)
    if not legacy:
        rows = _rows_from_sheets(sheets, resolver, warnings)
        if not rows:
            raise CollegeLoadFormatError(f"{sheet_name}: no subject rows found")

    elective_baskets = _read_elective_baskets(workbook)
    nptel_by_roman: Dict[str, Set[str]] = {}
    for option in sheets.electives:
        if option.offered == "nptel":
            nptel_by_roman.setdefault(option.roman, set()).add(_option_key(option.name))
    lecture_counts, lab_counts = _read_student_counts(workbook)
    if legacy:
        other_revisions = [n for n in workbook.sheetnames if ALLOTMENT_SHEET_PATTERN.search(n) and n != sheet_name]
        if other_revisions:
            warnings.append(
                f"Using '{sheet_name}'" + (f" (dated {sheet_date:%d/%m/%Y})" if sheet_date else "")
                + f" as the latest allotment; ignored older revisions: {', '.join(other_revisions)}."
            )
    if skipped:
        warnings.append(
            "Skipped rows with no class/section (courses for other departments or PhD work - "
            f"add them manually if they should block teacher time): {', '.join(skipped)}."
        )

    # --- years and sections, in workbook order
    years: Dict[str, Dict[str, Any]] = {}
    sections: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        year = _year_label(row.section_label)
        year_id = f"AY_{_slug(year)}"
        years.setdefault(year_id, {"id": year_id, "name": f"{year} Year" if year in ROMAN_NUMERALS else year,
                                   "department_id": department_id, "sections": set()})
        section_id = f"SEC_{_slug(row.section_label)}"
        sections.setdefault(section_id, {"id": section_id, "year_id": year_id,
                                         "name": _section_name(row.section_label),
                                         "strength": DEFAULT_SECTION_STRENGTH, "label": row.section_label,
                                         "lettered": _year_label(row.section_label) != row.section_label
                                         and not row.section_label.endswith(" RR")})
        years[year_id]["sections"].add(section_id)

    # --- subjects: one base id per curriculum row, shared across sections
    # only when every section has the same teachers for it (otherwise the
    # section-specific allotment would be lost).
    def base_id(row: _Row) -> str:
        code = COURSE_CODE.match(row.code_raw)
        rr = "_RR" if row.section_label.endswith(" RR") else ""
        if code:
            return f"{code.group(1)}{code.group(2)}{rr}"
        return f"{_slug(_year_label(row.section_label))}_{_slug(row.name)[:40]}{rr}"

    def teacher_signature(row: _Row) -> Tuple:
        return tuple(sorted({(kind, t.lower()) for kind, items in
                             (("th", row.theory), ("tut", row.tutorial + row.secondary_tutorial),
                              ("lab", row.lab + row.secondary_lab)) for t, _ in items}))

    signatures: Dict[str, set] = {}
    for row in rows:
        signatures.setdefault(base_id(row), set()).add(teacher_signature(row))

    subjects: Dict[str, Dict[str, Any]] = {}
    section_subjects: Dict[Tuple[str, str], Dict[str, Any]] = {}
    teacher_subjects: Dict[Tuple[str, str], str] = {}   # (teacher id, subject id) -> main | secondary
    elective_groups: Dict[str, Dict[str, Any]] = {}
    unscheduled: List[str] = []
    nptel_subjects: List[str] = []
    sections_with_labs: set = set()
    subject_index: List[Dict[str, Any]] = []
    expected_hours: Dict[str, Tuple[int, str]] = {}
    # Student numbers per section from the faculty-wise letters: a section
    # is as big as its largest lecture; a lab batch as big as its labs.
    section_lecture_size: Dict[str, int] = {}
    section_lab_size: Dict[str, int] = {}
    section_enrolled: Dict[str, int] = {}
    section_class_enrolled: Dict[str, int] = {}
    section_batches: Dict[str, int] = {}
    soft_fields: Dict[str, Dict[str, Set[str]]] = {}
    unallotted_fields = {"delivery_mode", "lecture_hours", "tutorial_hours", "practical_hours", "weekly_hours"}

    for row in rows:
        section_id = f"SEC_{_slug(row.section_label)}"
        subject_base = base_id(row)
        if len(signatures[subject_base]) > 1:
            subject_base = f"{subject_base}_{_slug(_section_name(row.section_label))}"
        code_match = COURSE_CODE.match(row.code_raw)
        code = (f"{code_match.group(1)}{code_match.group(2)}" if code_match else _acronym(row.name))
        plain_code = code
        if row.enrolled:
            section_enrolled[section_id] = max(section_enrolled.get(section_id, 0), row.enrolled)
        if row.class_enrolled:
            section_class_enrolled[section_id] = row.class_enrolled
        if row.batches:
            section_batches[section_id] = max(section_batches.get(section_id, 0), row.batches)
        if code_match and not row.section_label.endswith(" RR"):
            if row.theory and code in lecture_counts:
                section_lecture_size[section_id] = max(section_lecture_size.get(section_id, 0), lecture_counts[code])
            if row.lab and code in lab_counts:
                section_lab_size[section_id] = min(section_lab_size.get(section_id, lab_counts[code]), lab_counts[code])
        if row.section_label.endswith(" RR"):
            code += " RR"
        pattern = _parse_pattern(row.pattern)

        group_id = None
        elective_match = ELECTIVE_NAME.search(row.name) or ELECTIVE_NAME.search(row.code_raw)
        roman = elective_match.group(1) if elective_match else elective_baskets.get(_elective_key(row.name))
        is_elective = bool(roman) and "OEC" not in row.name.upper() and "OEC" not in row.code_raw.upper()
        # An NPTEL option is nobody's class: it is taken out of the basket
        # and only holds its students for self-study periods.
        nptel = row.nptel or (is_elective and _option_key(row.name) in nptel_by_roman.get(roman or "", set()))
        if is_elective and not nptel:
            year = _year_label(row.section_label)
            rr = " RR" if row.section_label.endswith(" RR") else ""
            group_id = f"EG_{_slug(year + rr)}_E{roman}"
            elective_groups.setdefault(group_id, {
                "id": group_id, "department_id": department_id,
                "name": f"{year}{rr} Elective-{roman}", "subjects": [],
            })

        if nptel:
            self_study = (row.hours.get("theory") or pattern["L"] or sum(h for _, h in row.theory) or DEFAULT_NPTEL_HOURS)
            if row.theory or row.tutorial or row.lab:
                warnings.append(f"{row.name} ({row.section_label}) is an NPTEL course: its teacher allotment is ignored.")
            subjects.setdefault(subject_base, {
                "id": subject_base, "name": row.name.strip(), "code": code, "type": "theory",
                "department_id": department_id, "delivery_mode": "MOOC_NPTEL",
                "lecture_hours": self_study, "tutorial_hours": 0, "practical_hours": 0, "weekly_hours": 0,
                "periods_per_session": 1, "back_to_back": True, "max_per_day": 1,
                "requires_room_type": None, "linked_group_id": None, "elective_group_id": None,
                "teachers_required": 1, "self_study_hours": self_study,
            })
            section_subjects[(section_id, subject_base)] = {
                "section_id": section_id, "subject_id": subject_base, "is_elective": False, "elective_group_id": None,
            }
            nptel_subjects.append(f"{row.name} ({row.section_label})")
            continue

        components: List[Dict[str, Any]] = []
        if row.hours:
            for kind, teachers, secondary in (
                ("theory", row.theory, []), ("tutorial", row.tutorial, row.secondary_tutorial),
                ("lab", row.lab, row.secondary_lab),
            ):
                if row.hours.get(kind):
                    required = 1 if kind == "theory" else row.faculty.get(kind, 1)
                    if secondary:
                        required = max(required, 2)  # secondary faculty are in the room too
                    components.append({"kind": kind, "hours": row.hours[kind], "teachers": teachers,
                                       "secondary": secondary, "required": required, "expected": row.expected.get(kind, 0)})
        else:
            if row.theory:
                components.append({"kind": "theory", "hours": sum(h for _, h in row.theory), "teachers": row.theory})
            if row.tutorial:
                hours = pattern["Tut"] or max(h for _, h in row.tutorial)
                components.append({"kind": "tutorial", "hours": hours, "teachers": row.tutorial})
            if row.lab:
                planned = PERIODS_PER_PRACTICAL_CREDIT * (pattern["P"] or 1)
                # A teacher allotted fewer hours than one full lab (an
                # internship review, "CHT(1)") means the session is that short.
                hours = min(planned, max(h for _, h in row.lab))
                components.append({"kind": "lab", "hours": hours, "teachers": row.lab})
            for component in components:
                component.update({"secondary": [], "required": 1, "expected": 0})

        if not components:
            kind = "lab" if pattern["P"] and not pattern["L"] else "theory"
            components.append({"kind": kind, "hours": 0, "teachers": [], "secondary": [], "required": 1, "expected": 0})
            unscheduled.append(f"{row.name} ({row.section_label})")

        suffixes = {"theory": "", "tutorial": "_TUT", "lab": "_LAB"}
        linked = subject_base if len(components) > 1 else None
        for index, component in enumerate(components):
            kind = component["kind"]
            subject_id = subject_base if index == 0 else f"{subject_base}{suffixes[kind] or '_TH'}"
            hours = component["hours"]
            periods = 2 if kind == "lab" and hours >= 2 and hours % 2 == 0 else 1
            subject = {
                "id": subject_id,
                "name": _component_name(row.name, kind, len(components)),
                "code": code,
                "type": kind,
                "department_id": department_id,
                "delivery_mode": "IN_PERSON" if hours > 0 else "SELF_STUDY",
                "lecture_hours": hours if kind == "theory" else 0,
                "tutorial_hours": hours if kind == "tutorial" else 0,
                "practical_hours": hours if kind == "lab" else 0,
                "weekly_hours": hours,
                "periods_per_session": periods,
                "back_to_back": True,
                "max_per_day": 1,
                "requires_room_type": {"theory": "lecture", "lab": "lab"}.get(kind),
                "linked_group_id": linked,
                "elective_group_id": group_id,
                "teachers_required": component["required"],
                "self_study_hours": 0,
            }
            # An elective basket holds ALTERNATIVES - a student takes one of
            # them, so the solver runs every member at the same time. Only
            # the main part of an elective (its theory, or its tutorial
            # when there is no theory) is an alternative; its lab/tutorial
            # is attended by the same students as that theory, so putting
            # it in the basket would put one cohort in two places at once.
            # Those parts stay linked to the main part (linked_group_id) and
            # are scheduled on their own.
            in_basket = group_id if index == 0 else None
            subject["elective_group_id"] = in_basket
            subjects.setdefault(subject_id, subject)
            section_subjects[(section_id, subject_id)] = {
                "section_id": section_id, "subject_id": subject_id,
                "is_elective": in_basket is not None, "elective_group_id": in_basket,
            }
            if in_basket and subject_id not in elective_groups[in_basket]["subjects"]:
                elective_groups[in_basket]["subjects"].append(subject_id)
            if kind == "lab" and hours > 0:
                sections_with_labs.add(section_id)
            subject_index.append({"id": subject_id, "kind": kind, "code": plain_code, "key": _option_key(row.name)})
            allocated = 0
            for token, token_hours in component["teachers"]:
                teacher_subjects[(resolver.resolve(token), subject_id)] = "main"
                allocated += token_hours
            for token, token_hours in component["secondary"]:
                teacher_subjects.setdefault((resolver.resolve(token), subject_id), "secondary")
                allocated += token_hours
            if component["expected"] and allocated and allocated != component["expected"]:
                expected_hours[subject_id] = (allocated, f"{row.name} ({row.section_label}) {kind}: expected "
                                                         f"{component['expected']} hours in total, allocated {allocated}")

    allotted_ids = set(teacher_subjects)
    allotted_subjects = {subject_id for _, subject_id in allotted_ids}
    allocated_teachers = {teacher_id for teacher_id, _ in allotted_ids}
    for _, text in sorted(expected_hours.items()):
        warnings.append(f"Hours do not add up - {text[1]}.")

    # --- Subject Choice: who CAN teach a subject nobody was allocated to.
    # Only teachers with no allocation of their own are considered - an
    # allocated teacher teaches exactly what the allocation says.
    choice_filled: Set[str] = set()
    unmatched_choices: Set[str] = set()
    for choice in sheets.choices:
        token = _person_token(resolver, choice.name, choice.initials)
        if token is None:
            unmatched_choices.add(choice.name)
            continue
        teacher_id = resolver.resolve(token)
        if teacher_id in allocated_teachers:
            continue
        for text in choice.choices:
            for entry in _match_choice(text, subject_index):
                if entry["id"] not in allotted_subjects and subjects[entry["id"]]["delivery_mode"] != "MOOC_NPTEL":
                    teacher_subjects.setdefault((teacher_id, entry["id"]), "main")
                    choice_filled.add(entry["id"])
    if unmatched_choices:
        warnings.append(
            "Subject Choice rows not matched to the Faculty List (skipped): " + ", ".join(sorted(unmatched_choices)) + "."
        )

    # --- who ended up with which subject
    teachers_of: Dict[str, Set[str]] = {}
    for (teacher_id, subject_id) in teacher_subjects:
        teachers_of.setdefault(subject_id, set()).add(teacher_id)
    without_teacher: List[str] = []
    for subject_id, subject in subjects.items():
        if subject["delivery_mode"] == "MOOC_NPTEL":
            continue
        people = teachers_of.get(subject_id, set())
        if not people:
            if subject["weekly_hours"] > 0:
                subject["delivery_mode"] = "SELF_STUDY"
                without_teacher.append(subject["name"])
            soft_fields.setdefault("Subjects", {}).setdefault(subject_id, set()).update(unallotted_fields)
            continue
        if subject_id not in allotted_subjects and subject["weekly_hours"] == 0:
            soft_fields.setdefault("Subjects", {}).setdefault(subject_id, set()).update(unallotted_fields)
        if subject["teachers_required"] > len(people):
            warnings.append(
                f"{subject['name']} needs {subject['teachers_required']} teachers at once but only "
                f"{len(people)} are allocated - set to {len(people)}."
            )
            subject["teachers_required"] = len(people)
    if unscheduled:
        warnings.append(
            "No faculty allotted yet, so imported as SELF_STUDY (not scheduled) - set delivery mode to "
            f"IN_PERSON once assigned: {', '.join(unscheduled)}."
        )
    if without_teacher:
        warnings.append(
            "Nobody is allocated or has chosen these, so they are imported as SELF_STUDY (not scheduled) until "
            f"a teacher is assigned: {', '.join(without_teacher)}."
        )
    if choice_filled:
        warnings.append(
            f"{len(choice_filled)} subject(s) had no allocation; every teacher without an allocation who chose "
            "them can teach them (check Faculty-wise allocation)."
        )
    if nptel_subjects:
        warnings.append(
            "NPTEL (self-study periods at the start or end of the day, no teacher, not in the elective "
            f"basket): {', '.join(nptel_subjects)}."
        )

    # --- section strengths: from the student numbers where the workbook
    # gives them; a lettered section with none takes its sibling's (II A
    # and II B are split from one intake); otherwise the default.
    lettered_in_year: Dict[str, int] = {}
    for section in sections.values():
        if section["lettered"]:
            lettered_in_year[section["year_id"]] = lettered_in_year.get(section["year_id"], 0) + 1
    estimated: List[str] = []
    for section_id, section in sections.items():
        size = section_enrolled.get(section_id)
        if size is None and section_class_enrolled.get(section_id) and section["lettered"]:
            # Only the class total is given: split it between the sections.
            size = -(-section_class_enrolled[section_id] // lettered_in_year[section["year_id"]])
        if size is None:
            size = section_lecture_size.get(section_id)
        if size is None and section["lettered"]:
            siblings = [
                section_lecture_size[other_id] for other_id, other in sections.items()
                if other["year_id"] == section["year_id"] and other["lettered"] and other_id in section_lecture_size
            ]
            size = max(siblings) if siblings else None
        if size is None and not section["lettered"]:
            # An unsplit class (PG) runs its lab as one group - the lab's
            # headcount is the class's.
            size = section_lab_size.get(section_id)
        if size is None:
            estimated.append(section["label"])
            soft_fields.setdefault("Sections", {})[section_id] = {"strength"}
        section["strength"] = size or DEFAULT_SECTION_STRENGTH
    if estimated:
        warnings.append(
            f"No student numbers in the workbook for {', '.join(estimated)} - set to {DEFAULT_SECTION_STRENGTH}. "
            "Correct them under Years & Sections."
        )

    # --- lab batches: the Load Calculation's "No. of Batches" where given,
    # else sized from the labs' student numbers (90 students in labs of 30 =
    # 3 batches), else the college's usual split.
    lab_batches = []
    defaulted_batches: List[str] = []
    soft_batch_sections: Set[str] = set()
    for section_id in sorted(sections_with_labs):
        section = sections[section_id]
        name = section["name"]
        lab_size = section_lab_size.get(section_id)
        if section_batches.get(section_id):
            count = section_batches[section_id]
        elif lab_size:
            count = max(1, round(section["strength"] / lab_size))
        else:
            count = DEFAULT_BATCHES_LETTERED_SECTION if section["lettered"] else DEFAULT_BATCHES_OTHER_SECTION
            defaulted_batches.append(section["label"])
            soft_batch_sections.add(section_id)
        for number in range(1, count + 1):
            batch_name = f"{name}{number}" if count > 1 else name
            lab_batches.append({
                "id": f"LB_{_slug(section['label'])}_{number}", "section_id": section_id,
                "batch_name": batch_name, "strength": section["strength"] // count,
            })
    if defaulted_batches:
        warnings.append(
            f"No lab sizes in the workbook for {', '.join(defaulted_batches)} - created "
            f"{DEFAULT_BATCHES_LETTERED_SECTION} batches per A/B section and {DEFAULT_BATCHES_OTHER_SECTION} "
            "otherwise. Adjust under Lab Batches if different."
        )

    # --- First Year Load: hours already given to the central timetable
    first_year_hours: Dict[str, int] = {}
    unknown_first_year: List[str] = []
    for entry in sheets.first_year:
        token = _person_token(resolver, entry.name, entry.initials)
        if token is None:
            unknown_first_year.append(entry.name)
            continue
        teacher_id = resolver.resolve(token)
        first_year_hours[teacher_id] = first_year_hours.get(teacher_id, 0) + entry.hours
    if unknown_first_year:
        warnings.append("First Year Load rows not on the Faculty List (skipped): " + ", ".join(unknown_first_year) + ".")

    warnings.extend(resolver.warnings)
    for teacher_id in resolver.placeholder_ids:
        soft_fields.setdefault("Teachers", {})[teacher_id] = {"name"}
    # The workbook never says whether a basket must run in one slot - that
    # is the admin's call (it depends on rooms and teachers), so a new basket
    # starts parallel and an existing one keeps whatever it was set to.
    for group_id in elective_groups:
        soft_fields.setdefault("ElectiveGroups", {})[group_id] = {"must_be_parallel"}

    max_hours = {f.initials.lower(): f.max_hours for f in sheets.faculty if f.max_hours}
    teacher_rows = []
    for teacher in resolver.teachers.values():
        record = {**teacher, "department_id": department_id,
                  "max_weekly_hours": max_hours.get(str(teacher["initials"]).lower())}
        if sheets.first_year:
            record["first_year_hours"] = first_year_hours.get(teacher["id"], 0)
        teacher_rows.append(record)

    workbook_out = Workbook()
    workbook_out.remove(workbook_out.active)

    def add_sheet(title: str, columns: List[str], records: Iterable[Dict[str, Any]]) -> None:
        sheet = workbook_out.create_sheet(title)
        sheet.append(columns)
        for record in records:
            sheet.append([record.get(column) for column in columns])

    add_sheet("AcademicYears", ["id", "name", "department_id", "num_sections", "default_section_strength"],
              ({**y, "num_sections": len(y["sections"]),
                "default_section_strength": max(sections[s]["strength"] for s in y["sections"])}
               for y in years.values()))
    add_sheet("Sections", ["id", "year_id", "name", "strength"], sections.values())
    add_sheet("ElectiveGroups", ["id", "department_id", "name", "must_be_parallel"],
              ({**g, "must_be_parallel": True} for g in elective_groups.values()))
    add_sheet("ElectiveGroupSubjects", ["elective_group_id", "subject_id"],
              ({"elective_group_id": g["id"], "subject_id": s} for g in elective_groups.values() for s in g["subjects"]))
    add_sheet("Subjects", ["id", "name", "code", "type", "department_id", "delivery_mode",
                           "lecture_hours", "tutorial_hours", "practical_hours", "weekly_hours",
                           "periods_per_session", "back_to_back", "max_per_day", "requires_room_type",
                           "linked_group_id", "elective_group_id", "teachers_required", "self_study_hours"],
              subjects.values())
    add_sheet("Teachers", ["id", "name", "initials", "department_id", "max_weekly_hours", "first_year_hours"],
              teacher_rows)
    add_sheet("SectionSubjects", ["section_id", "subject_id", "is_elective", "elective_group_id"],
              section_subjects.values())
    add_sheet("TeacherSubjects", ["teacher_id", "subject_id", "role"],
              ({"teacher_id": t, "subject_id": s, "role": role} for (t, s), role in sorted(teacher_subjects.items())))
    add_sheet("LabBatches", ["id", "section_id", "batch_name", "strength"], lab_batches)
    return ConversionResult(
        workbook=workbook_out, source_sheet=sheet_name, warnings=warnings,
        soft_fields=soft_fields, soft_batch_sections=soft_batch_sections,
    )


# ----------------------------------------------------------------- template

def build_college_template() -> Workbook:
    """A blank workbook with the six sheets of the department load file, laid
    out like the college's own (01_Load_july2026.xlsx) with the few columns
    it lacked added. Every header is one department_load_sheets.py looks for;
    tests/integration/test_college_load_import.py reads the template back
    through the converter so the two can't drift apart."""
    from openpyxl.styles import Alignment, Font

    today = date.today()
    bold = Font(bold=True)
    title_font = Font(bold=True, size=13)
    hint_font = Font(italic=True, color="666666")
    example = Font(italic=True, color="888888")
    workbook = Workbook()
    workbook.remove(workbook.active)

    def make(title: str, heading: str, hint: str, widths: Sequence[int]):
        sheet = workbook.create_sheet(title)
        sheet.append(["Department of <your department>"])
        sheet.append([heading])
        sheet.append([f"Date: {today:%d/%m/%Y}"])
        sheet.append([hint])
        sheet["A1"].font = title_font
        sheet["A4"].font = hint_font
        for letter, width in zip("ABCDEFGHIJKLMNOPQ", widths):
            sheet.column_dimensions[letter].width = width
        return sheet

    def style(sheet, header_rows: Sequence[int], example_rows: range) -> None:
        for index in header_rows:
            for cell in sheet[index]:
                cell.font = bold
                cell.alignment = Alignment(wrap_text=True, vertical="center")
        for index in example_rows:
            for cell in sheet[index]:
                cell.font = example

    # 1 - Faculty List
    faculty = make(
        "Faculty List", "Faculty List",
        "One row per teacher. Initials are what the allocation sheet uses; Max Hours/Week is optional (default 24).",
        (8, 30, 10, 18, 16, 14),
    )
    faculty.append(["S.No.", "Name", "Initials", "Designation", "Contact No.", "Max Hours/Week"])
    faculty.append([1, "Dr. Example Teacher", "ET", "Professor", "", 18])
    faculty.append([2, "Ms. Sample Faculty", "SF", "Assistant Professor", "", ""])
    faculty.append([3, "Mr. Another Teacher", "AT", "Assistant Professor", "", ""])
    style(faculty, [5], range(6, 9))
    faculty.freeze_panes = "A6"

    # 2 - Subject Choice
    choice = make(
        "Subject Choice", "Faculty Subject Choice List",
        "What each teacher CAN teach, in order of preference: the subject code and name, or E-I / E-II / E-III and the "
        "elective's name. Used for subjects nobody is allocated to.",
        (8, 26, 10, 38, 38, 38, 38),
    )
    choice.append(["S.No.", "Name", "Initials", "Subject Choice-I", "Subject Choice-II", "Subject Choice-III", "Subject Choice-IV"])
    choice.append([1, "Mr. Another Teacher", "AT", "CO24517 Data Structures", "E-I Data Science & Engineering", "", ""])
    choice.append([2, "Ms. Sample Faculty", "SF", "CO24019 Computer Architecture", "", "", ""])
    style(choice, [5], range(6, 8))
    choice.freeze_panes = "A6"

    # 3 - Load Calculation
    load = make(
        "Load Calculation", 'Teaching load of the department for SEM "A", Session <month-month year>',
        "One row per subject. Section: A, B or RR (blank for a class that isn't split). Periods are per week; "
        "Tutorial / Practical = periods x batches x faculty. An 'Elective-I' row is the periods the class gives to "
        "that elective - its options are on the Elective sheet. Enrolled students: the first row of a class is enough.",
        (8, 12, 10, 16, 40, 14, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 18),
    )
    load.append([
        "S.No.", "Class/ Year", "Section", "Subject Code", "Subject Nomenclature",
        "Actual No. of students enrolled", "Load(periods/Week)", None, None, None, None, None, None, None, None, "Total", "Remarks",
    ])
    load.append([None, None, None, None, None, None, "Theory", "Tutorial (No. of Periods x No. of Batches x No. of Faculty)",
                 None, None, None, "Practical (No. of Periods x No. of Batches x No. of Faculty)", None, None, None])
    load.append([None, None, None, None, None, None, "No. of periods", "No. of periods", "No. of Batches", "No. of faculty",
                 "Total", "No. of periods", "No. of Batches", "No. of faculty", "Total"])
    samples = [
        [1, "II", "A", "CO24019", "Computer Architecture", 90, 3, 0, 0, 0, None, 0, 0, 0, None],
        [None, None, "A", "CO24402", "Computer Architecture Lab", None, 0, 0, 0, 0, None, 2, 3, 2, None],
        [None, None, "B", "CO24517", "Data Structures", None, 3, 0, 0, 0, None, 0, 0, 0, None],
        [2, "III", "A", "CO34501", "Database Management Systems", 60, 3, 1, 3, 1, None, 0, 0, 0, None],
        [None, None, "A", "", "Elective-I", None, 3, 0, 0, 0, None, 0, 0, 0, None],
    ]
    for number, values in enumerate(samples, start=8):
        load.append(values)
        load.cell(row=number, column=11, value=f"=H{number}*I{number}*J{number}")
        load.cell(row=number, column=15, value=f"=L{number}*M{number}*N{number}")
        load.cell(row=number, column=16, value=f"=G{number}+K{number}+O{number}")
    style(load, [5, 6, 7], range(8, 13))
    load.freeze_panes = "A8"

    # 4 - Faculty wise subject allocation
    allocation = make(
        "Faculty wise subject allocation", "FACULTYWISE SUBJECT ALLOCATION",
        "The final list: a teacher listed here teaches exactly these subjects. Write CODE(hours), several separated by "
        "commas. Add -A, -B or -RR (CO24019-A) only when the same code runs in more than one class. Secondary columns: "
        "teachers who assist a session another teacher runs.",
        (8, 26, 10, 16, 12, 16, 12, 16, 12, 18, 12, 18, 18, 8),
    )
    allocation.append([
        "S.No.", "Name", "Initials", "Th1", "Number of Students", "Th2", "Number of Students", "Tut", "Number of Students",
        "Lab", "Number of Students", "Tut (Secondary)", "Lab (Secondary)", "Total",
    ])
    allocation.append([1, "Dr. Example Teacher", "ET", "CO24019-A(3)", 90, "", "", "", "", "CO24402(6)", 30, "", "", 9])
    allocation.append([2, "Ms. Sample Faculty", "SF", "CO24517(3)", 90, "", "", "", "", "", "", "", "CO24402(6)", 9])
    allocation.append([3, "Mr. Another Teacher", "AT", "CO34501(3)", 60, "", "", "CO34501(3)", 20, "", "", "", "", 6])
    style(allocation, [5], range(6, 9))
    allocation.freeze_panes = "A6"

    # 5 - First Year Load
    first_year = make(
        "First Year Load", "FACULTYWISE I YEAR LOAD ALLOTMENT",
        "Hours each teacher gives to the first-year timetable. They are taken off that teacher's weekly hours.",
        (8, 26, 10, 18, 14, 14, 8),
    )
    first_year.append(["S.No.", "Name", "Initials", "Th1", "Tut", "Lab", "Total"])
    first_year.append([1, "Ms. Sample Faculty", "SF", "IT10007(2)", "IT10007(1)", "IT10007(4)", 7])
    style(first_year, [5], range(6, 7))
    first_year.freeze_panes = "A6"

    # 6 - Elective
    elective = make(
        "Elective", "B.Tech Elective Subject List",
        "Offered: Offline (a teacher takes it), NPTEL (self-study, no teacher - kept to the first or last period of a "
        "day) or - (not offered). Faculty: initials of the teacher(s) for an Offline option. Leave Class/ Section "
        "blank for all classes.",
        (24, 12, 10, 8, 14, 36, 12, 12, 40, 44),
    )
    elective.append(["Elective No.", "Class/ Year", "Section", "S.No.", "Subject Code", "Subjects", "Offered", "Faculty",
                     "Details", "Link to NPTEL Course"])
    elective.append(["Elective-I (3 credits)", "III", "", 1, "CO34601", "Data Science & Engineering", "Offline", "AT", "", ""])
    elective.append([None, "", "", 2, "", "Artificial Intelligence", "NPTEL", "",
                     "Artificial Intelligence: Foundations and Algorithms, IIT Delhi", "https://onlinecourses.nptel.ac.in/"])
    elective.append([None, "", "", 3, "", "Software Architecture", "-", "", "", ""])
    style(elective, [5], range(6, 9))
    elective.freeze_panes = "A6"
    return workbook
