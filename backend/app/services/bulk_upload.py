"""Shared CSV/Excel bulk-upload helpers used by every entity router's
`POST .../bulk` endpoint. Each row is validated independently so one bad row
doesn't fail the whole batch - the response reports created ids plus a
per-row error list.
"""
import io
from typing import Any, Callable, Dict, List

import pandas as pd
from pymongo.errors import DuplicateKeyError


_BLANK_TOKENS = {"nan", "none", "null", "na", "n/a"}


def parse_upload_file(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        df = pd.read_csv(io.BytesIO(file_bytes))
    df = df.where(pd.notnull(df), None)
    rows = df.to_dict(orient="records")
    # A cell that's literally the text "nan"/"None"/"null" (e.g. a sheet exported
    # from another pandas dataframe without proper NA handling) means the same
    # thing as a truly empty cell - treat it as such rather than storing the
    # sentinel string as real data.
    for row in rows:
        for key, value in row.items():
            if isinstance(value, str) and value.strip().lower() in _BLANK_TOKENS:
                row[key] = None
    return rows


def split_list(value: Any) -> List[str]:
    """Cell values for list fields are semicolon-separated, e.g. 'computers; projector'."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if not text:
        return []
    return [v.strip() for v in text.split(";") if v.strip()]


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def parse_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(float(value))


def bulk_create(rows: List[Dict[str, Any]], row_to_doc: Callable[[Dict[str, Any]], Dict[str, Any]], repo) -> Dict[str, Any]:
    created: List[str] = []
    errors: List[Dict[str, Any]] = []

    for i, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            doc = row_to_doc(row)
            if not doc.get("id"):
                raise ValueError("id is required")
            repo.create(doc)
            created.append(doc["id"])
        except DuplicateKeyError:
            errors.append({"row": i, "id": row.get("id"), "error": "ID already exists"})
        except Exception as e:
            errors.append({"row": i, "id": row.get("id"), "error": str(e)})

    return {"created": created, "errors": errors}


def csv_template(headers: List[str], example_rows: List[str] | List[List[str]]) -> str:
    """`example_rows` may be a single row (list of strings) or several rows
    (list of lists) - several rows lets the template demonstrate optional
    fields (e.g. a second row with a prerequisite filled in) without making
    every column look mandatory."""
    import csv
    rows = [example_rows] if example_rows and isinstance(example_rows[0], str) else example_rows
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()
