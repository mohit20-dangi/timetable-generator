"""Readers for the six sheets of the department load workbook:

  1. Faculty List                     who the teachers are
  2. Subject Choice                   which teacher CAN teach what
  3. Load Calculation                 each class's subjects and their periods
  4. Faculty wise subject allocation  the final word on who teaches what
  5. First Year Load                  hours given to the first-year timetable
  6. Elective                         elective options (Offline / NPTEL / -)

They follow the sheets of the college's own workbook (01_Load_july2026.xlsx),
with a few columns added where that workbook had no place for something
(Section, Initials, the secondary-faculty columns, the elective Class and
Faculty). Sheets are found by name, ignoring case, spaces and punctuation, so
the college's own names ("load_calculation", "Choice_filling", "I_YEAR_LOAD",
"electives") work as they are.

Nothing here touches the database; college_load_import.py turns what is read
into the app's import sheets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROMAN = r"(?:IV|III|II|I)"
COURSE_CODE = re.compile(r"([A-Z]{2})\s*(\d{5})")
ELECTIVE_WORD = re.compile(rf"\b(?:Elective|E)\s*[-–:]?\s*({ROMAN})\b", re.IGNORECASE)
CREDITS = re.compile(r"(\d+)\s*credit", re.IGNORECASE)
HOURS_IN_BRACKETS = re.compile(r"\(\s*(\d+)\s*(?:\+\s*(\d+))?\s*\)")
DATE_IN_CELL = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")

SHEET_ALIASES = {
    "faculty": ("facultylist", "faculty"),
    "choice": ("subjectchoice", "choicefilling", "subjectchoices", "facultysubjectchoice"),
    "load": ("loadcalculation", "loadcalc", "teachingload"),
    "allocation": ("facultywisesubjectallocation", "facultywiseallocation", "subjectallocation"),
    "first_year": ("firstyearload", "iyearload", "1styearload", "firstyear"),
    "elective": ("elective", "electives"),
}


@dataclass
class FacultyEntry:
    name: str
    initials: str
    max_hours: Optional[int] = None


@dataclass
class ChoiceEntry:
    name: str
    initials: str
    choices: List[str]


@dataclass
class LoadEntry:
    year_label: str                 # "II", "PG I", ...
    section: str                    # "A", "B", "RR" or ""
    code_raw: str
    name: str
    theory: int = 0
    tutorial: int = 0
    tutorial_batches: int = 0
    tutorial_faculty: int = 1
    practical: int = 0
    practical_batches: int = 0
    practical_faculty: int = 1
    enrolled: Optional[int] = None  # this row's own count
    class_enrolled: Optional[int] = None  # the class block's count, carried down
    row_number: int = 0


@dataclass
class AllocationItem:
    label: str                      # the text before the brackets: "CO24402", "CO24019-A", "DSE"
    hours: int
    kind: str                       # theory | tutorial | lab
    secondary: bool = False


@dataclass
class AllocationEntry:
    name: str
    initials: str
    items: List[AllocationItem] = field(default_factory=list)
    students: Dict[str, int] = field(default_factory=dict)  # code -> approx. students


@dataclass
class FirstYearEntry:
    name: str
    initials: str
    hours: int


@dataclass
class ElectiveOption:
    roman: str                      # "I", "II", ...
    credits: Optional[int]
    name: str
    code: str
    offered: str                    # offline | nptel | none
    year_label: Optional[str] = None
    section: Optional[str] = None
    faculty: List[str] = field(default_factory=list)  # initials


@dataclass
class DepartmentLoadSheets:
    faculty: List[FacultyEntry] = field(default_factory=list)
    choices: List[ChoiceEntry] = field(default_factory=list)
    load: List[LoadEntry] = field(default_factory=list)
    allocation: List[AllocationEntry] = field(default_factory=list)
    first_year: List[FirstYearEntry] = field(default_factory=list)
    electives: List[ElectiveOption] = field(default_factory=list)
    allocation_sheet: str = ""
    found: Dict[str, str] = field(default_factory=dict)  # role -> sheet title
    warnings: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers

def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def as_int(value: Any) -> int:
    match = re.search(r"-?\d+", text_of(value))
    return int(match.group()) if match else 0


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _rows(workbook: Any, name: str) -> List[Tuple[Any, ...]]:
    return list(workbook[name].iter_rows(values_only=True))


def _sheet_date(rows: Sequence[Tuple[Any, ...]]) -> date:
    best = date.min
    for row in rows[:8]:
        for value in row:
            match = DATE_IN_CELL.search(text_of(value)) if value else None
            if match:
                day, month, year = (int(p) for p in match.groups())
                try:
                    best = max(best, date(year + (2000 if year < 100 else 0), month, day))
                except ValueError:
                    pass
    return best


def _header_row(rows: Sequence[Tuple[Any, ...]], needs: Sequence[str], limit: int = 15) -> Optional[int]:
    for index, row in enumerate(rows[:limit]):
        cells = [text_of(v).lower() for v in row]
        if all(any(cell == need or cell.startswith(need) for cell in cells) for need in needs):
            return index
    return None


def find_sheet(workbook: Any, role: str) -> Optional[str]:
    wanted = SHEET_ALIASES[role]
    titles = {name: _norm_title(name) for name in workbook.sheetnames}
    for alias in wanted:
        for name, norm in titles.items():
            if norm == alias:
                return name
    return None


def find_allocation_sheet(workbook: Any) -> Optional[str]:
    """The faculty-wise allocation: by title when it has the template's own
    name, otherwise the newest sheet with Name + Th1 + Th2 + Lab headers
    (the college keeps one per revision, and the first-year load has no Th2)."""
    named = find_sheet(workbook, "allocation")
    if named:
        return named
    candidates = []
    for order, name in enumerate(workbook.sheetnames):
        rows = _rows(workbook, name)
        if _header_row(rows, ("name", "th1", "th2", "lab")) is not None:
            candidates.append((_sheet_date(rows), order, name))
    return max(candidates)[2] if candidates else None


def is_department_load_workbook(workbook: Any) -> bool:
    return find_sheet(workbook, "load") is not None


def _columns(header: Sequence[Any]) -> Dict[str, List[int]]:
    result: Dict[str, List[int]] = {}
    for col, value in enumerate(header):
        cell = text_of(value).lower()
        if cell:
            result.setdefault(cell, []).append(col)
    return result


def _first(columns: Dict[str, List[int]], *names: str) -> Optional[int]:
    for name in names:
        for key, cols in columns.items():
            if key == name or key.startswith(name):
                return cols[0]
    return None


def _cell(row: Sequence[Any], col: Optional[int]) -> Any:
    return row[col] if col is not None and col < len(row) else None


# ------------------------------------------------------------------ sheet 1

def read_faculty(workbook: Any) -> List[FacultyEntry]:
    name = find_sheet(workbook, "faculty")
    if not name:
        return []
    rows = _rows(workbook, name)
    header = _header_row(rows, ("name",))
    if header is None:
        return []
    columns = _columns(rows[header])
    name_col = _first(columns, "name")
    initials_col = _first(columns, "initials", "short name", "code")
    if initials_col is None:
        initials_col = name_col + 1  # the college's own sheet leaves the initials header blank
    hours_col = _first(columns, "max hours", "max. hours", "max weekly")
    faculty: List[FacultyEntry] = []
    for row in rows[header + 1:]:
        person = text_of(_cell(row, name_col))
        initials = text_of(_cell(row, initials_col))
        if not person:
            if faculty and not text_of(_cell(row, 0)):
                break
            continue
        if not initials or not re.fullmatch(r"[A-Za-z]+", initials):
            continue
        hours = as_int(_cell(row, hours_col)) if hours_col is not None else 0
        faculty.append(FacultyEntry(person, initials, hours or None))
    return faculty


# ------------------------------------------------------------------ sheet 2

def read_choices(workbook: Any) -> List[ChoiceEntry]:
    name = find_sheet(workbook, "choice")
    if not name:
        return []
    rows = _rows(workbook, name)
    entries: List[ChoiceEntry] = []
    index = 0
    # The college's sheet repeats the table for UG and PG; read every one.
    while index < len(rows):
        header = _header_row(rows[index:], ("name", "subject choice"))
        if header is None:
            break
        header += index
        columns = _columns(rows[header])
        name_col = _first(columns, "name")
        initials_col = _first(columns, "initials")
        choice_cols = sorted(c for key, cols in columns.items() if key.startswith("subject choice") for c in cols)
        cursor = header + 1
        while cursor < len(rows):
            row = rows[cursor]
            person = text_of(_cell(row, name_col))
            if not person:
                if any(text_of(v) for v in row):
                    break  # the next block's heading
                cursor += 1
                continue
            if _header_row([row], ("name", "subject choice")) is not None:
                break
            choices = [text_of(_cell(row, c)) for c in choice_cols]
            entries.append(ChoiceEntry(person, text_of(_cell(row, initials_col)), [c for c in choices if c]))
            cursor += 1
        index = cursor
    return entries


# ------------------------------------------------------------------ sheet 3

def _year_label(class_text: str) -> Optional[str]:
    """"B.Tech. II" -> "II", "M.Tech. I" -> "PG I", "II A" -> "II A"; None for
    classes that aren't ours to schedule (Ph.D., IP)."""
    clean = class_text.strip()
    if not clean:
        return None
    match = re.search(rf"\b({ROMAN})\b(?:\s+([A-Z]|RR)\b)?\s*$", clean)
    if not match:
        return None
    label = match.group(1) + (f" {match.group(2)}" if match.group(2) else "")
    if re.search(r"m\.?\s*tech|\bpg\b", clean, re.IGNORECASE):
        return f"PG {label}"
    if re.match(r"^\s*(b\.?\s*tech|be\b|btech)", clean, re.IGNORECASE) or re.fullmatch(rf"{ROMAN}(?:\s+[A-Z]|\s+RR)?", clean):
        return label
    if re.match(r"^PG\b", clean):
        return clean
    return label if not re.search(r"p\.?\s*h\.?\s*d", clean, re.IGNORECASE) else None


def _code_and_section(code_raw: str) -> Tuple[str, str]:
    section = ""
    if re.search(r"(?:^|[\s_/-])RR\b", code_raw.upper()):
        section = "RR"
    else:
        match = re.search(r":\s*([A-Z])\b", code_raw)
        if match:
            section = match.group(1)
    return code_raw, section


def read_load(workbook: Any) -> Tuple[List[LoadEntry], List[str]]:
    name = find_sheet(workbook, "load")
    if not name:
        return [], []
    rows = _rows(workbook, name)
    header = _header_row(rows, ("subject code", "subject nomenclature"))
    if header is None:
        return [], [f"{name}: could not find the Subject Code / Subject Nomenclature header."]
    # The periods columns sit under two or three stacked header rows.
    block = rows[header: header + 4]
    columns = _columns(rows[header])
    class_col = _first(columns, "class")
    section_col = _first(columns, "section")
    code_col = _first(columns, "subject code")
    name_col = _first(columns, "subject nomenclature")
    enrolled_col = _first(columns, "actual no", "no. of students", "students")

    theory_col = None
    period_cols: List[int] = []
    for row in block:
        for col, value in enumerate(row):
            cell = text_of(value).lower()
            if cell == "theory" and theory_col is None:
                theory_col = col
            if cell.startswith("no. of periods") or cell.startswith("no of periods"):
                period_cols.append(col)
    period_cols = sorted(set(period_cols))
    if theory_col is None and period_cols:
        theory_col = period_cols[0]
        period_cols = period_cols[1:]
    # Theory has a single "No. of periods" in the template, none in the
    # college's sheet: when three period columns turn up, the first is theory.
    if len(period_cols) >= 3:
        theory_col, period_cols = period_cols[0], period_cols[1:]
    if theory_col is None or len(period_cols) < 2:
        return [], [f"{name}: the Theory, Tutorial and Practical period columns were not found."]
    tut_col, prac_col = period_cols[0], period_cols[1]

    entries: List[LoadEntry] = []
    warnings: List[str] = []
    current_class: Optional[str] = None
    class_skipped = False
    class_enrolled: Optional[int] = None
    first_data = header + 1  # the stacked sub-header rows have no code or name, so they fall through
    for offset, row in enumerate(rows[first_data:], start=first_data + 1):
        class_text = text_of(_cell(row, class_col))
        code_raw = text_of(_cell(row, code_col))
        subject = text_of(_cell(row, name_col))
        if not code_raw and not subject:
            continue
        if class_text:
            current_class = _year_label(class_text)
            class_skipped = current_class is None
            class_enrolled = as_int(_cell(row, enrolled_col)) or None
            if class_skipped:
                warnings.append(f"Skipped class '{class_text}' - not a class of this department's timetable.")
        elif text_of(_cell(row, 0)) and not class_text:
            current_class, class_skipped = None, True  # a numbered block with no class
        if current_class is None or class_skipped:
            continue
        _, section = _code_and_section(code_raw)
        section = text_of(_cell(row, section_col)).upper() or section
        own_enrolled = as_int(_cell(row, enrolled_col)) or None if not class_text else None
        entries.append(LoadEntry(
            year_label=current_class, section=section, code_raw=code_raw, name=subject,
            theory=as_int(_cell(row, theory_col)),
            tutorial=as_int(_cell(row, tut_col)),
            tutorial_batches=as_int(_cell(row, tut_col + 1)),
            tutorial_faculty=max(1, as_int(_cell(row, tut_col + 2))),
            practical=as_int(_cell(row, prac_col)),
            practical_batches=as_int(_cell(row, prac_col + 1)),
            practical_faculty=max(1, as_int(_cell(row, prac_col + 2))),
            enrolled=own_enrolled, class_enrolled=class_enrolled, row_number=offset,
        ))
    return entries, warnings


# ------------------------------------------------------------------ sheet 4

def parse_allocation_cell(value: Any, kind: str, secondary: bool = False) -> List[AllocationItem]:
    """"CO24404(2),\\nCO71455(4)" -> two items; "CO24553(3)" -> one; "-" -> none.
    A trailing "(Elective)" note and "(CS-1)" style tags are ignored."""
    items: List[AllocationItem] = []
    raw = str(value) if value is not None else ""
    for part in re.split(r"[,\n;]+", raw):
        part = part.strip()
        if not part or part == "-":
            continue
        part = re.sub(r"\((?:elective|[A-Za-z][^()]*)\)", " ", part, flags=re.IGNORECASE).strip()
        match = re.search(r"^(.*?)\(\s*(\d+)\s*(?:\+\s*(\d+))?\s*\)\s*$", part)
        if not match or not match.group(1).strip():
            continue
        items.append(AllocationItem(
            label=match.group(1).strip(), hours=int(match.group(2)) + int(match.group(3) or 0),
            kind=kind, secondary=secondary,
        ))
    return items


def read_allocation(workbook: Any) -> Tuple[List[AllocationEntry], str]:
    name = find_allocation_sheet(workbook)
    if not name:
        return [], ""
    rows = _rows(workbook, name)
    header = _header_row(rows, ("name", "th1"))
    if header is None:
        return [], name
    head = rows[header]
    columns = _columns(head)
    name_col = _first(columns, "name")
    initials_col = _first(columns, "initials")
    kind_cols: List[Tuple[int, str, bool]] = []
    for col, value in enumerate(head):
        cell = text_of(value).lower()
        secondary = "secondary" in cell
        if cell.startswith("th"):
            kind_cols.append((col, "theory", False))
        elif cell.startswith("tut"):
            kind_cols.append((col, "tutorial", secondary))
        elif cell.startswith("lab"):
            kind_cols.append((col, "lab", secondary))
    count_cols = {col: col - 1 for col, value in enumerate(head)
                  if text_of(value).lower().startswith("number of students") and col > 0}
    entries: List[AllocationEntry] = []
    for row in rows[header + 1:]:
        person = text_of(_cell(row, name_col))
        if not person:
            continue
        entry = AllocationEntry(person, text_of(_cell(row, initials_col)))
        for col, kind, secondary in kind_cols:
            entry.items.extend(parse_allocation_cell(_cell(row, col), kind, secondary))
        entries.append(entry)
    return entries, name


# ------------------------------------------------------------------ sheet 5

def read_first_year(workbook: Any) -> List[FirstYearEntry]:
    name = find_sheet(workbook, "first_year")
    if not name:
        return []
    rows = _rows(workbook, name)
    header = _header_row(rows, ("name", "th1"))
    if header is None:
        return []
    columns = _columns(rows[header])
    name_col = _first(columns, "name")
    initials_col = _first(columns, "initials")
    total_col = _first(columns, "total")
    load_cols = [c for key, cols in columns.items() if key.startswith(("th", "tut", "lab")) for c in cols]
    entries: List[FirstYearEntry] = []
    for row in rows[header + 1:]:
        person = text_of(_cell(row, name_col))
        if not person or person.lower().startswith(("total", "to,", "head", "copy")):
            continue
        hours = 0
        for col in load_cols:
            for match in HOURS_IN_BRACKETS.finditer(text_of(_cell(row, col))):
                hours += int(match.group(1)) + int(match.group(2) or 0)
        if not hours:
            hours = as_int(_cell(row, total_col))
        entries.append(FirstYearEntry(person, text_of(_cell(row, initials_col)), hours))
    return entries


# ------------------------------------------------------------------ sheet 6

def _offered(value: str) -> str:
    lowered = value.strip().lower()
    if "nptel" in lowered or "mooc" in lowered or "swayam" in lowered:
        return "nptel"
    if lowered in {"", "-", "no", "not offered", "x", "n/a", "na"}:
        return "none"
    return "offline"


def read_electives(workbook: Any) -> List[ElectiveOption]:
    name = find_sheet(workbook, "elective")
    if not name:
        return []
    rows = _rows(workbook, name)
    header = _header_row(rows, ("subjects",))
    if header is None:
        return []
    columns = _columns(rows[header])
    label_col = _first(columns, "elective no", "elective")
    class_col = _first(columns, "class")
    section_col = _first(columns, "section")
    code_col = _first(columns, "subject code", "code")
    subject_col = _first(columns, "subjects")
    offered_col = _first(columns, "offered")
    faculty_col = _first(columns, "faculty")
    options: List[ElectiveOption] = []
    roman, credits, year, section = None, None, None, None
    for row in rows[header + 1:]:
        label = text_of(_cell(row, label_col))
        match = ELECTIVE_WORD.search(label)
        if match:
            roman = match.group(1).upper()
            credit_match = CREDITS.search(label)
            credits = int(credit_match.group(1)) if credit_match else None
        if class_col is not None and text_of(_cell(row, class_col)):
            year = _year_label(text_of(_cell(row, class_col))) or text_of(_cell(row, class_col))
            section = None
        if section_col is not None and text_of(_cell(row, section_col)):
            section = text_of(_cell(row, section_col)).upper()
        subject = text_of(_cell(row, subject_col))
        if not roman or not subject:
            continue
        faculty = [t for t in re.split(r"[,;/ ]+", text_of(_cell(row, faculty_col))) if re.fullmatch(r"[A-Za-z]+", t)]
        options.append(ElectiveOption(
            roman=roman, credits=credits, name=subject, code=text_of(_cell(row, code_col)),
            offered=_offered(text_of(_cell(row, offered_col))), year_label=year, section=section, faculty=faculty,
        ))
    return options


# ------------------------------------------------------------------ all

def read_department_load(workbook: Any) -> DepartmentLoadSheets:
    sheets = DepartmentLoadSheets()
    for role in SHEET_ALIASES:
        found = find_allocation_sheet(workbook) if role == "allocation" else find_sheet(workbook, role)
        if found:
            sheets.found[role] = found
    sheets.faculty = read_faculty(workbook)
    sheets.choices = read_choices(workbook)
    sheets.load, load_warnings = read_load(workbook)
    sheets.warnings.extend(load_warnings)
    sheets.allocation, sheets.allocation_sheet = read_allocation(workbook)
    sheets.first_year = read_first_year(workbook)
    sheets.electives = read_electives(workbook)
    return sheets
