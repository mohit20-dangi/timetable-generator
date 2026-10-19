"""PaddleOCR worker for the first-year timetable import.

Runs as its OWN process under a Python 3.11 interpreter that has
`paddleocr` + `paddlepaddle` + `pymupdf` installed (Paddle does not support
the Python the backend runs on). It must stay standalone: it imports nothing
from `app`, so it can be executed with any interpreter.

    python worker.py <input.pdf> <output.json>

Output JSON: a list with one object per PDF page:
    {"page": 1, "cells": [[x0,y0,x1,y1], ...], "texts": [...], "boxes": [[x0,y0,x1,y1], ...]}
`cells` are the table-cell boxes PP-StructureV3 detects; `texts`/`boxes` are
its OCR lines. All coordinates are in the auto-cropped page image. Turning
these into day/time/teacher is done by the backend
(app/services/first_year_import.py), not here: PP-StructureV3's own table
HTML scrambles merged cells, but its cell boxes are accurate.
"""
import json
import os
import sys

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

RENDER_DPI = 200
CROP_MARGIN = 30


def render_pages(pdf_path):
    import numpy as np
    import pymupdf
    from PIL import Image

    pages = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=RENDER_DPI)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(_crop_to_content(image, np))
    return pages


def _crop_to_content(image, np):
    """Scans of landscape timetables sit in a big blank A4 portrait page;
    cropping to the ink makes the table a much larger share of the pixels."""
    gray = np.asarray(image.convert("L"))
    dark = gray < 130
    rows = np.where(dark.sum(axis=1) >= 3)[0]
    cols = np.where(dark.sum(axis=0) >= 3)[0]
    if rows.size == 0 or cols.size == 0:
        return image
    x0, x1 = max(cols[0] - CROP_MARGIN, 0), min(cols[-1] + CROP_MARGIN, image.width)
    y0, y1 = max(rows[0] - CROP_MARGIN, 0), min(rows[-1] + CROP_MARGIN, image.height)
    return image.crop((x0, y0, x1, y1))


def main(pdf_path, out_path):
    import numpy as np
    from paddleocr import PPStructureV3

    pipeline = PPStructureV3(
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_chart_recognition=False, use_formula_recognition=False, use_seal_recognition=False,
    )
    result = []
    for number, image in enumerate(render_pages(pdf_path), start=1):
        res = list(pipeline.predict(np.asarray(image)))[0]
        data = res.json["res"] if "res" in res.json else res.json
        cells = []
        for table in data.get("table_res_list", []):
            cells.extend([[float(v) for v in box] for box in table.get("cell_box_list", [])])
        ocr = data["overall_ocr_res"]
        result.append({
            "page": number,
            "cells": cells,
            "texts": list(ocr["rec_texts"]),
            "boxes": [[float(v) for v in box] for box in ocr["rec_boxes"]],
        })
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: worker.py <input.pdf> <output.json>")
    main(sys.argv[1], sys.argv[2])
