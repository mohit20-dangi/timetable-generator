from app.llm.client import claude_client

ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "SUPERADMIN"}


def _headers(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _setup(client):
    assert client.post("/api/auth/bootstrap-admin", json=ADMIN).status_code == 200
    admin = _headers(client, ADMIN["email"], ADMIN["password"])
    for dept in ("cse", "ece"):
        client.post("/api/departments/", json={"id": dept, "institution_id": "inst1", "name": dept}, headers=admin)
    for n, (email, dept) in enumerate((("f.cse@test.edu", "cse"), ("f2.cse@test.edu", "cse"), ("f.ece@test.edu", "ece"))):
        tid = f"t{n}"
        t = client.post("/api/teachers/", json={"id": tid, "name": f"Teacher {n}", "department_id": dept}, headers=admin)
        assert t.status_code == 200, t.text
        r = client.post("/api/auth/register", json={
            "email": email, "password": "TestPassword123!", "full_name": email,
            "role": "TEACHER", "department_id": dept, "teacher_id": tid,
        }, headers=admin)
        assert r.status_code == 200, r.text
    r = client.post("/api/rooms/", json={"id": "sem1", "name": "Seminar Hall", "type": "seminar", "capacity": 100}, headers=admin)
    assert r.status_code == 200, r.text
    return admin


SPEC = {"mode": "free_slots", "days": ["Thu"], "room_types": ["seminar"]}


def test_saved_filter_crud_and_department_visibility(client):
    _setup(client)
    cse = _headers(client, "f.cse@test.edu", "TestPassword123!")
    cse2 = _headers(client, "f2.cse@test.edu", "TestPassword123!")
    ece = _headers(client, "f.ece@test.edu", "TestPassword123!")

    created = client.post("/api/custom-filters/saved", json={"name": "Seminar slots", "spec": SPEC}, headers=cse)
    assert created.status_code == 200, created.text
    fid = created.json()["id"]
    assert created.json()["department_id"] == "cse"

    assert [f["id"] for f in client.get("/api/custom-filters/saved", headers=cse2).json()] == [fid]
    assert client.get("/api/custom-filters/saved", headers=ece).json() == []

    assert client.delete(f"/api/custom-filters/saved/{fid}", headers=cse2).status_code == 403
    assert client.delete(f"/api/custom-filters/saved/{fid}", headers=cse).status_code == 200
    assert client.get("/api/custom-filters/saved", headers=cse).json() == []


def test_faculty_cannot_target_a_run_but_can_evaluate_published(client):
    _setup(client)
    cse = _headers(client, "f.cse@test.edu", "TestPassword123!")
    assert client.post("/api/custom-filters/evaluate", json={"spec": SPEC, "run_id": 1}, headers=cse).status_code == 403
    ok = client.post("/api/custom-filters/evaluate", json={"spec": SPEC}, headers=cse)
    assert ok.status_code == 200 and ok.json() == {"cells": []}


def test_parse_drops_ids_the_model_invented(client, monkeypatch):
    admin = _setup(client)
    monkeypatch.setattr(claude_client, "parse_filter_query", lambda q, catalog: {
        "title": "Seminar slots", "explanation": "x", "unsupported": [],
        "spec": {"mode": "free_slots", "teacher_ids": ["ghost", "$me"], "room_types": ["seminar", "dome"]},
    })
    r = client.post("/api/custom-filters/parse", json={"query": "when can I hold a seminar"}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["spec"]["teacher_ids"] == ["$me"]
    assert body["spec"]["room_types"] == ["seminar"]
    assert sorted(body["dropped_ids"]) == ["room_types: dome", "teacher_ids: ghost"]
