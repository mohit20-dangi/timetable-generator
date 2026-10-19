"""Opt-in: runs the REAL PaddleOCR worker on a real scanned PDF through the
HTTP API. Skipped unless both are provided, because it needs the Python 3.11
OCR environment and takes minutes:

    set OCR_PYTHON=C:\\path\\to\\ocr-venv\\Scripts\\python.exe
    set FIRST_YEAR_SAMPLE_PDF=C:\\path\\to\\III_yr_updated_TT.pdf
    pytest tests/integration/test_first_year_real_ocr.py
"""
import os
from pathlib import Path

import pytest

from tests.integration.test_first_year_import_api import _department, _headers, _preview

PDF = os.environ.get("FIRST_YEAR_SAMPLE_PDF", "")
OCR = os.environ.get("OCR_PYTHON", "")

pytestmark = pytest.mark.skipif(
    not (PDF and OCR and Path(PDF).exists() and Path(OCR).exists()),
    reason="set OCR_PYTHON and FIRST_YEAR_SAMPLE_PDF to run the real-OCR test",
)


def test_real_pdf_through_the_real_worker(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "OCR_PYTHON", OCR)
    h = _headers(client)
    _department(client, h, teachers=("KAM", "RKD", "AP", "AS", "CHN", "RV", "TD", "HM", "VT"))

    response = client.post(
        "/api/first-year-import/preview", data={"department_id": "cse"}, headers=h,
        files={"file": ("sample.pdf", Path(PDF).read_bytes(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["pages"]) == 2 and all(p["cells"] >= 20 for p in body["pages"])
    matched = {(r["page"], r["day"], r["start"], t["teacher_id"]) for r in body["rows"]
               for t in r["teachers"] if t["status"] == "matched"}
    assert (1, "Mon", "11:00", "t_KAM") in matched      # CO34_OS, Tut. Room
    assert (1, "Thu", "10:00", "t_RKD") in matched      # CO34_CN, LT102
    assert (2, "Mon", "12:00", "t_TD") in matched       # CO34_DAA, LT102
