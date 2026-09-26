"""Phase 4.5 - regression coverage for behaviour that shipped in earlier
phases but never had a dedicated test (Ground rule 1 deferred all new
tests to Phase 4). Each test isolates ONE mechanism and proves it by
constructing a scenario that is only satisfiable if that mechanism is
actually enforced - not just that generation "succeeds".
"""
from openpyxl import load_workbook
import io

ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "ADMIN"}


def _auth_headers(client, email=ADMIN["email"], password=ADMIN["password"]):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _bootstrap(client):
    r = client.post("/api/auth/bootstrap-admin", json=ADMIN)
    assert r.status_code == 200, r.text
    return _auth_headers(client)


def _time_slots(client, headers, days, periods_per_day=1, start_hour=9):
    for day in days:
        for i in range(1, periods_per_day + 1):
            h = start_hour + i - 1
            client.post("/api/constraints/time-slots", json={
                "id": f"{day}_{i}", "day": day, "period_index": i,
                "start_time": f"{h:02d}:00", "end_time": f"{h + 1:02d}:00",
            }, headers=headers)


def test_reset_scoping_keeps_timetable_history(client):
    """Phase 0.1: resetting "sections" must never touch TimetableRun/
    GeneratedEntry - only the explicit "timetables" scope does."""
    headers = _bootstrap(client)
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    _time_slots(client, headers, ["Mon"], periods_per_day=1)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={"id": "sub1", "name": "Subject 1", "type": "theory", "department_id": "cse", "weekly_hours": 1}, headers=headers)
    client.post("/api/teachers/", json={"id": "t1", "name": "T1", "department_id": "cse"}, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "sub1"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "sub1"}, headers=headers)

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run_id = r.json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=headers).json()
    assert run["status"] == "completed", run.get("llm_explanation")
    entries_before = client.get(f"/api/timetable/runs/{run_id}/entries", headers=headers).json()
    assert len(entries_before) > 0

    reset = client.post("/api/admin/data/reset/sections", headers=headers)
    assert reset.status_code == 200, reset.text

    run_after = client.get(f"/api/timetable/runs/{run_id}", headers=headers)
    assert run_after.status_code == 200, "resetting sections must not delete timetable history"
    entries_after = client.get(f"/api/timetable/runs/{run_id}/entries", headers=headers).json()
    assert len(entries_after) == len(entries_before)

    # The section itself IS gone - that's what the scope is for.
    assert client.get("/api/sections/", headers=headers).json() == []


def test_editing_a_class_creates_a_child_run_and_leaves_parent_untouched(client):
    """Phase 0.3: editing must copy-on-write into a new TimetableRun, not
    mutate the run being viewed."""
    headers = _bootstrap(client)
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    _time_slots(client, headers, ["Mon", "Tue"], periods_per_day=1)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={"id": "sub1", "name": "Subject 1", "type": "theory", "department_id": "cse", "weekly_hours": 1}, headers=headers)
    client.post("/api/teachers/", json={"id": "t1", "name": "T1", "department_id": "cse"}, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "sub1"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "sub1"}, headers=headers)

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run_id = r.json()["id"]
    assert client.get(f"/api/timetable/runs/{run_id}", headers=headers).json()["status"] == "completed"
    entries = client.get(f"/api/timetable/runs/{run_id}/entries", headers=headers).json()
    assert len(entries) == 1
    original = entries[0]
    new_day, new_period = ("Tue", 1) if original["day"] == "Mon" else ("Mon", 1)

    edit = client.post(f"/api/timetable/runs/{run_id}/edit", json={
        "target": {"day": original["day"], "period": original["period"], "subject_id": "sub1", "section_id": "s1"},
        "new_day": new_day, "new_period": new_period,
    }, headers=headers)
    assert edit.status_code == 200, edit.text
    body = edit.json()
    assert body["status"] == "applied", body
    new_run = body["new_run"]
    assert new_run["id"] != run_id, "edit must create a NEW run, not reuse the one being viewed"
    assert new_run["parent_run_id"] == run_id
    assert new_run["change_summary"], "a human-readable summary of the move is required"

    parent_entries = client.get(f"/api/timetable/runs/{run_id}/entries", headers=headers).json()
    assert parent_entries[0]["day"] == original["day"] and parent_entries[0]["period"] == original["period"], \
        "the parent run must be left exactly as it was"

    child_entries = client.get(f"/api/timetable/runs/{new_run['id']}/entries", headers=headers).json()
    assert child_entries[0]["day"] == new_day and child_entries[0]["period"] == new_period


def test_teacher_marked_unavailable_is_never_scheduled_then(client):
    """Phase 1.1: TeacherInfo.unavailable_slot_indices must actually forbid
    placement, not just be computed and ignored."""
    headers = _bootstrap(client)
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    _time_slots(client, headers, ["Mon", "Tue"], periods_per_day=1)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={"id": "sub1", "name": "Subject 1", "type": "theory", "department_id": "cse", "weekly_hours": 1}, headers=headers)
    # Available only on Tuesday - absence of a day means unavailable that
    # whole day (see Teacher.availability's docstring).
    client.post("/api/teachers/", json={
        "id": "t1", "name": "T1", "department_id": "cse",
        "availability": [{"day": "Tue", "start": "09:00", "end": "10:00"}],
    }, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "sub1"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "sub1"}, headers=headers)

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run_id = r.json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=headers).json()
    assert run["status"] == "completed", run.get("llm_explanation")
    entries = client.get(f"/api/timetable/runs/{run_id}/entries", headers=headers).json()
    assert len(entries) == 1
    assert entries[0]["day"] == "Tue", "the only entry must land on the teacher's one available day"

    validation = client.get(f"/api/timetable/runs/{run_id}/validate", headers=headers).json()
    assert validation["valid"], validation["issues"]


def test_teacher_daily_cap_is_respected(client):
    """Phase 1.3: with both weekly sessions only placeable on the SAME
    single configured day, a max_daily_classes=1 cap must make this
    unsatisfiable - proving the cap is a real hard constraint, not just
    stored and displayed."""
    headers = _bootstrap(client)
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    _time_slots(client, headers, ["Mon"], periods_per_day=2)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={
        "id": "sub1", "name": "Subject 1", "type": "theory", "department_id": "cse",
        "weekly_hours": 2, "sessions_per_week": 2, "periods_per_session": 1,
    }, headers=headers)
    client.post("/api/teachers/", json={"id": "t1", "name": "T1", "department_id": "cse", "max_daily_classes": 1}, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "sub1"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "sub1"}, headers=headers)

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run = client.get(f"/api/timetable/runs/{r.json()['id']}", headers=headers).json()
    assert run["status"] == "failed", "2 sessions forced onto 1 day must be infeasible under max_daily_classes=1"


def test_teacher_weekly_cap_is_respected(client):
    """max_weekly_hours=1 with 2 required contact hours (spread across 2
    different days, so the daily cap alone couldn't explain a failure)
    must still make generation infeasible."""
    headers = _bootstrap(client)
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    _time_slots(client, headers, ["Mon", "Tue"], periods_per_day=1)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={
        "id": "sub1", "name": "Subject 1", "type": "theory", "department_id": "cse",
        "weekly_hours": 2, "sessions_per_week": 2, "periods_per_session": 1,
    }, headers=headers)
    client.post("/api/teachers/", json={
        "id": "t1", "name": "T1", "department_id": "cse", "max_daily_classes": 6, "max_weekly_hours": 1,
    }, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "sub1"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "sub1"}, headers=headers)

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run = client.get(f"/api/timetable/runs/{r.json()['id']}", headers=headers).json()
    assert run["status"] == "failed", "2 required hours with max_weekly_hours=1 must be infeasible"


def test_teacher_continuous_cap_is_respected(client):
    """3 unavoidably-back-to-back periods (the only day configured has
    exactly 3 periods, all needed) against max_continuous_classes=2 must
    be infeasible."""
    headers = _bootstrap(client)
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    _time_slots(client, headers, ["Mon"], periods_per_day=3)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={
        "id": "sub1", "name": "Subject 1", "type": "theory", "department_id": "cse",
        "weekly_hours": 3, "sessions_per_week": 3, "periods_per_session": 1, "max_per_day": 3,
    }, headers=headers)
    client.post("/api/teachers/", json={
        "id": "t1", "name": "T1", "department_id": "cse",
        "max_daily_classes": 6, "max_weekly_hours": 24, "max_continuous_classes": 2,
    }, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "sub1"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "sub1"}, headers=headers)

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run = client.get(f"/api/timetable/runs/{r.json()['id']}", headers=headers).json()
    assert run["status"] == "failed", "3 unavoidably-consecutive periods with max_continuous_classes=2 must be infeasible"


def test_hard_constraint_rule_changes_the_result(client):
    """Phase 1.4: an approved ConstraintRule with priority=hard must
    actually reach the solver - the previous build stored, displayed, and
    audited these rules while no code path ever read them."""
    headers = _bootstrap(client)
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    _time_slots(client, headers, ["Mon", "Tue"], periods_per_day=1)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={"id": "sub1", "name": "Subject 1", "type": "theory", "department_id": "cse", "weekly_hours": 1}, headers=headers)
    client.post("/api/teachers/", json={"id": "t1", "name": "T1", "department_id": "cse"}, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "sub1"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "sub1"}, headers=headers)

    # "Prof. T1 is unavailable Monday" as a hard, AI/manual-authored rule -
    # not via the teacher's own availability field.
    rule = client.post("/api/constraint-rules/", json={
        "id": "rule1", "department_id": "cse", "rule_type": "teacher_unavailable",
        "target_type": "teacher", "target_id": "t1", "day": "Mon",
        "start_time": "09:00", "end_time": "10:00", "priority": "hard",
    }, headers=headers)
    assert rule.status_code == 200, rule.text

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run = client.get(f"/api/timetable/runs/{r.json()['id']}", headers=headers).json()
    assert run["status"] == "completed", run.get("llm_explanation")
    entries = client.get(f"/api/timetable/runs/{r.json()['id']}/entries", headers=headers).json()
    assert entries[0]["day"] == "Tue", "the hard ConstraintRule must have forced the class off Monday"


def test_export_merges_multi_period_block_and_renders_lunch_band(client):
    """Phase 4.1: GeneratedEntry.session_group exists precisely so a
    2-period block prints as ONE merged cell, not one row per period, and
    a per-day lunch window renders as its own labelled cell."""
    headers = _bootstrap(client)
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    # 4 contiguous periods: a 2-period lab fills 1-2, lunch covers period 3,
    # nothing scheduled in period 4.
    for i, (start, end) in enumerate([("09:00", "10:00"), ("10:00", "11:00"), ("12:00", "13:00"), ("14:00", "15:00")], start=1):
        client.post("/api/constraints/time-slots", json={
            "id": f"Mon_{i}", "day": "Mon", "period_index": i, "start_time": start, "end_time": end,
        }, headers=headers)
    client.post("/api/years/", json={
        "id": "y1", "name": "Y1", "department_id": "cse",
        "lunch_windows": {"Mon": ["12:00", "13:00"]},
    }, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 20}, headers=headers)
    client.post("/api/rooms/", json={"id": "lab1", "name": "Lab1", "type": "lab", "capacity": 25, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={
        "id": "lab_subj", "name": "Programming Lab", "type": "lab", "department_id": "cse",
        "weekly_hours": 2, "sessions_per_week": 1, "periods_per_session": 2, "back_to_back": True,
        "requires_room_type": "lab",
    }, headers=headers)
    client.post("/api/teachers/", json={"id": "t1", "name": "T1", "department_id": "cse"}, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "lab_subj"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "lab_subj"}, headers=headers)
    client.post("/api/constraints/lab-batches", json={"id": "b1", "section_id": "s1", "batch_name": "B1", "strength": 20}, headers=headers)

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run_id = r.json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=headers).json()
    assert run["status"] == "completed", run.get("llm_explanation")

    resp = client.get(f"/api/timetable/runs/{run_id}/export", params={"format": "xlsx", "view": "section", "entity_id": "s1"}, headers=headers)
    assert resp.status_code == 200, resp.text
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb.active

    merged_row_spans = [(rng.min_row, rng.max_row) for rng in ws.merged_cells.ranges if rng.max_row > rng.min_row]
    assert any(end - start == 1 for start, end in merged_row_spans), \
        f"expected a 2-row merge for the lab block, got merges: {merged_row_spans}"

    all_values = [cell.value for row in ws.iter_rows() for cell in row]
    assert any(v == "Lunch" for v in all_values), "expected a rendered 'Lunch' cell"
