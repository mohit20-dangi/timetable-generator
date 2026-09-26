"""HOD role: can generate/edit/publish timetables for their own department
only. A HOD account scoped to one department must be refused (403) on any
run belonging to another department, and reads/writes of unrelated
departments must not be reachable through /runs listing either.
"""
ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "ADMIN"}


def _auth_headers(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _minimal_department(client, headers, dept_id, inst_id="inst1"):
    client.post("/api/institutions/", json={"id": inst_id, "name": "Test"}, headers=headers)
    client.post("/api/departments/", json={"id": dept_id, "institution_id": inst_id, "name": dept_id}, headers=headers)
    client.post("/api/years/", json={"id": f"y_{dept_id}", "name": "Y1", "department_id": dept_id}, headers=headers)
    client.post("/api/sections/", json={"id": f"sec_{dept_id}", "year_id": f"y_{dept_id}", "name": "A", "strength": 10}, headers=headers)


def test_hod_cannot_touch_another_departments_run(client):
    r = client.post("/api/auth/bootstrap-admin", json=ADMIN)
    assert r.status_code == 200, r.text
    admin_headers = _auth_headers(client, ADMIN["email"], ADMIN["password"])

    _minimal_department(client, admin_headers, "cse")
    _minimal_department(client, admin_headers, "ece")

    # A run that belongs to ECE, not CSE.
    r = client.post("/api/timetable/generate", json={"department_id": "ece"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    ece_run_id = r.json()["id"]

    reg = client.post("/api/auth/register", json={
        "email": "hod.cse@test.edu", "password": "TestPassword123!", "full_name": "CSE HOD",
        "role": "HOD", "department_id": "cse",
    }, headers=admin_headers)
    assert reg.status_code == 200, reg.text
    hod_headers = _auth_headers(client, "hod.cse@test.edu", "TestPassword123!")

    # Generating for another department is refused outright.
    gen = client.post("/api/timetable/generate", json={"department_id": "ece"}, headers=hod_headers)
    assert gen.status_code == 403

    # Reading/editing/publishing an existing ECE run is refused too.
    assert client.get(f"/api/timetable/runs/{ece_run_id}", headers=hod_headers).status_code == 403
    assert client.get(f"/api/timetable/runs/{ece_run_id}/entries", headers=hod_headers).status_code == 403
    assert client.post(f"/api/timetable/runs/{ece_run_id}/publish", headers=hod_headers).status_code == 403

    # Listing runs never leaks another department's runs to an HOD, even if
    # they explicitly ask for it via the department_id filter.
    listed = client.get("/api/timetable/runs", params={"department_id": "ece"}, headers=hod_headers).json()
    assert all(run["department_id"] == "cse" for run in listed)


def test_hod_can_generate_and_publish_own_department(client):
    r = client.post("/api/auth/bootstrap-admin", json=ADMIN)
    assert r.status_code == 200, r.text
    admin_headers = _auth_headers(client, ADMIN["email"], ADMIN["password"])

    _minimal_department(client, admin_headers, "cse")
    client.post("/api/auth/register", json={
        "email": "hod.cse2@test.edu", "password": "TestPassword123!", "full_name": "CSE HOD",
        "role": "HOD", "department_id": "cse",
    }, headers=admin_headers)
    hod_headers = _auth_headers(client, "hod.cse2@test.edu", "TestPassword123!")

    gen = client.post("/api/timetable/generate", json={"department_id": "cse"}, headers=hod_headers)
    assert gen.status_code == 200, gen.text
    run_id = gen.json()["id"]

    run = client.get(f"/api/timetable/runs/{run_id}", headers=hod_headers).json()
    assert run["status"] == "completed"

    pub = client.post(f"/api/timetable/runs/{run_id}/publish", headers=hod_headers)
    assert pub.status_code == 200, pub.text


def test_register_requires_department_for_hod(client):
    r = client.post("/api/auth/bootstrap-admin", json=ADMIN)
    assert r.status_code == 200, r.text
    admin_headers = _auth_headers(client, ADMIN["email"], ADMIN["password"])

    reg = client.post("/api/auth/register", json={
        "email": "bad.hod@test.edu", "password": "TestPassword123!", "full_name": "No Dept",
        "role": "HOD",
    }, headers=admin_headers)
    assert reg.status_code == 400


def test_admin_only_can_deactivate_users(client):
    r = client.post("/api/auth/bootstrap-admin", json=ADMIN)
    assert r.status_code == 200, r.text
    admin_headers = _auth_headers(client, ADMIN["email"], ADMIN["password"])

    _minimal_department(client, admin_headers, "cse")
    reg = client.post("/api/auth/register", json={
        "email": "hod.cse3@test.edu", "password": "TestPassword123!", "full_name": "CSE HOD",
        "role": "HOD", "department_id": "cse",
    }, headers=admin_headers)
    user_id = reg.json()["id"]

    # A non-admin cannot deactivate anyone.
    hod_headers = _auth_headers(client, "hod.cse3@test.edu", "TestPassword123!")
    assert client.patch(
        f"/api/auth/users/{user_id}/active", params={"is_active": False}, headers=hod_headers
    ).status_code == 403

    deact = client.patch(
        f"/api/auth/users/{user_id}/active", params={"is_active": False}, headers=admin_headers
    )
    assert deact.status_code == 200, deact.text

    relogin = client.post("/api/auth/login", json={"email": "hod.cse3@test.edu", "password": "TestPassword123!"})
    assert relogin.status_code == 403
