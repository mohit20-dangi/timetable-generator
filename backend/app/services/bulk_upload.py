"""Shared CSV/Excel bulk-upload helpers used by every entity router's
`POST .../bulk` endpoint. Each row is validated independently so one bad row
doesn't fail the whole batch - the response reports created ids plus a
per-row error list.
"""
import io
from typing import Any, Callable, Dict, List

import pandas as pd
from pymongo.errors import DuplicateKeyError


def parse_upload_file(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        df = pd.read_csv(io.BytesIO(file_bytes))
    df = df.where(pd.notnull(df), None)
    return df.to_dict(orient="records")


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


def csv_template(headers: List[str], example_row: List[str]) -> str:
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerow(example_row)
    return buf.getvalue()
