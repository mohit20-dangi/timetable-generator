"""Roles are SUPERADMIN (every department), DEPT_ADMIN (all of one
department), HOD (one department's timetables) and TEACHER (own published
schedule). These tests pin the department wall: nobody but the superadmin
can see or change another department's data, however they phrase the
request."""

SUPER = {"email": "super@test.edu", "password": "TestPassword123!", "full_name": "Super", "role": "SUPERADMIN"}
PASSWORD = "TestPassword123!"


def _login(client, email, password=PASSWORD):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _setup(client):
    assert client.post("/api/auth/bootstrap-admin", json=SUPER).status_code == 200
    su = _login(client, SUPER["email"], SUPER["password"])
    for dept in ("cse", "ece"):
        assert client.post("/api/departments/", json={"id": dept, "name": dept.upper()}, headers=su).status_code == 200
        assert client.post("/api/years/", json={"id": f"{dept}_y1", "name": "Y1", "department_id": dept}, headers=su).status_code == 200
        assert client.post("/api/teachers/", json={"id": f"{dept}_t1", "name": "T", "department_id": dept}, headers=su).status_code == 200
    r = client.post("/api/auth/register", headers=su, json={
        "email": "cse-admin@test.edu", "password": PASSWORD, "full_name": "CSE Admin",
        "role": "DEPT_ADMIN", "department_id": "cse",
    })
    assert r.status_code == 200, r.text
    return su, _login(client, "cse-admin@test.edu")


def test_department_admin_sees_and_changes_only_their_department(client):
    su, admin = _setup(client)

    years = client.get("/api/years/", headers=admin).json()
    assert [y["id"] for y in years] == ["cse_y1"]
    # Another department's record is invisible, not just read-only.
    assert client.get("/api/years/ece_y1", headers=admin).status_code == 404
    assert client.delete("/api/years/ece_y1", headers=admin).status_code == 404
    # Asking for the other department explicitly changes nothing.
    assert [y["id"] for y in client.get("/api/years/?department_id=ece", headers=admin).json()] == ["cse_y1"]
    # Creating "in" another department is refused; a blank department means their own.
    assert client.post("/api/years/", json={"id": "x", "name": "X", "department_id": "ece"}, headers=admin).status_code == 403
    r = client.post("/api/years/", json={"id": "cse_y2", "name": "Y2"}, headers=admin)
    assert r.status_code == 200 and r.json()["department_id"] == "cse"

    # The superadmin sees every department.
    assert {y["id"] for y in client.get("/api/years/", headers=su).json()} == {"cse_y1", "cse_y2", "ece_y1"}


def test_superadmin_works_in_the_department_selected_in_the_ui(client):
    su, _admin = _setup(client)
    scoped = {**su, "X-Department-Id": "ece"}
    assert [y["id"] for y in client.get("/api/years/", headers=scoped).json()] == ["ece_y1"]
    r = client.post("/api/subjects/", json={"id": "s1", "name": "S", "type": "theory", "weekly_hours": 1}, headers=scoped)
    assert r.status_code == 200 and r.json()["department_id"] == "ece"


def test_department_admin_creates_only_hod_and_teacher_accounts_in_their_department(client):
    _su, admin = _setup(client)

    def register(**extra):
        return client.post("/api/auth/register", headers=admin, json={
            "email": f"{extra['role'].lower()}-{extra.get('teacher_id') or extra.get('department_id')}@test.edu",
            "password": PASSWORD, "full_name": "X", **extra,
        })

    assert register(role="DEPT_ADMIN", department_id="cse").status_code == 403
    assert register(role="SUPERADMIN").status_code == 403
    r = register(role="HOD", department_id="ece")  # department comes from the admin, not the payload
    assert r.status_code == 200 and r.json()["department_id"] == "cse"
    assert register(role="TEACHER", teacher_id="ece_t1").status_code == 403
    r = register(role="TEACHER", teacher_id="cse_t1")
    assert r.status_code == 200 and r.json()["department_id"] == "cse"

    listed = {u["email"] for u in client.get("/api/auth/users", headers=admin).json()}
    assert "super@test.edu" not in listed and "cse-admin@test.edu" in listed


def test_hod_runs_timetables_but_cannot_change_setup(client):
    su, admin = _setup(client)
    client.post("/api/auth/register", headers=admin, json={
        "email": "hod@test.edu", "password": PASSWORD, "full_name": "HOD", "role": "HOD",
    })
    hod = _login(client, "hod@test.edu")
    assert client.post("/api/years/", json={"id": "h", "name": "H"}, headers=hod).status_code == 403
    assert client.post("/api/import/excel/preview", headers=hod,
                       files={"file": ("x.xlsx", b"x", "application/octet-stream")}).status_code == 403
    # Generating is allowed - in their own department only.
    assert client.post("/api/timetable/generate", json={"department_id": "ece"}, headers=hod).status_code == 403


def test_teacher_sees_only_published_runs(client):
    su, admin = _setup(client)
    client.post("/api/auth/register", headers=admin, json={
        "email": "teacher@test.edu", "password": PASSWORD, "full_name": "T", "role": "TEACHER", "teacher_id": "cse_t1",
    })
    teacher = _login(client, "teacher@test.edu")
    run_id = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=admin).json()["id"]
    assert client.get("/api/timetable/runs", headers=teacher).json() == []
    assert client.get(f"/api/timetable/runs/{run_id}", headers=teacher).status_code == 404
    assert client.get(f"/api/timetable/runs/{run_id}/entries", headers=teacher).status_code == 404


def test_scoped_reset_only_clears_own_department(client):
    su, admin = _setup(client)
    assert client.post("/api/admin/data/reset/years", headers=admin).status_code == 200
    assert {y["id"] for y in client.get("/api/years/", headers=su).json()} == {"ece_y1"}


def test_first_bell_schedule_edit_copies_the_shared_schedule(client):
    su, admin = _setup(client)
    for period in (1, 2):
        client.post("/api/constraints/time-slots", headers=su, json={
            "id": f"shared_{period}", "day": "Mon", "period_index": period,
            "start_time": f"{8 + period:02d}:00", "end_time": f"{9 + period:02d}:00",
        })
    # The superadmin with no department selected created shared slots...
    shared = client.get("/api/constraints/time-slots", headers=admin).json()
    assert {s["id"] for s in shared} == {"shared_1", "shared_2"}
    # ...and CSE's first change keeps the rest of the schedule.
    r = client.post("/api/constraints/time-slots", headers=admin, json={
        "id": "cse_mon_3", "day": "Mon", "period_index": 3, "start_time": "11:00", "end_time": "12:00",
    })
    assert r.status_code == 200, r.text
    own = client.get("/api/constraints/time-slots", headers=admin).json()
    assert sorted(s["period_index"] for s in own) == [1, 2, 3]
    assert all(s["department_id"] == "cse" for s in own)
