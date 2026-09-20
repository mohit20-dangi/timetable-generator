"""End-to-end: bootstrap admin -> build a CSE department's data -> generate
-> independently validate -> publish -> per-user scoped view. Mirrors
seed_example.py but as permanent, assertion-backed regression coverage.
"""
ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "ADMIN"}


def _auth_headers(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _build_department(client, headers):
    client.post("/api/institutions/", json={"id": "inst1", "name": "Test Institute"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)

    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    times = [("09:00", "09:50"), ("09:50", "10:40"), ("10:40", "11:30"), ("11:30", "12:20")]
    for day in days:
        for i, (start, end) in enumerate(times, start=1):
            client.post("/api/constraints/time-slots", json={
                "id": f"{day}_{i}", "day": day, "period_index": i, "start_time": start, "end_time": end,
            }, headers=headers)

    client.post("/api/years/", json={"id": "y3", "name": "III Year", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "sec_a", "year_id": "y3", "name": "Section A", "strength": 40}, headers=headers)

    client.post("/api/rooms/", json={"id": "lt1", "name": "LT1", "type": "lecture", "capacity": 60, "department_id": "cse"}, headers=headers)
    client.post("/api/rooms/", json={"id": "lab1", "name": "Lab1", "type": "lab", "capacity": 25, "department_id": "cse"}, headers=headers)
    client.post("/api/rooms/", json={"id": "lab2", "name": "Lab2", "type": "lab", "capacity": 25, "department_id": "cse"}, headers=headers)

    client.post("/api/subjects/", json={
        "id": "ds", "name": "Data Structures", "type": "theory", "department_id": "cse",
        "weekly_hours": 3, "max_per_day": 1,
    }, headers=headers)
    client.post("/api/subjects/", json={
        "id": "lab_subj", "name": "Programming Lab", "type": "lab", "department_id": "cse",
        "weekly_hours": 2, "block_size": 2, "needs_continuous_block": True, "requires_room_type": "lab",
    }, headers=headers)
    client.post("/api/subjects/", json={
        "id": "nptel", "name": "NPTEL Course", "type": "theory", "department_id": "cse",
        "delivery_mode": "MOOC_NPTEL", "weekly_hours": 0, "scheme_hours_per_week": 3,
    }, headers=headers)

    client.post("/api/teachers/", json={"id": "t1", "name": "Teacher One", "department_id": "cse"}, headers=headers)
    client.post("/api/teachers/", json={"id": "t2", "name": "Teacher Two", "department_id": "cse"}, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "ds"}, headers=headers)
    client.post("/api/teachers/t1/subjects", json={"teacher_id": "t1", "subject_id": "lab_subj"}, headers=headers)
    client.post("/api/teachers/t2/subjects", json={"teacher_id": "t2", "subject_id": "lab_subj"}, headers=headers)

    for subject_id in ["ds", "lab_subj", "nptel"]:
        client.post("/api/constraints/section-subjects", json={"section_id": "sec_a", "subject_id": subject_id}, headers=headers)

    client.post("/api/constraints/lab-batches", json={"id": "b1", "section_id": "sec_a", "batch_name": "B1", "strength": 20}, headers=headers)
    client.post("/api/constraints/lab-batches", json={"id": "b2", "section_id": "sec_a", "batch_name": "B2", "strength": 20}, headers=headers)


def test_full_generation_flow(client):
    r = client.post("/api/auth/bootstrap-admin", json=ADMIN)
    assert r.status_code == 200, r.text
    headers = _auth_headers(client, ADMIN["email"], ADMIN["password"])

    _build_department(client, headers)

    r = client.post("/api/timetable/generate", json={"department_id": "cse", "num_alternatives": 1}, headers=headers)
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]

    run = client.get(f"/api/timetable/runs/{run_id}", headers=headers).json()
    assert run["status"] == "completed", run.get("llm_explanation")

    entries = client.get(f"/api/timetable/runs/{run_id}/entries", headers=headers).json()
    subject_ids = {e["subject_id"] for e in entries}
    assert "nptel" not in subject_ids, "MOOC_NPTEL subject must never be scheduled"
    assert subject_ids == {"ds", "lab_subj"}

    validation = client.get(f"/api/timetable/runs/{run_id}/validate", headers=headers).json()
    assert validation["valid"], validation["issues"]

    # publish, then check the scoped /me view for a registered faculty/student
    pub = client.post(f"/api/timetable/runs/{run_id}/publish", headers=headers)
    assert pub.status_code == 200, pub.text

    client.post("/api/auth/register", json={
        "email": "student@test.edu", "password": "TestPassword123!", "full_name": "Stu",
        "role": "STUDENT", "section_id": "sec_a",
    }, headers=headers)
    student_headers = _auth_headers(client, "student@test.edu", "TestPassword123!")
    my_schedule = client.get("/api/timetable/me", headers=student_headers).json()
    assert len(my_schedule) == len(entries)


def test_infeasible_generation_reports_named_cause(client):
    """A subject with NO qualified teacher must fail generation with a
    diagnostic that names the actual subject, not a bare 'INFEASIBLE'."""
    r = client.post("/api/auth/bootstrap-admin", json=ADMIN)
    headers = _auth_headers(client, ADMIN["email"], ADMIN["password"])

    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    client.post("/api/constraints/time-slots", json={
        "id": "Mon_1", "day": "Mon", "period_index": 1, "start_time": "09:00", "end_time": "09:50",
    }, headers=headers)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={"id": "orphan", "name": "Orphan Subject", "type": "theory", "department_id": "cse", "weekly_hours": 1}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": "orphan"}, headers=headers)
    # deliberately no teacher qualified for "orphan"

    r = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=headers)
    run_id = r.json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=headers).json()
    assert run["status"] == "failed"
    assert "orphan" in (run["llm_explanation"] or "").lower() or "Orphan Subject" in (run["llm_explanation"] or "")


def test_fit_into_existing_scope_freezes_other_sections(client):
    """Publishing section A's run, then regenerating section B with a
    SHARED teacher in fit_into_existing mode, must never double-book that
    teacher - this is the scope mechanism from the planning discussion."""
    r = client.post("/api/auth/bootstrap-admin", json=ADMIN)
    headers = _auth_headers(client, ADMIN["email"], ADMIN["password"])

    client.post("/api/institutions/", json={"id": "inst1", "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=headers)
    for i in range(1, 3):  # only 2 slots on purpose - forces the shared teacher into a real conflict if not frozen
        client.post("/api/constraints/time-slots", json={
            "id": f"Mon_{i}", "day": "Mon", "period_index": i, "start_time": f"0{8+i}:00", "end_time": f"0{9+i}:00",
        }, headers=headers)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=headers)
    client.post("/api/sections/", json={"id": "sec_a", "year_id": "y1", "name": "A", "strength": 30}, headers=headers)
    client.post("/api/sections/", json={"id": "sec_b", "year_id": "y1", "name": "B", "strength": 30}, headers=headers)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=headers)
    client.post("/api/subjects/", json={"id": "shared_subj", "name": "Shared", "type": "theory", "department_id": "cse", "weekly_hours": 1}, headers=headers)
    client.post("/api/teachers/", json={"id": "shared_t", "name": "Shared Teacher", "department_id": "cse"}, headers=headers)
    client.post("/api/teachers/shared_t/subjects", json={"teacher_id": "shared_t", "subject_id": "shared_subj"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "sec_a", "subject_id": "shared_subj"}, headers=headers)
    client.post("/api/constraints/section-subjects", json={"section_id": "sec_b", "subject_id": "shared_subj"}, headers=headers)

    r1 = client.post("/api/timetable/generate", json={
        "department_id": "cse", "section_ids": ["sec_a"], "scope_mode": "fit_into_existing",
    }, headers=headers)
    run1_id = r1.json()["id"]
    assert client.get(f"/api/timetable/runs/{run1_id}", headers=headers).json()["status"] == "completed"
    client.post(f"/api/timetable/runs/{run1_id}/publish", headers=headers)

    r2 = client.post("/api/timetable/generate", json={
        "department_id": "cse", "section_ids": ["sec_b"], "scope_mode": "fit_into_existing",
    }, headers=headers)
    run2_id = r2.json()["id"]
    run2 = client.get(f"/api/timetable/runs/{run2_id}", headers=headers).json()
    assert run2["status"] == "completed", run2.get("llm_explanation")

    entries_a = client.get(f"/api/timetable/runs/{run1_id}/entries", headers=headers).json()
    entries_b = client.get(f"/api/timetable/runs/{run2_id}/entries", headers=headers).json()
    slots_a = {(e["day"], e["period"]) for e in entries_a}
    slots_b = {(e["day"], e["period"]) for e in entries_b}
    assert not (slots_a & slots_b), "Shared teacher was double-booked across two separately-generated runs"
