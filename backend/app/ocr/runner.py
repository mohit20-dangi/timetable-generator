"""Runs the PaddleOCR worker (app/ocr/worker.py) in its own Python 3.11
process. Kept separate from the backend interpreter because Paddle does not
support the Python the backend runs on."""
import json
import subprocess
import tempfile
from pathlib import Path
from typing import List

from app.core.config import settings

WORKER = Path(__file__).with_name("worker.py")


class OcrUnavailable(Exception):
    """OCR is not configured on this server (503)."""


class OcrFailed(Exception):
    """The worker ran but did not produce a result (502)."""


def run_ocr(pdf_bytes: bytes) -> List[dict]:
    if not settings.OCR_PYTHON:
        raise OcrUnavailable(
            "First-year PDF import needs OCR. Set OCR_PYTHON in .env to a Python 3.11 "
            "interpreter that has paddleocr, paddlepaddle and pymupdf installed.")
    if not Path(settings.OCR_PYTHON).exists():
        raise OcrUnavailable(f"OCR_PYTHON does not exist: {settings.OCR_PYTHON}")
    with tempfile.TemporaryDirectory() as workdir:
        source = Path(workdir) / "input.pdf"
        output = Path(workdir) / "output.json"
        source.write_bytes(pdf_bytes)
        try:
            completed = subprocess.run(
                [settings.OCR_PYTHON, str(WORKER), str(source), str(output)],
                capture_output=True, text=True, timeout=settings.OCR_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise OcrFailed(f"OCR took longer than {settings.OCR_TIMEOUT_SECONDS}s and was stopped.")
        if completed.returncode != 0 or not output.exists():
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-3:]
            raise OcrFailed("OCR worker failed: " + " | ".join(tail))
        return json.loads(output.read_text(encoding="utf-8"))
