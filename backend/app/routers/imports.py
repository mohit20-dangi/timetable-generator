from datetime import datetime, time
import csv
import io
import json
import zipfile
from typing import Any, Dict, Iterable, List, Mapping, Type

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.db import get_db
from app.models import (
    AcademicYear,
    LabBatch,
    Prerequisite,
    Room,
    Section,
    SectionSubject,
    Subject,
    Teacher,
    TeacherSubject,
    TimeSlot,
    User,
)


router = APIRouter(prefix="/api/import", tags=["Bulk Import"])


SHEET_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "AcademicYears": {
        "model": AcademicYear,
        "required": {"id", "name"},
        "columns": ["id", "name", "num_sections", "lunch_start", "lunch_end"],
        "json": set(),
        "int": {"num_sections"},
        "time": {"lunch_start", "lunch_end"},
    },
    "Sections": {
        "model": Section,
        "required": {"id", "year_id", "name"},
        "columns": ["id", "year_id", "name", "strength"],
        "json": set(),
        "int": {"strength"},
    },
    "Subjects": {
        "model": Subject,
        "required": {"id", "name", "type"},
        "columns": [
            "id", "name", "type", "weekly_hours", "needs_continuous_block",
            "block_size", "requires_room_type", "requires_equipment",
        ],
        "json": {"requires_equipment"},
        "int": {"weekly_hours", "block_size"},
        "bool": {"needs_continuous_block"},
    },
    "Teachers": {
        "model": Teacher,
        "required": {"id", "name"},
        "columns": [
            "id", "name", "department", "max_continuous_classes", "max_daily_classes",
            "availability", "preferred_slots", "is_guest_from_other_dept",
        ],
        "json": {"availability", "preferred_slots"},
        "int": {"max_continuous_classes", "max_daily_classes"},
        "bool": {"is_guest_from_other_dept"},
    },
    "Rooms": {
        "model": Room,
        "required": {"id", "name", "type"},
        "columns": [
            "id", "name", "type", "capacity", "equipment",
            "shared_with_departments", "availability",
        ],
        "json": {"equipment", "shared_with_departments", "availability"},
        "int": {"capacity"},
    },
    "SectionSubjects": {
        "model": SectionSubject,
        "required": {"section_id", "subject_id"},
        "columns": ["section_id", "subject_id", "is_elective", "elective_group_id"],
        "json": set(),
        "bool": {"is_elective"},
    },
    "TeacherSubjects": {
        "model": TeacherSubject,
        "required": {"teacher_id", "subject_id"},
        "columns": ["teacher_id", "subject_id"],
        "json": set(),
    },
    "LabBatches": {
        "model": LabBatch,
        "required": {"id", "section_id", "batch_name"},
        "columns": ["id", "section_id", "batch_name", "strength"],
        "json": set(),
        "int": {"strength"},
    },
    "Prerequisites": {
        "model": Prerequisite,
        "required": {"subject_id", "requires_subject_id"},
        "columns": ["subject_id", "requires_subject_id"],
        "json": set(),
    },
    "TimeSlots": {
        "model": TimeSlot,
        "required": {"id", "day", "period_index", "start_time", "end_time"},
        "columns": ["id", "day", "period_index", "start_time", "end_time"],
        "json": set(),
        "int": {"period_index"},
        "time": {"start_time", "end_time"},
    },
}

RELATION_KEYS = {
    "SectionSubjects": (SectionSubject, ("section_id", "subject_id")),
    "TeacherSubjects": (TeacherSubject, ("teacher_id", "subject_id")),
    "Prerequisites": (Prerequisite, ("subject_id", "requires_subject_id")),
}


def _normalise_header(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _cell_value(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
    return value


def _parse_time(value: Any, sheet: str, row_number: int, column: str) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    try:
        parsed = datetime.strptime(str(value).strip(), "%H:%M")
        return parsed.time()
    except ValueError as exc:
        raise ValueError(f"{sheet} row {row_number}: {column} must be HH:MM") from exc


def _parse_json(value: Any, sheet: str, row_number: int, column: str) -> Any:
    if value in (None, ""):
        return []
    if isinstance(value, (list, dict)):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{sheet} row {row_number}: {column} must contain valid JSON") from exc
    if not isinstance(parsed, (list, dict)):
        raise ValueError(f"{sheet} row {row_number}: {column} must be a JSON list or object")
    return parsed


def _parse_bool(value: Any, sheet: str, row_number: int, column: str) -> bool:
    if isinstance(value, bool):
        return value
    normalised = str(value or "").strip().lower()
    if normalised in {"true", "1", "yes", "y"}:
        return True
    if normalised in {"false", "0", "no", "n", ""}:
        return False
    raise ValueError(f"{sheet} row {row_number}: {column} must be true or false")


def _parse_int(value: Any, sheet: str, row_number: int, column: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{sheet} row {row_number}: {column} must be an integer") from exc


def _read_rows(workbook: Any) -> Dict[str, List[Dict[str, Any]]]:
    parsed: Dict[str, List[Dict[str, Any]]] = {}
    for sheet_name, definition in SHEET_DEFINITIONS.items():
        if sheet_name not in workbook.sheetnames:
            continue
        sheet = workbook[sheet_name]
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue
        headers = [_normalise_header(value) for value in rows[0]]
        present = {header for header in headers if header}
        missing = definition["required"] - present
        if missing:
            raise ValueError(f"{sheet_name}: missing required columns: {', '.join(sorted(missing))}")
        if len(headers) != len(set(headers)):
            raise ValueError(f"{sheet_name}: duplicate column headers are not allowed")

        sheet_rows: List[Dict[str, Any]] = []
        for row_number, values in enumerate(rows[1:], start=2):
            if not any(value not in (None, "") for value in values):
                continue
            raw = {headers[index]: _cell_value(values[index]) for index in range(len(headers)) if headers[index]}
            item: Dict[str, Any] = {}
            for column in definition["columns"]:
                if column not in raw:
                    continue
                value = raw[column]
                if column in definition.get("json", set()):
                    value = _parse_json(value, sheet_name, row_number, column)
                elif column in definition.get("time", set()):
                    value = _parse_time(value, sheet_name, row_number, column)
                elif column in definition.get("bool", set()):
                    value = _parse_bool(value, sheet_name, row_number, column)
                elif column in definition.get("int", set()):
                    value = _parse_int(value, sheet_name, row_number, column)
                if column == "id" or column.endswith("_id"):
                    value = str(value).strip() if value not in (None, "") else value
                item[column] = value
            for required in definition["required"]:
                if item.get(required) in (None, ""):
                    raise ValueError(f"{sheet_name} row {row_number}: {required} is required")
            sheet_rows.append(item)
        key_columns = ("id",) if "id" in definition["required"] else sorted(definition["required"])
        seen_keys = set()
        for row_number, item in enumerate(sheet_rows, start=2):
            key = tuple(str(item[column]) for column in key_columns)
            if key in seen_keys:
                raise ValueError(
                    f"{sheet_name} row {row_number}: duplicate key ({', '.join(key)})"
                )
            seen_keys.add(key)
        parsed[sheet_name] = sheet_rows
    return parsed


def _validate_references(rows: Mapping[str, List[Dict[str, Any]]], db: Session) -> None:
    ids: Dict[Type[Any], set[str]] = {}
    for model in (AcademicYear, Section, Subject, Teacher, Room, LabBatch, TimeSlot):
        existing = {str(item[0]) for item in db.query(model.id).all()}
        sheet_name = next((name for name, definition in SHEET_DEFINITIONS.items() if definition["model"] is model), "")
        existing.update(str(row["id"]) for row in rows.get(sheet_name, []) if row.get("id") is not None)
        ids[model] = existing

    references = {
        "Sections": (("year_id", AcademicYear, "academic year"),),
        "SectionSubjects": (("section_id", Section, "section"), ("subject_id", Subject, "subject")),
        "TeacherSubjects": (("teacher_id", Teacher, "teacher"), ("subject_id", Subject, "subject")),
        "LabBatches": (("section_id", Section, "section"),),
        "Prerequisites": (("subject_id", Subject, "subject"), ("requires_subject_id", Subject, "subject")),
    }
    errors: List[str] = []
    for sheet_name, fields in references.items():
        for row_number, row in enumerate(rows.get(sheet_name, []), start=2):
            for field, model, label in fields:
                if str(row[field]) not in ids[model]:
                    errors.append(f"{sheet_name} row {row_number}: unknown {label} '{row[field]}'")
    if errors:
        raise ValueError("; ".join(errors[:20]) + ("; ..." if len(errors) > 20 else ""))


def _upsert_entities(rows: Mapping[str, List[Dict[str, Any]]], db: Session) -> Dict[str, int]:
    counts = {"created": 0, "updated": 0, "relations_created": 0}
    entity_sheets = [name for name in SHEET_DEFINITIONS if name not in RELATION_KEYS]
    for sheet_name in entity_sheets:
        definition = SHEET_DEFINITIONS[sheet_name]
        model = definition["model"]
        for data in rows.get(sheet_name, []):
            record = db.get(model, str(data["id"]))
            if record is None:
                record = model(**data)
                db.add(record)
                counts["created"] += 1
            else:
                for key, value in data.items():
                    setattr(record, key, value)
                counts["updated"] += 1
    db.flush()

    for sheet_name, (model, key_fields) in RELATION_KEYS.items():
        for data in rows.get(sheet_name, []):
            filters = {field: data[field] for field in key_fields}
            record = db.query(model).filter_by(**filters).first()
            if record is None:
                db.add(model(**data))
                counts["relations_created"] += 1
            else:
                for key, value in data.items():
                    setattr(record, key, value)
    return counts


def _parse_and_validate_workbook(content: bytes, db: Session) -> Dict[str, List[Dict[str, Any]]]:
    workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    rows = _read_rows(workbook)
    if not rows:
        raise ValueError("The workbook does not contain any supported data sheets")
    _validate_references(rows, db)
    return rows


@router.post("/excel/preview")
async def preview_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Parse and validate an upload without changing the database."""
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Upload an .xlsx or .xlsm workbook")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded workbook is empty")
    try:
        rows = _parse_and_validate_workbook(content, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Workbook preview failed: {exc}") from exc
    return {
        "message": "Workbook validated. No data has been imported.",
        "sheets": {name: len(sheet_rows) for name, sheet_rows in rows.items()},
        "total_rows": sum(len(sheet_rows) for sheet_rows in rows.values()),
    }


@router.post("/csv")
async def import_csv_bundle(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Import either one named CSV sheet or a ZIP bundle of named CSV sheets."""
    filename = (file.filename or "").lower()
    if not filename.endswith((".csv", ".zip")):
        raise HTTPException(status_code=400, detail="Upload a .csv file or a .zip bundle of CSV sheets")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded CSV file is empty")
    workbook = Workbook()
    workbook.remove(workbook.active)
    try:
        sources = {}
        if filename.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                for member in archive.namelist():
                    if member.lower().endswith(".csv") and not member.endswith("/"):
                        sources[member.rsplit("/", 1)[-1]] = archive.read(member).decode("utf-8-sig")
        else:
            sources[file.filename or "data.csv"] = content.decode("utf-8-sig")
        supported = {f"{name.lower()}.csv": name for name in SHEET_DEFINITIONS}
        for source_name, source_text in sources.items():
            sheet_name = supported.get(source_name.lower())
            if not sheet_name:
                continue
            sheet = workbook.create_sheet(sheet_name)
            for row in csv.reader(io.StringIO(source_text)):
                sheet.append(row)
        if not workbook.sheetnames:
            raise ValueError("CSV names must match supported sheets, for example Subjects.csv or TimeSlots.csv")
        rows = _read_rows(workbook)
        _validate_references(rows, db)
        counts = _upsert_entities(rows, db)
        db.commit()
    except (ValueError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"CSV import failed: {exc}") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"CSV import failed: {exc}") from exc
    return {
        "message": "CSV data imported successfully",
        "sheets": {name: len(sheet_rows) for name, sheet_rows in rows.items()},
        **counts,
    }


@router.post("/excel")
async def import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Upload an .xlsx or .xlsm workbook")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded workbook is empty")
    try:
        rows = _parse_and_validate_workbook(content, db)
        counts = _upsert_entities(rows, db)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"Workbook import failed: {exc}") from exc

    return {
        "message": "Workbook imported successfully",
        "sheets": {name: len(sheet_rows) for name, sheet_rows in rows.items()},
        **counts,
    }


@router.get("/excel-template")
def download_excel_template(_admin: User = Depends(require_admin)):
    workbook = Workbook()
    instructions = workbook.active
    instructions.title = "Instructions"
    instructions.append(["Bulk import workbook", "Fill one or more supported sheets and upload the .xlsx file."])
    instructions.append(["JSON fields", "Use JSON, for example [\"lab\", \"projector\"] or [{\"day\": \"Mon\"}]."])
    instructions.append(["Time fields", "Use HH:MM values, for example 09:00."])
    for sheet_name, definition in SHEET_DEFINITIONS.items():
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(definition["columns"])
        sheet.freeze_panes = "A2"
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=timetable-import-template.xlsx"},
    )
