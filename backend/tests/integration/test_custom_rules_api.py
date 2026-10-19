"""Admin-defined preference rules, end to end through the real HTTP API and
database: create the rule, generate, and check the stored timetable obeys it.
"""
ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "SUPERADMIN"}


def _headers(client):
    assert client.post("/api/auth/bootstrap-admin", json=ADMIN).status_code == 200
    r = client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _build_department(client, h):
    client.post("/api/departments/", json={"id": "cse", "institution_id": "inst1", "name": "CSE"}, headers=h)
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        for i in range(1, 5):
            client.post("/api/constraints/time-slots", json={
                "id": f"{day}_{i}", "day": day, "period_index": i,
                "start_time": f"{8 + i:02d}:00", "end_time": f"{9 + i:02d}:00",
            }, headers=h)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": "cse"}, headers=h)
    client.post("/api/sections/", json={"id": "s1", "year_id": "y1", "name": "S1", "strength": 30}, headers=h)
    client.post("/api/rooms/", json={"id": "r1", "name": "R1", "type": "lecture", "capacity": 40, "department_id": "cse"}, headers=h)
    for sid in ("maths", "physics"):
        client.post("/api/subjects/", json={"id": sid, "name": sid.title(), "type": "theory", "department_id": "cse", "weekly_hours": 3}, headers=h)
        client.post("/api/teachers/", json={"id": f"t_{sid}", "name": sid, "department_id": "cse"}, headers=h)
        client.post(f"/api/teachers/t_{sid}/subjects", json={"teacher_id": f"t_{sid}", "subject_id": sid}, headers=h)
        client.post("/api/constraints/section-subjects", json={"section_id": "s1", "subject_id": sid}, headers=h)


def _rule(**overrides):
    base = {
        "id": "r_maths", "department_id": "cse", "rule_type": "subject_time_window",
        "target_type": "subject", "target_id": "maths", "start_time": "09:00", "end_time": "11:00",
        "priority": "hard", "weight": 0, "params": {"mode": "within"},
    }
    base.update(overrides)
    return base


def test_subject_time_window_rule_is_applied_to_a_generated_timetable(client):
    h = _headers(client)
    _build_department(client, h)
    created = client.post("/api/constraint-rules/", json=_rule(), headers=h)
    assert created.status_code == 200, created.text
    assert created.json()["params"] == {"mode": "within"}

    run_id = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=h).json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=h).json()
    assert run["status"] == "completed", run.get("llm_explanation")

    entries = client.get(f"/api/timetable/runs/{run_id}/entries", headers=h).json()
    maths = [e for e in entries if e["subject_id"] == "maths"]
    assert len(maths) == 3
    assert all(e["period"] in (1, 2) for e in maths), [e["period"] for e in maths]


def test_unsatisfiable_hard_rule_fails_with_a_clear_message(client):
    h = _headers(client)
    _build_department(client, h)
    # 3 maths sessions, max 1 per day, but a window on a single day with one period.
    client.post("/api/constraint-rules/", json=_rule(day="Mon", end_time="10:00"), headers=h)
    run_id = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=h).json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=h).json()
    assert run["status"] == "failed"
    # The admin must be told WHICH rule/subject is impossible, not just "failed".
    assert "room for only 1 session" in run["llm_explanation"] and "Maths" in run["llm_explanation"]


def test_rule_payloads_are_validated(client):
    h = _headers(client)
    _build_department(client, h)
    bad = [
        _rule(id="a", target_type="teacher"),                       # wrong target for the template
        _rule(id="b", priority="soft", weight=0),                   # a soft rule with no weight does nothing
        _rule(id="c", params={"mode": "sideways"}),                 # unknown mode
        _rule(id="d", rule_type="max_subjects_per_day", target_type="section", target_id="s1", params={}),  # no max
        _rule(id="e", start_time="11:00", end_time="09:00"),        # backwards window
    ]
    for payload in bad:
        assert client.post("/api/constraint-rules/", json=payload, headers=h).status_code == 422, payload["id"]
