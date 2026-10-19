"""First-year PDF import end to end over the real HTTP API and database:
upload (OCR stubbed with real captured output) -> review -> apply -> the
locks bind both a "fresh" and a "fit into existing" generation.
"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PAGES = json.loads((FIXTURES / "first_year_pages.json").read_text(encoding="utf-8"))
ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "SUPERADMIN"}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
PDF = ("first_year.pdf", b"%PDF-1.4 stub", "application/pdf")


def _headers(client):
    assert client.post("/api/auth/bootstrap-admin", json=ADMIN).status_code == 200
    r = client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _department(client, h, teachers=("KAM", "RKD")):
    client.post("/api/departments/", json={"id": "cse", "name": "CSE"}, headers=h)
    for day in DAYS:
        for hour in range(8, 18):
            assert client.post("/api/constraints/time-slots", json={
                "id": f"{day}_{hour - 7}", "day": day, "period_index": hour - 7,
                "start_time": f"{hour:02d}:00", "end_time": f"{hour + 1:02d}:00",
            }, headers=h).status_code == 200
    for code in teachers:
        assert client.post("/api/teachers/", json={
            "id": f"t_{code}", "name": f"Teacher {code}", "initials": code, "department_id": "cse",
        }, headers=h).status_code == 200
    client.post("/api/rooms/", json={"id": "r_gcl", "name": "GCL", "type": "lab", "capacity": 40, "department_id": "cse"}, headers=h)
    client.post("/api/rooms/", json={"id": "r_lt", "name": "LT102", "type": "lecture", "capacity": 80, "department_id": "cse"}, headers=h)


@pytest.fixture()
def ocr_returns_fixture(monkeypatch):
    monkeypatch.setattr("app.routers.first_year_import.run_ocr", lambda content: PAGES)


def _preview(client, h, department="cse"):
    return client.post("/api/first-year-import/preview", data={"department_id": department},
                       files={"file": PDF}, headers=h)


def _apply_all(client, h, preview):
    rows = [{
        "periods": r["periods"],
        "teacher_ids": [t["teacher_id"] for t in r["teachers"] if t["status"] == "matched"],
        "room_id": r["room_id"], "reason": f"1st yr {r['section']} {r['subject']}",
        "tile": {"section": r["section"], "subject": r["subject"], "batches": r["batches"], "faculty": r["faculty"],
                 "room_text": r["room_text"], "start": r["start"], "end": r["end"]},
    } for r in preview["rows"]]
    return client.post("/api/first-year-import/apply", json={"department_id": "cse", "rows": rows}, headers=h)


def test_preview_proposes_only_our_teachers_and_rooms_and_writes_nothing(client, ocr_returns_fixture):
    h = _headers(client)
    _department(client, h)
    response = _preview(client, h)
    assert response.status_code == 200, response.text
    body = response.json()

    teachers = {t["teacher_id"] for r in body["rows"] for t in r["teachers"] if t["status"] == "matched"}
    assert teachers == {"t_KAM", "t_RKD"}
    assert {r["room_id"] for r in body["rows"]} >= {"r_gcl", "r_lt"}
    # Mon 11:00-12:00 KAM teaches OS in the Tut. Room (page 1)
    assert any(r["page"] == 1 and r["day"] == "Mon" and r["start"] == "11:00" and r["periods"] == [{"day": "Mon", "period": 4}]
               for r in body["rows"])
    assert client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json() == []


def test_apply_replaces_first_year_locks_and_leaves_other_reservations_alone(client, ocr_returns_fixture, db_session):
    from app.models import Reservation
    h = _headers(client)
    _department(client, h)
    db_session.add(Reservation(department_id="cse", resource_type="teacher", resource_id="t_KAM",
                               day="Sat", period=1, reason="other dept", source=None))
    db_session.commit()

    preview = _preview(client, h).json()
    first = _apply_all(client, h, preview)
    assert first.status_code == 200, first.text
    count = first.json()
    assert count["teacher_locks"] > 0 and count["room_locks"] > 0

    second = _apply_all(client, h, preview).json()
    assert second == count  # re-upload replaces, it never stacks duplicates

    locks = client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json()
    assert len(locks) == count["teacher_locks"] + count["room_locks"]
    assert {l["resource_name"] for l in locks if l["resource_type"] == "teacher"} == {"Teacher KAM", "Teacher RKD"}
    kept = db_session.query(Reservation).filter(Reservation.source.is_(None)).all()
    assert [(r.resource_id, r.day, r.period) for r in kept] == [("t_KAM", "Sat", 1)]

    cleared = client.delete("/api/first-year-import", params={"department_id": "cse"}, headers=h).json()
    assert cleared["removed"] == len(locks)
    assert db_session.query(Reservation).filter(Reservation.source.is_(None)).count() == 1


def test_apply_rejects_unknown_resources_and_slots_without_changing_anything(client, ocr_returns_fixture):
    h = _headers(client)
    _department(client, h)
    _apply_all(client, h, _preview(client, h).json())
    before = client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json()

    bad_teacher = client.post("/api/first-year-import/apply", headers=h, json={
        "department_id": "cse", "rows": [{"periods": [{"day": "Mon", "period": 1}], "teacher_ids": ["nobody"]}]})
    bad_slot = client.post("/api/first-year-import/apply", headers=h, json={
        "department_id": "cse", "rows": [{"periods": [{"day": "Sun", "period": 1}], "teacher_ids": ["t_KAM"]}]})
    assert bad_teacher.status_code == 422 and bad_slot.status_code == 422
    assert client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json() == before


def _tiles(client, h):
    r = client.get("/api/first-year-import/tiles", params={"department_id": "cse"}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_each_locked_class_is_stored_as_a_full_tile_per_teacher_and_room(client, ocr_returns_fixture):
    h = _headers(client)
    _department(client, h)
    preview = _preview(client, h).json()
    _apply_all(client, h, preview)
    tiles = _tiles(client, h)

    # KAM's Thursday OS class: full details, not just a busy slot
    kam = [t for t in tiles if t["resource_type"] == "teacher" and t["resource_id"] == "t_KAM"
           and t["day"] == "Thu" and t["subject"] == "CO34_OS"]
    assert len(kam) == 1
    tile = kam[0]
    assert tile["room_text"] == "LT102" and tile["periods"] == [4]
    assert tile["start"] == "11:00" and tile["end"] == "12:00"
    assert {f["code"] for f in tile["faculty"]} == {"KAM"} and tile["faculty"][0]["name"] == "Ms. Karishma"

    # a two-hour lab with several faculty: ours is listed with the others, spanning both periods
    lab = [t for t in tiles if t["resource_id"] == "t_RKD" and t["subject"] == "CO34_CN" and t["day"] == "Mon" and t["batches"]]
    assert len(lab) == 1 and lab[0]["periods"] == [7, 8] and lab[0]["batches"] == ["A1", "A2"]
    assert {"RKD", "AS", "ANS", "PM"} <= {f["code"] for f in lab[0]["faculty"]}
    assert lab[0]["room_text"] == "GCL"

    # the same class is also drawn on the room it books
    in_gcl = [t for t in tiles if t["resource_type"] == "room" and t["resource_id"] == "r_gcl" and t["tile_id"] == lab[0]["tile_id"]]
    assert len(in_gcl) == 1 and in_gcl[0]["periods"] == [7, 8]


def test_tiles_follow_their_locks_when_removed_or_cleared(client, ocr_returns_fixture, db_session):
    from app.models import FirstYearTile
    h = _headers(client)
    _department(client, h)
    _apply_all(client, h, _preview(client, h).json())
    assert db_session.query(FirstYearTile).count() > 0

    # re-applying replaces tiles instead of piling them up
    count = db_session.query(FirstYearTile).count()
    _apply_all(client, h, _preview(client, h).json())
    db_session.expire_all()
    assert db_session.query(FirstYearTile).count() == count

    # removing every lock of one tile removes the tile
    locks = client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json()
    tile = _tiles(client, h)[0]
    owners = [t for t in _tiles(client, h) if t["tile_id"] == tile["tile_id"]]
    for owner in owners:
        for lock in locks:
            if lock["resource_id"] == owner["resource_id"] and lock["day"] == owner["day"] and lock["period"] in owner["periods"]:
                client.delete(f"/api/first-year-import/{lock['id']}", params={"department_id": "cse"}, headers=h)
    assert tile["tile_id"] not in {t["tile_id"] for t in _tiles(client, h)}

    client.delete("/api/first-year-import", params={"department_id": "cse"}, headers=h)
    db_session.expire_all()
    assert db_session.query(FirstYearTile).count() == 0 and _tiles(client, h) == []


def test_manual_locks_become_tiles_split_by_day_and_gap(client):
    h = _headers(client)
    _department(client, h)
    body = {"department_id": "cse", "resource_type": "teacher", "resource_id": "t_KAM", "subject": "CO34_OS",
            "section": "I-C", "batches": ["C1"], "faculty_text": "KAM, RKD", "room_text": "LT101",
            "periods": [{"day": "Mon", "period": 2}, {"day": "Mon", "period": 3}, {"day": "Mon", "period": 6},
                        {"day": "Tue", "period": 1}]}
    assert client.post("/api/first-year-import/manual", json=body, headers=h).json()["teacher_locks"] == 4
    tiles = _tiles(client, h)
    assert sorted((t["day"], t["periods"]) for t in tiles) == [("Mon", [2, 3]), ("Mon", [6]), ("Tue", [1])]
    first = next(t for t in tiles if t["periods"] == [2, 3])
    assert (first["subject"], first["section"], first["batches"], first["room_text"]) == ("CO34_OS", "I-C", ["C1"], "LT101")
    assert [f["code"] for f in first["faculty"]] == ["KAM", "RKD"]
    assert (first["start"], first["end"]) == ("09:00", "11:00")

    bare = {**body, "periods": [{"day": "Fri", "period": 1}], "subject": "", "faculty_text": "", "room_text": "", "section": "", "batches": []}
    client.post("/api/first-year-import/manual", json=bare, headers=h)
    assert any(t["day"] == "Fri" and t["subject"] == "1st year class" for t in _tiles(client, h))


def _login(client, h, email, role, **extra):
    made = client.post("/api/auth/register", headers=h, json={
        "email": email, "password": "TestPassword123!", "full_name": email, "role": role, **extra})
    assert made.status_code == 200, made.text
    token = client.post("/api/auth/login", json={"email": email, "password": "TestPassword123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_tiles_respect_department_and_role_scoping(client, ocr_returns_fixture):
    h = _headers(client)
    _department(client, h)
    _apply_all(client, h, _preview(client, h).json())
    assert client.get("/api/first-year-import/tiles", params={"department_id": "cse"}).status_code in (401, 403)

    client.post("/api/departments/", json={"id": "ece", "name": "ECE"}, headers=h)
    other_admin = _login(client, h, "ece-admin@test.edu", "DEPT_ADMIN", department_id="ece")
    own_hod = _login(client, h, "hod@test.edu", "HOD", department_id="cse")
    teacher = _login(client, h, "kam@test.edu", "TEACHER", teacher_id="t_KAM")
    params = {"department_id": "cse"}

    # another department's admin can neither read nor change CSE's first-year data
    assert client.get("/api/first-year-import/tiles", params=params, headers=other_admin).status_code == 403
    assert client.get("/api/first-year-import", params=params, headers=other_admin).status_code == 403
    assert client.delete("/api/first-year-import", params=params, headers=other_admin).status_code == 403
    assert client.post("/api/first-year-import/manual", headers=other_admin, json={
        "department_id": "cse", "resource_type": "teacher", "resource_id": "t_KAM",
        "periods": [{"day": "Mon", "period": 1}]}).status_code == 403

    # an HOD of the department can see the tiles but not change locks
    assert client.get("/api/first-year-import/tiles", params=params, headers=own_hod).status_code == 200
    assert client.delete("/api/first-year-import", params=params, headers=own_hod).status_code == 403

    # a teacher sees only their own classes
    mine = client.get("/api/first-year-import/tiles", params=params, headers=teacher).json()
    assert mine and {(t["resource_type"], t["resource_id"]) for t in mine} == {("teacher", "t_KAM")}
    everyone = client.get("/api/first-year-import/tiles", params=params, headers=h).json()
    assert len({(t["resource_type"], t["resource_id"]) for t in everyone}) > 1


def test_manual_locks_are_added_without_replacing_and_can_be_removed_one_by_one(client, ocr_returns_fixture, db_session):
    from app.models import Reservation
    h = _headers(client)
    _department(client, h)
    _apply_all(client, h, _preview(client, h).json())
    before = client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json()

    body = {"department_id": "cse", "resource_type": "teacher", "resource_id": "t_KAM", "reason": "Sat guest lecture",
            "periods": [{"day": "Sat", "period": 1}, {"day": "Sat", "period": 2}]}
    first = client.post("/api/first-year-import/manual", json=body, headers=h)
    assert first.status_code == 200 and first.json() == {"teacher_locks": 2, "room_locks": 0}
    assert client.post("/api/first-year-import/manual", json=body, headers=h).json()["teacher_locks"] == 0  # no duplicates

    after = client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json()
    assert len(after) == len(before) + 2  # the OCR locks are still there

    room = client.post("/api/first-year-import/manual", headers=h, json={
        "department_id": "cse", "resource_type": "room", "resource_id": "r_gcl", "periods": [{"day": "Sat", "period": 3}]})
    assert room.json() == {"teacher_locks": 0, "room_locks": 1}

    lock = next(l for l in after if l["day"] == "Sat" and l["period"] == 1)
    assert client.delete(f"/api/first-year-import/{lock['id']}", params={"department_id": "cse"}, headers=h).status_code == 200
    assert client.delete(f"/api/first-year-import/{lock['id']}", params={"department_id": "cse"}, headers=h).status_code == 404
    assert len(client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json()) == len(before) + 2

    # a lock from another source can never be deleted through this endpoint
    other = Reservation(department_id="cse", resource_type="teacher", resource_id="t_KAM", day="Fri", period=9, source=None)
    db_session.add(other); db_session.commit()
    assert client.delete(f"/api/first-year-import/{other.id}", params={"department_id": "cse"}, headers=h).status_code == 404


def test_manual_lock_rejects_bad_input(client):
    h = _headers(client)
    _department(client, h)
    ok = {"department_id": "cse", "resource_type": "teacher", "resource_id": "t_KAM", "periods": [{"day": "Mon", "period": 1}]}
    assert client.post("/api/first-year-import/manual", json={**ok, "resource_id": "nobody"}, headers=h).status_code == 422
    assert client.post("/api/first-year-import/manual", json={**ok, "periods": [{"day": "Sun", "period": 1}]}, headers=h).status_code == 422
    assert client.post("/api/first-year-import/manual", json={**ok, "resource_type": "teacher_x"}, headers=h).status_code == 422
    assert client.post("/api/first-year-import/manual", json={**ok, "periods": []}, headers=h).status_code == 422
    assert client.get("/api/first-year-import", params={"department_id": "cse"}, headers=h).json() == []


def test_preview_errors_are_clear(client, monkeypatch):
    h = _headers(client)
    _department(client, h)
    not_pdf = client.post("/api/first-year-import/preview", data={"department_id": "cse"},
                          files={"file": ("x.xlsx", b"x", "application/octet-stream")}, headers=h)
    assert not_pdf.status_code == 400

    # OCR not configured -> 503 telling the admin what to set
    from app.core.config import settings
    monkeypatch.setattr(settings, "OCR_PYTHON", "")
    unavailable = _preview(client, h)
    assert unavailable.status_code == 503 and "OCR_PYTHON" in unavailable.json()["detail"]

    # a department whose teachers have no initials cannot be matched
    client.post("/api/departments/", json={"id": "ece", "name": "ECE"}, headers=h)
    assert _preview(client, h, department="ece").status_code == 422
    assert _preview(client, h, department="nope").status_code == 404


def test_locks_are_rejected_without_an_admin_login(client):
    assert client.get("/api/first-year-import", params={"department_id": "cse"}).status_code in (401, 403)
    assert client.post("/api/first-year-import/preview", data={"department_id": "cse"},
                       files={"file": PDF}).status_code in (401, 403)


# ---- the locks actually bind the solver -------------------------------------
def _generation_setup(client, h):
    """One section needing 3 maths sessions with a single maths teacher, in a
    5-day, 4-period week - tight enough that an ignored lock would show."""
    client.post("/api/departments/", json={"id": "cse", "name": "CSE"}, headers=h)
    for day in DAYS[:5]:
        for i in range(1, 5):
            client.post("/api/constraints/time-slots", json={
                "id": f"{day}_{i}", "day": day, "period_index": i,
                "start_time": f"{8 + i:02d}:00", "end_time": f"{9 + i:02d}:00"}, headers=h)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=h)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=h)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=h)
    client.post("/api/subjects/", json={"id": "maths", "name": "Maths", "type": "theory", "department_id": "cse", "weekly_hours": 3}, headers=h)
    client.post("/api/teachers/", json={"id": "t_maths", "name": "Maths", "initials": "MT", "department_id": "cse"}, headers=h)
    client.post("/api/teachers/t_maths/subjects", json={"teacher_id": "t_maths", "subject_id": "maths"}, headers=h)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "maths"}, headers=h)


@pytest.mark.parametrize("scope_mode", ["fresh", "fit_into_existing"])
def test_first_year_locks_bind_generation_in_every_scope_mode(client, scope_mode):
    h = _headers(client)
    _generation_setup(client, h)
    locked = [("Mon", 1), ("Mon", 2), ("Mon", 3), ("Mon", 4), ("Tue", 1), ("Tue", 2)]
    applied = client.post("/api/first-year-import/apply", headers=h, json={
        "department_id": "cse",
        "rows": [{"periods": [{"day": d, "period": p} for d, p in locked], "teacher_ids": ["t_maths"], "room_id": None,
                  "reason": "1st yr Sec A CO34_MA"}]})
    assert applied.status_code == 200, applied.text

    run_id = client.post("/api/timetable/generate", headers=h,
                         json={"department_id": "cse", "scope_mode": scope_mode}).json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=h).json()
    assert run["status"] == "completed", run.get("llm_explanation")
    entries = [e for e in client.get(f"/api/timetable/runs/{run_id}/entries", headers=h).json() if e["teacher_id"] == "t_maths"]
    assert len(entries) == 3
    assert not {(e["day"], e["period"]) for e in entries} & set(locked)
