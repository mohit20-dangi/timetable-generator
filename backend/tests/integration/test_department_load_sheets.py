"""The six-sheet department load workbook (Faculty List, Subject Choice, Load
Calculation, Faculty wise subject allocation, First Year Load, Elective) and
the NPTEL self-study periods it can produce."""
import io

import pytest
from openpyxl import Workbook, load_workbook

from app.models import TeacherSubject
from app.services.college_load_import import build_college_template

ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "SUPERADMIN"}
SIX = ["Faculty List", "Subject Choice", "Load Calculation", "Faculty wise subject allocation",
       "First Year Load", "Elective"]


def _headers(client):
    assert client.post("/api/auth/bootstrap-admin", json=ADMIN).status_code == 200
    r = client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _template_bytes() -> bytes:
    output = io.BytesIO()
    build_college_template().save(output)
    return output.getvalue()


def _import(client, headers, content):
    r = client.post("/api/import/excel", headers=headers,
                    files={"file": ("load.xlsx", content, "application/octet-stream")})
    assert r.status_code == 200, r.text
    return r.json()


def _edited_template(edit) -> bytes:
    workbook = load_workbook(io.BytesIO(_template_bytes()))
    edit(workbook)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_template_has_exactly_the_six_sheets():
    assert build_college_template().sheetnames == SIX


def test_template_imports_with_batches_sizes_roles_and_nptel(client, db_session):
    headers = _headers(client)
    preview = client.post("/api/import/excel/preview", headers=headers,
                          files={"file": ("t.xlsx", _template_bytes(), "application/octet-stream")})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["format"] == "college_load"
    assert body["sheets"]["Teachers"] == 3 and body["sheets"]["Sections"] == 3
    assert body["sheets"]["LabBatches"] == 3          # "No. of Batches" of the lab

    _import(client, headers, _template_bytes())
    subjects = {s["id"]: s for s in client.get("/api/subjects/", headers=headers).json()}
    lab = subjects["CO24402"]
    assert lab["teachers_required"] == 2               # "No. of faculty"
    assert lab["periods_per_session"] == 2
    sections = {s["id"]: s for s in client.get("/api/sections/", headers=headers).json()}
    assert sections["SEC_II_A"]["strength"] == 45       # class of 90 split over A and B
    assert sections["SEC_III_A"]["strength"] == 60

    # NPTEL: no teacher, not in the basket, self-study periods instead
    nptel = next(s for s in subjects.values() if s["delivery_mode"] == "MOOC_NPTEL")
    assert nptel["self_study_hours"] == 3 and nptel["elective_group_id"] is None
    group = client.get("/api/elective-groups/", headers=headers).json()[0]
    assert nptel["id"] not in group["offered_subject_ids"]
    assert group["offered_subject_ids"] == ["CO34601"]
    assert not db_session.query(TeacherSubject).filter(TeacherSubject.subject_id == nptel["id"]).count()

    # the allocation's Secondary column
    roles = {(t.teacher_id, t.subject_id): t.role for t in db_session.query(TeacherSubject).all()}
    assert roles[("T_ET", "CO24402")] == "main" and roles[("T_SF", "CO24402")] == "secondary"

    teachers = {t["id"]: t for t in client.get("/api/teachers/", headers=headers).json()}
    assert teachers["T_ET"]["max_weekly_hours"] == 18
    assert teachers["T_SF"]["first_year_hours"] == 7


def test_allocation_wins_over_choice_and_choice_fills_the_rest(client, db_session):
    headers = _headers(client)

    def edit(workbook):
        # Mr. Another Teacher is allocated DBMS only; Ms. Sample Faculty chose
        # Computer Architecture but is allocated Data Structures + a lab, so her
        # choice must not add her to a subject that is already allocated.
        allocation = workbook["Faculty wise subject allocation"]
        for row in allocation.iter_rows(min_row=6):
            if row[1].value == "Dr. Example Teacher":
                row[3].value = None            # CO24019 now has nobody allocated
        choice = workbook["Subject Choice"]
        for row in choice.iter_rows(min_row=6):
            if row[1].value == "Mr. Another Teacher":
                row[3].value = "CO24019T Th Computer Architecture"

    _import(client, headers, _edited_template(edit))
    links = {(t.teacher_id, t.subject_id) for t in db_session.query(TeacherSubject).all()}
    # AT has an allocation (DBMS, the elective), so the choice is ignored
    assert ("T_AT", "CO24019") not in links
    # SF's choice of Computer Architecture is ignored too (allocated elsewhere)
    assert ("T_SF", "CO24019") not in links


def test_a_subject_nobody_is_allocated_takes_the_teachers_who_chose_it(client, db_session):
    headers = _headers(client)

    def edit(workbook):
        allocation = workbook["Faculty wise subject allocation"]
        for row in allocation.iter_rows(min_row=6):
            if row[1].value == "Dr. Example Teacher":
                row[3].value = None            # Computer Architecture loses its teacher
                row[9].value = None
            if row[1].value == "Mr. Another Teacher":
                row[3].value = None
                row[7].value = None
        # AT and ET now have no allocation at all, so their choices count
        choice = workbook["Subject Choice"]
        choice.append([3, "Dr. Example Teacher", "ET", "CO24019T Th Computer Architecture"])
        # the lab keeps SF (secondary) only, ET removed above

    _import(client, headers, _edited_template(edit))
    links = {(t.teacher_id, t.subject_id): t.role for t in db_session.query(TeacherSubject).all()}
    assert links.get(("T_ET", "CO24019")) == "main"


def _build_nptel_department(client, headers, first_year_hours=0):
    client.post("/api/departments/", json={"id": "cse", "institution_id": "i", "name": "CSE"}, headers=headers)
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        for i in range(1, 6):
            client.post("/api/constraints/time-slots", json={
                "id": f"{day}_{i}", "day": day, "period_index": i,
                "start_time": f"{8 + i:02d}:00", "end_time": f"{9 + i:02d}:00", "department_id": "cse",
            }, headers=headers)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40,
                                     "department_id": "cse"}, headers=headers)
    client.post("/api/rooms/", json={"id": "r2", "name": "R2", "type": "lecture", "capacity": 40,
                                     "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={"id": "maths", "name": "Maths", "type": "theory", "department_id": "cse",
                                        "weekly_hours": 3}, headers=headers)
    client.post("/api/subjects/", json={"id": "nptel", "name": "NPTEL AI", "type": "theory", "department_id": "cse",
                                        "delivery_mode": "MOOC_NPTEL", "lecture_hours": 3, "self_study_hours": 3},
                headers=headers)
    client.post("/api/teachers/", json={"id": "t1", "name": "T1", "department_id": "cse", "max_weekly_hours": 24,
                                        "first_year_hours": first_year_hours}, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "maths"}, headers=headers)
    for subject in ("maths", "nptel"):
        client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": subject}, headers=headers)


def _generate(client, headers):
    run_id = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers).json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=headers).json()
    entries = client.get(f"/api/timetable/runs/{run_id}/entries", headers=headers).json()
    return run, entries


def test_nptel_gets_self_study_only_at_the_start_or_end_of_the_day(client):
    headers = _headers(client)
    _build_nptel_department(client, headers)
    run, entries = _generate(client, headers)
    assert run["status"] == "completed", run.get("llm_explanation")
    study = [e for e in entries if e["subject_id"] == "nptel"]
    assert len(study) == 3
    assert all(e["period"] in (1, 5) for e in study), [(e["day"], e["period"]) for e in study]
    assert all(e["teacher_id"] is None and e["room_id"] is None for e in study)
    assert len({e["day"] for e in study}) == 3         # at most one block a day
    maths = [e for e in entries if e["subject_id"] == "maths"]
    assert all(e["teacher_id"] == "t1" for e in maths)
    # a block with no teacher or room must not break the exports
    for fmt in ("xlsx", "pdf"):
        for view, entity in (("section", "s1"), ("teacher", "t1")):
            r = client.get(f"/api/timetable/runs/{run['id']}/export", headers=headers,
                           params={"format": fmt, "view": view, "entity_id": entity})
            assert r.status_code == 200, (fmt, view, r.text[:300])


def test_first_year_hours_come_off_a_teachers_weekly_cap(client):
    headers = _headers(client)
    _build_nptel_department(client, headers, first_year_hours=0)
    client.put("/api/teachers/t1", headers=headers, json={
        "id": "t1", "name": "T1", "department_id": "cse", "max_weekly_hours": 4, "first_year_hours": 0})
    run, _ = _generate(client, headers)
    assert run["status"] == "completed", run.get("llm_explanation")   # 3 of 4 hours fits

    client.put("/api/teachers/t1", headers=headers, json={
        "id": "t1", "name": "T1", "department_id": "cse", "max_weekly_hours": 4, "first_year_hours": 3})
    run, _ = _generate(client, headers)
    assert run["status"] != "completed"                               # only 1 hour is left


def test_a_secondary_teacher_assists_but_never_runs_the_class_alone(client, db_session):
    headers = _headers(client)
    _build_nptel_department(client, headers)
    client.post("/api/teachers/", json={"id": "t2", "name": "T2", "department_id": "cse"}, headers=headers)
    client.post("/api/teachers/t2/subjects", json={"teacher_id": "t2", "subject_id": "maths", "role": "secondary"},
                headers=headers)
    # one teacher at a time: the main teacher, always
    run, entries = _generate(client, headers)
    assert run["status"] == "completed", run.get("llm_explanation")
    assert {e["teacher_id"] for e in entries if e["subject_id"] == "maths"} == {"t1"}

    # two at a time: the main one leads, the other assists (a co-teacher)
    subject = client.get("/api/subjects/maths", headers=headers).json()
    client.put("/api/subjects/maths", headers=headers, json={**subject, "teachers_required": 2})
    run, entries = _generate(client, headers)
    assert run["status"] == "completed", run.get("llm_explanation")
    maths = [e for e in entries if e["subject_id"] == "maths"]
    assert {e["teacher_id"] for e in maths} == {"t1"}
    from app.models import GeneratedEntry
    last_run = max(e.timetable_run_id for e in db_session.query(GeneratedEntry).all())
    stored = db_session.query(GeneratedEntry).filter(
        GeneratedEntry.subject_id == "maths", GeneratedEntry.timetable_run_id == last_run).all()
    assert stored and all(list(e.co_teacher_ids or []) == ["t2"] for e in stored)


def test_the_colleges_own_sheet_names_are_found():
    from app.services.department_load_sheets import find_sheet

    workbook = Workbook()
    for title in ("load_calculation", "Choice_filling", "I_YEAR_LOAD", "electives", "faculty_list"):
        workbook.create_sheet(title)
    roles = {role: find_sheet(workbook, role) for role in ("load", "choice", "first_year", "elective", "faculty")}
    assert roles == {"load": "load_calculation", "choice": "Choice_filling", "first_year": "I_YEAR_LOAD",
                     "elective": "electives", "faculty": "faculty_list"}
