"""First-year central timetable import: geometry -> cells -> teacher/room
matching -> time slots. Uses the REAL PaddleOCR output for two scanned pages
(tests/fixtures/first_year_pages.json) so the tests need no OCR installed, and
a hand-transcribed reference (first_year_reference.json) as a regression guard
on reading accuracy.
"""
import json
from datetime import time
from pathlib import Path

from app.services.first_year_import import (
    RoomRef, SlotRef, TeacherRef, build_preview, extract_page, normalize_code,
    normalize_subject, parse_cell_text, slots_for_span,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PAGES = json.loads((FIXTURES / "first_year_pages.json").read_text(encoding="utf-8"))
REFERENCE = json.loads((FIXTURES / "first_year_reference.json").read_text(encoding="utf-8"))["cells"]

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
HOURLY_SLOTS = [SlotRef(d, h - 7, time(h), time(h + 1)) for d in DAYS for h in range(8, 18)]
ROOMS = [RoomRef("r_lt102", "LT102"), RoomRef("r_tut", "Tut. Room"), RoomRef("r_gcl", "GCL"), RoomRef("r_ai", "AI Lab")]


def _teachers(codes):
    return [TeacherRef(id=f"t_{c}", name=f"Teacher {c}", initials=c) for c in codes]


ALL_CODES = sorted({t for c in REFERENCE for t in c["teachers"]})


def _preview(teacher_codes=ALL_CODES, rooms=ROOMS):
    return build_preview(PAGES, _teachers(teacher_codes), rooms, HOURLY_SLOTS)


def _hits(preview):
    """{(page, day, hour, code)} for every confidently matched teacher."""
    return {
        (row.page, day, period + 7, hit.code)
        for row in preview.rows for hit in row.teachers if hit.status == "matched"
        for day, period in row.periods
    }


# ---- small pieces ---------------------------------------------------------
def test_normalize_code_drops_guest_faculty_markers():
    assert normalize_code('ANS"') == "ANS"
    assert normalize_code("PM'") == "PM"
    assert normalize_code("sr″") == "SR"
    assert normalize_code("") == ""


def test_subject_codes_are_normalised_whatever_the_ocr_did_to_the_underscore():
    assert [normalize_subject(x) for x in ("CO34OS", "CO34 OS", "CO34__OS", "co34_os", "CO34_OS")] == ["CO34_OS"] * 5
    assert normalize_subject("CO_IoT") == "CO_IOT"
    assert normalize_subject("HUM3401") == "HUM3401"


def test_every_subject_read_from_the_sample_pages_has_the_canonical_shape():
    subjects = {c.subject for p in PAGES for c in extract_page(p, "x").cells}
    assert subjects == {"CO34_IS", "CO34_OS", "CO34_CN", "CO34_INTER", "CO34_MINI", "CO34_TOC", "HUM3401",
                        "CO34_DAA", "CO34_DBMS", "CO34_IOT", "CO34_ML", "CO_IOT"}


def test_two_hour_lab_occupies_two_periods_and_does_not_spill_over():
    hit = slots_for_span(HOURLY_SLOTS, "Mon", "14:00", "16:00")
    assert [s.period_index for s in hit] == [7, 8]


def test_slot_mapping_tolerates_bell_schedules_that_are_not_on_the_hour():
    bells = [SlotRef("Tue", 1, time(9, 0), time(9, 50)), SlotRef("Tue", 2, time(9, 50), time(10, 40)),
             SlotRef("Tue", 3, time(10, 40), time(11, 30))]
    # a 10:00-11:00 cell covers most of period 2 and part of period 3, never period 1
    assert [s.period_index for s in slots_for_span(bells, "Tue", "10:00", "11:00")] == [2, 3]
    assert [s.period_index for s in slots_for_span(bells, "Tue", "09:00", "09:50")] == [1]
    assert slots_for_span(bells, "Wed", "10:00", "11:00") == []


def test_cell_text_splits_faculty_codes_from_room():
    recognised = {"RKD", "AS", "ANS", "PM"}
    parsed = parse_cell_text(["CO34_CN", "A1,A2", "RKD, AS,", 'ANS",PM\'', "GCL"], recognised)
    assert parsed.codes == ["RKD", "AS", "ANS", "PM"]
    assert parsed.room_text == "GCL"


def test_room_printed_on_the_same_line_as_the_last_codes():
    parsed = parse_cell_text(["CO34_MINI", "A1", "DAM, NM,AS AVLC"], {"DAM", "NM", "AS"})
    assert parsed.codes == ["DAM", "NM", "AS"]
    assert parsed.room_text == "AVLC"


def test_code_with_trailing_scan_noise_is_still_read():
    parsed = parse_cell_text(["CO34_IS", "RV$", "Tut. Room"], {"RV"})
    assert parsed.codes == ["RV"]
    assert parsed.damaged == []


def test_half_read_code_is_reported_not_dropped():
    parsed = parse_cell_text(["CO34_TOC", "A_$", "LT102"], {"AP", "AS"})
    assert parsed.codes == []
    assert parsed.damaged == ["A_$"]


# ---- reading the real scanned pages ---------------------------------------
def test_each_page_is_read_as_a_timetable_with_its_faculty_legend():
    results = [extract_page(p, f"Page {i}") for i, p in enumerate(PAGES, 1)]
    assert all(r.warnings == [] for r in results)
    assert [len(r.cells) for r in results] == [22, 22]
    assert results[0].legend["KAM"] == "Ms. Karishma"


def test_single_hour_and_lab_cells_land_on_the_right_day_and_hours():
    cells = {(c.day, c.start, c.subject, tuple(c.lines[:1])): c for c in extract_page(PAGES[0], "A").cells}
    kam = [c for c in extract_page(PAGES[0], "A").cells if c.subject == "CO34_OS" and c.day == "Mon" and c.start == "11:00"]
    assert len(kam) == 1 and kam[0].end == "12:00" and "KAM" in kam[0].text and "Tut. Room" in kam[0].text
    assert cells  # page produced cells


def test_lab_sub_columns_are_assigned_to_monday_and_tuesday_correctly():
    """Four lab cells sit side by side under Monday+Tuesday; the day must come
    from pixel position, not from the order the cells are listed."""
    labs = [c for c in extract_page(PAGES[0], "A").cells if c.start == "14:00" and c.end == "16:00" and c.day in ("Mon", "Tue")]
    by_day = {d: sorted(c.subject + ("/A3" if "A3" in c.text else "/A1A2") for c in labs if c.day == d) for d in ("Mon", "Tue")}
    assert by_day == {"Mon": ["CO34_CN/A1A2", "CO34_OS/A3"], "Tue": ["CO34_CN/A3", "CO34_OS/A1A2"]}


def test_cell_the_detector_cut_in_two_is_glued_back_together():
    """Wed 16-18 Mini Project A2: subject box and faculty box were detected
    separately; its teachers must still end up on the cell."""
    cells = [c for c in extract_page(PAGES[0], "A").cells if c.day == "Wed" and c.start == "16:00"]
    a2 = [c for c in cells if "A2" in c.text]
    assert len(a2) == 1
    assert all(code in a2[0].text for code in ("AP", "CHN", "KAM"))


def test_teacher_locks_match_the_hand_transcribed_timetable():
    """Regression guard on reading accuracy. Recall must stay high AND nothing
    may be locked that is not in the real timetable (a wrong lock silently
    removes a slot from the solver)."""
    want = {(1 if c["section"].endswith("A") else 2, c["day"], h, t)
            for c in REFERENCE for h in range(int(c["start"][:2]), int(c["end"][:2])) for t in c["teachers"]}
    got = _hits(_preview())
    assert got <= want, sorted(got - want)
    assert len(got) / len(want) >= 0.97, sorted(want - got)


def test_the_unreadable_teacher_text_is_surfaced_not_silently_skipped():
    preview = _preview()
    missed = {(1, "Fri", 10, "AP"), (2, "Thu", 11, "VT")}
    want = {(1 if c["section"].endswith("A") else 2, c["day"], h, t)
            for c in REFERENCE for h in range(int(c["start"][:2]), int(c["end"][:2])) for t in c["teachers"]}
    lost = want - _hits(preview)
    assert lost <= {(p, d, h, t) for p, d, _, t in missed for h in range(10, 14)} | {(1, "Fri", 11, "AP")}
    # every lost slot must be visible to the admin in one of the two lists
    flagged = {(r.page, r.day) for r in preview.rows if any(h.status != "matched" for h in r.teachers)}
    unreadable = {(int(u["page"]), u["day"]) for u in preview.unreadable}
    assert {(p, d) for p, d, _, _ in lost} <= flagged | unreadable


# ---- matching against our own data ----------------------------------------
def test_only_our_teachers_produce_rows_and_other_codes_are_ignored():
    preview = _preview(teacher_codes=["KAM", "RKD"], rooms=[])
    hit_codes = {hit.code for row in preview.rows for hit in row.teachers if hit.status == "matched"}
    assert hit_codes == {"KAM", "RKD"}
    assert all(any(h.teacher_id in ("t_KAM", "t_RKD") for h in row.teachers) for row in preview.rows
               if any(h.status == "matched" for h in row.teachers))
    # RV teaches IS on Tuesday but is not ours: no row for that cell
    assert not any(r.subject == "CO34_IS" and r.day == "Tue" and r.page == 1 for r in preview.rows)


def test_room_is_locked_when_its_name_matches_one_of_ours_even_with_no_teacher_of_ours():
    preview = _preview(teacher_codes=["KAM"], rooms=[RoomRef("r_gcl", "GCL")])
    room_rows = [r for r in preview.rows if r.room_id == "r_gcl"]
    assert room_rows, "GCL lab classes must lock our GCL room"
    assert any(not any(h.status == "matched" for h in r.teachers) for r in room_rows)


def test_shared_initials_are_ambiguous_until_the_legend_name_breaks_the_tie():
    teachers = [TeacherRef("t_a", "Ms. Karishma", "KAM"), TeacherRef("t_b", "Mr. Kamal Verma", "KAM")]
    preview = build_preview(PAGES, teachers, [], HOURLY_SLOTS)
    kam_hits = [h for r in preview.rows for h in r.teachers if h.code == "KAM"]
    assert kam_hits and {h.teacher_id for h in kam_hits if h.status == "matched"} == {"t_a"}

    no_legend = [dict(p, texts=[t for t in p["texts"] if t != "Ms. Karishma"]) for p in PAGES]
    no_legend = [dict(p, boxes=[b for b, t in zip(p["boxes"], PAGES[i]["texts"]) if t != "Ms. Karishma"])
                 for i, p in enumerate(no_legend)]
    preview = build_preview(no_legend, teachers, [], HOURLY_SLOTS)
    ambiguous = [h for r in preview.rows for h in r.teachers if h.code == "KAM" and h.status == "ambiguous"]
    assert ambiguous and {c.teacher_id for c in ambiguous[0].candidates} == {"t_a", "t_b"}


def test_half_read_code_offers_our_teachers_as_candidates():
    preview = _preview(teacher_codes=["AP", "AS", "RV"], rooms=[])
    flagged = [h for r in preview.rows for h in r.teachers if h.status == "unread"]
    assert flagged and {c.initials for c in flagged[0].candidates} >= {"AP", "AS"}


def test_cell_outside_the_configured_bell_schedule_is_reported():
    only_morning = [s for s in HOURLY_SLOTS if s.start < time(12)]
    preview = build_preview(PAGES, _teachers(ALL_CODES), [], only_morning)
    assert any("matches none of the configured time slots" in w for w in preview.warnings)


def test_a_page_with_no_grid_gives_a_warning_not_a_crash():
    blank = {"page": 1, "cells": [], "texts": ["Nothing here"], "boxes": [[0, 0, 10, 10]]}
    preview = build_preview([blank], _teachers(["KAM"]), [], HOURLY_SLOTS)
    assert preview.rows == [] and preview.warnings
