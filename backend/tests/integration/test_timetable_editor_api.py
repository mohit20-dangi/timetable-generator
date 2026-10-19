"""Manual timetable editor: conflict-gated, draft-session based."""
from app.models import GeneratedEntry, Reservation

ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "SUPERADMIN"}


def _auth(client, email=ADMIN["email"], password=ADMIN["password"]):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _build(client, dept="cse"):
    """2 days x 2 periods, 2 sections, 2 rooms, 2 one-hour theory subjects.
    t1 teaches sub1, t2 teaches sub2, t3 is qualified for sub2 only."""
    assert client.post("/api/auth/bootstrap-admin", json=ADMIN).status_code == 200
    h = _auth(client)
    client.post("/api/departments/", json={"id": dept, "institution_id": "inst1", "name": dept.upper()}, headers=h)
    for day in ("Mon", "Tue"):
        for i in (1, 2):
            client.post("/api/constraints/time-slots", json={
                "id": f"{day}_{i}", "day": day, "period_index": i,
                "start_time": f"{8 + i:02d}:00", "end_time": f"{9 + i:02d}:00",
            }, headers=h)
    client.post("/api/years/", json={"id": "y1", "name": "Y1", "department_id": dept, "num_sections": 2}, headers=h)
    for s in ("s1", "s2"):
        client.post("/api/sections/", json={"id": s, "year_id": "y1", "name": s.upper(), "strength": 30}, headers=h)
    for r in ("r1", "r2"):
        client.post("/api/rooms/", json={"id": r, "name": r.upper(), "type": "lecture", "capacity": 40, "department_id": dept}, headers=h)
    for sub in ("sub1", "sub2"):
        client.post("/api/subjects/", json={"id": sub, "name": sub.upper(), "type": "theory", "department_id": dept, "weekly_hours": 1}, headers=h)
        for s in ("s1", "s2"):
            client.post("/api/constraints/section-subjects", json={"section_id": s, "subject_id": sub}, headers=h)
    for t, subs in (("t1", ["sub1"]), ("t2", ["sub2"]), ("t3", ["sub2"])):
        client.post("/api/teachers/", json={"id": t, "name": t.upper(), "department_id": dept}, headers=h)
        for sub in subs:
            client.post(f"/api/teachers/{t}/subjects", json={"teacher_id": t, "subject_id": sub}, headers=h)
    run = client.post("/api/timetable/generate", json={"department_id": dept}, headers=h).json()
    assert client.get(f"/api/timetable/runs/{run['id']}", headers=h).json()["status"] == "completed"
    return h, run["id"]


def _entries(client, h, run_id):
    return client.get(f"/api/timetable/runs/{run_id}/entries", headers=h).json()


def _ed(run_id, path):
    return f"/api/timetable/runs/{run_id}/editor/{path}"


def _find(entries, section, subject):
    return next(e for e in entries if e["section_id"] == section and e["subject_id"] == subject)


def test_draft_forks_once_and_published_run_is_never_mutated(client):
    h, run_id = _build(client)
    assert client.post(f"/api/timetable/runs/{run_id}/publish", headers=h).status_code == 200

    draft = client.post(_ed(run_id, "draft"), headers=h).json()
    assert draft["created"] is True and draft["run"]["id"] != run_id and draft["run"]["is_published"] is False
    again = client.post(_ed(run_id, "draft"), headers=h).json()
    assert again["created"] is False and again["run"]["id"] == draft["run"]["id"]

    # Editing the published run directly is refused.
    g = _find(_entries(client, h, run_id), "s1", "sub1")["session_group"]
    r = client.post(_ed(run_id, "apply"), json={"operations": [{"type": "lock", "session_group": g}]}, headers=h)
    assert r.status_code == 409

    d = draft["run"]["id"]
    r = client.post(_ed(d, "apply"), json={"operations": [{"type": "lock", "session_group": g}]}, headers=h)
    assert r.status_code == 200, r.text
    assert _find(_entries(client, h, d), "s1", "sub1")["is_locked"] is True
    assert _find(_entries(client, h, run_id), "s1", "sub1")["is_locked"] is False


def test_conflicting_move_is_refused_and_changes_nothing(client):
    h, run_id = _build(client)
    entries = _entries(client, h, run_id)
    a, b = _find(entries, "s1", "sub1"), _find(entries, "s2", "sub1")  # same teacher t1, different slots
    assert (a["day"], a["period"]) != (b["day"], b["period"])
    body = {"operations": [{"type": "move", "session_group": a["session_group"], "day": b["day"], "period": b["period"]}]}

    check = client.post(_ed(run_id, "check"), json=body, headers=h).json()
    assert check["ok"] is False and "TEACHER_CLASH" in {v["type"] for v in check["violations"]}

    r = client.post(_ed(run_id, "apply"), json=body, headers=h)
    assert r.status_code == 409
    assert "TEACHER_CLASH" in {v["type"] for v in r.json()["detail"]["violations"]}
    after = _find(_entries(client, h, run_id), "s1", "sub1")
    assert (after["day"], after["period"]) == (a["day"], a["period"])


def test_locked_class_cannot_be_edited_until_unlocked(client):
    h, run_id = _build(client)
    g = _find(_entries(client, h, run_id), "s1", "sub1")["session_group"]

    def ap(ops):
        return client.post(_ed(run_id, "apply"), json={"operations": ops}, headers=h)

    assert ap([{"type": "lock", "session_group": g}]).status_code == 200
    r = ap([{"type": "delete", "session_group": g}])
    assert r.status_code == 409 and r.json()["detail"]["violations"][0]["type"] == "LOCKED"
    assert ap([{"type": "unlock", "session_group": g}]).status_code == 200
    assert ap([{"type": "delete", "session_group": g}]).status_code == 200


def test_unqualified_teacher_is_refused(client):
    h, run_id = _build(client)
    g = _find(_entries(client, h, run_id), "s1", "sub1")["session_group"]
    r = client.post(_ed(run_id, "apply"), json={"operations": [
        {"type": "change_teacher", "session_group": g, "teacher_id": "t3"}]}, headers=h)
    assert r.status_code == 409
    assert "TEACHER_NOT_QUALIFIED" in {v["type"] for v in r.json()["detail"]["violations"]}


def test_teacher_booked_by_a_reservation_is_refused(client, db_session):
    h, run_id = _build(client)
    a = _find(_entries(client, h, run_id), "s1", "sub1")
    other = next(s for s in (("Mon", 1), ("Mon", 2), ("Tue", 1), ("Tue", 2)) if s != (a["day"], a["period"]))
    db_session.add(Reservation(department_id="cse", resource_type="teacher", resource_id=a["teacher_id"],
                               day=other[0], period=other[1], reason="exam duty"))
    db_session.commit()
    check = client.post(_ed(run_id, "check"), json={"operations": [
        {"type": "move", "session_group": a["session_group"], "day": other[0], "period": other[1]}]}, headers=h).json()
    assert "TEACHER_BOOKED_ELSEWHERE" in {v["type"] for v in check["violations"]}


def test_delete_add_undo_redo_round_trip(client):
    h, run_id = _build(client)
    a = _find(_entries(client, h, run_id), "s1", "sub1")
    total = len(_entries(client, h, run_id))

    def ap(ops):
        return client.post(_ed(run_id, "apply"), json={"operations": ops}, headers=h)

    assert ap([{"type": "delete", "session_group": a["session_group"]}]).status_code == 200
    assert len(_entries(client, h, run_id)) == total - 1

    # Adding the same class back into the slot it just vacated is conflict-free.
    add = ap([{"type": "add", "section_id": "s1", "subject_id": "sub1", "teacher_id": a["teacher_id"],
               "room_id": a["room_id"], "day": a["day"], "period": a["period"]}])
    assert add.status_code == 200, add.text
    restored = _find(_entries(client, h, run_id), "s1", "sub1")
    assert restored["is_manual"] is True and restored["session_group"].startswith("manual:")

    hist = client.get(_ed(run_id, "history"), headers=h).json()
    assert hist["can_undo"] and not hist["can_redo"] and len(hist["items"]) == 2

    assert client.post(_ed(run_id, "undo"), headers=h).status_code == 200   # undo add
    assert len(_entries(client, h, run_id)) == total - 1
    assert client.post(_ed(run_id, "undo"), headers=h).status_code == 200   # undo delete
    assert len(_entries(client, h, run_id)) == total
    assert client.get(_ed(run_id, "history"), headers=h).json()["can_redo"]
    assert client.post(_ed(run_id, "redo"), headers=h).status_code == 200   # redo delete
    assert len(_entries(client, h, run_id)) == total - 1
    assert client.post(_ed(run_id, "undo"), headers=h).status_code == 200
    assert client.post(_ed(run_id, "undo"), headers=h).status_code == 409   # nothing left


def test_slot_map_options_and_swap_agree_with_check(client):
    h, run_id = _build(client)
    a = _find(_entries(client, h, run_id), "s1", "sub1")
    sm = client.get(_ed(run_id, "slot-map"), params={
        "session_group": a["session_group"], "view": "section", "entity_id": "s1"}, headers=h).json()
    assert len(sm["slots"]) == 4
    for slot in sm["slots"]:
        chk = client.post(_ed(run_id, "check"), json={"operations": [
            {"type": "move", "session_group": a["session_group"], "day": slot["day"], "period": slot["period"]}]}, headers=h).json()
        assert chk["ok"] == slot["ok"]
        if slot["occupant_group"]:
            sw = client.post(_ed(run_id, "check"), json={"operations": [
                {"type": "swap", "session_group_a": a["session_group"], "session_group_b": slot["occupant_group"]}]}, headers=h).json()
            assert sw["ok"] == slot["swap_ok"]
    opts = client.get(_ed(run_id, "options"), params={"session_group": a["session_group"]}, headers=h).json()
    assert [t["id"] for t in opts["teachers"]] == ["t1"]      # only t1 is qualified for sub1
    assert {r["id"] for r in opts["rooms"]} == {"r1", "r2"}


def test_publish_is_blocked_while_the_timetable_has_clashes(client, db_session):
    h, run_id = _build(client)
    a = _find(_entries(client, h, run_id), "s1", "sub1")
    db_session.add(GeneratedEntry(  # a hand-made clash the gate would never have allowed
        timetable_run_id=run_id, alternative_rank=1, session_group="bad", day=a["day"], period=a["period"],
        section_id="s2", subject_id="sub2", teacher_id=a["teacher_id"], room_id=a["room_id"]))
    db_session.commit()
    r = client.post(f"/api/timetable/runs/{run_id}/publish", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["violations"]


def test_hod_of_another_department_is_refused(client):
    h, run_id = _build(client)
    client.post("/api/departments/", json={"id": "ece", "institution_id": "inst1", "name": "ECE"}, headers=h)
    client.post("/api/auth/register", json={"email": "hod.ece@test.edu", "password": "TestPassword123!",
                                            "full_name": "ECE HOD", "role": "HOD", "department_id": "ece"}, headers=h)
    hod = _auth(client, "hod.ece@test.edu", "TestPassword123!")
    assert client.post(_ed(run_id, "draft"), headers=hod).status_code == 403
    assert client.post(_ed(run_id, "check"), json={"operations": [{"type": "lock", "session_group": "x"}]}, headers=hod).status_code == 403


def test_locked_class_keeps_its_place_through_ai_regeneration(client):
    h, run_id = _build(client)
    a = _find(_entries(client, h, run_id), "s1", "sub1")
    assert client.post(_ed(run_id, "apply"), json={"operations": [
        {"type": "lock", "session_group": a["session_group"]}]}, headers=h).status_code == 200

    regen = client.post(f"/api/timetable/runs/{run_id}/ai-apply", json={"actions": [{
        "action_type": "exclude_subject", "description": "drop sub2 for s2",
        "payload": {"section_id": "s2", "subject_id": "sub2", "exclude": True}}]}, headers=h)
    assert regen.status_code == 200, regen.text
    new_id = regen.json()["id"]
    assert client.get(f"/api/timetable/runs/{new_id}", headers=h).json()["status"] == "completed"
    kept = _find(_entries(client, h, new_id), "s1", "sub1")
    assert kept["is_locked"] is True
    assert (kept["day"], kept["period"], kept["teacher_id"], kept["room_id"]) == \
        (a["day"], a["period"], a["teacher_id"], a["room_id"])


def test_ai_editor_tools_only_propose_changes_the_gate_would_accept(client, db_session):
    import json
    from app.models import TimetableRun
    from app.services import timetable_ai_agent as agent, timetable_editor as editor

    h, run_id = _build(client)
    entries = _entries(client, h, run_id)
    a, b = _find(entries, "s1", "sub1"), _find(entries, "s2", "sub1")
    run = db_session.query(TimetableRun).filter(TimetableRun.id == run_id).first()
    ctx = editor.EditContext(db_session, run)
    actions = []

    listed = json.loads(agent._execute_tool(db_session, run, "find_classes", {"section_id": "s1"}, actions, ctx))
    assert {c["session_group"] for c in listed} == {e["session_group"] for e in entries if e["section_id"] == "s1"}

    # Same teacher already teaches s2's sub1 there: refused, nothing proposed.
    msg = agent._execute_tool(db_session, run, "propose_move", {
        "session_group": a["session_group"], "day": b["day"], "period": b["period"]}, actions, ctx)
    assert msg.startswith("NOT PROPOSED") and actions == []

    msg = agent._execute_tool(db_session, run, "propose_lock", {"session_group": a["session_group"]}, actions, ctx)
    assert msg.startswith("Proposed") and actions[0]["action_type"] == "editor_op"
    assert actions[0]["payload"]["type"] == "lock"


def test_a_batch_of_operations_is_all_or_nothing(client):
    h, run_id = _build(client)
    entries = _entries(client, h, run_id)
    good, other = _find(entries, "s1", "sub1")["session_group"], _find(entries, "s1", "sub2")["session_group"]
    # Second op is unqualified (t1 cannot teach sub2): the lock in the first op must not stick either.
    r = client.post(_ed(run_id, "apply"), json={"operations": [
        {"type": "lock", "session_group": good},
        {"type": "change_teacher", "session_group": other, "teacher_id": "t1"}]}, headers=h)
    assert r.status_code == 409
    assert _find(_entries(client, h, run_id), "s1", "sub1")["is_locked"] is False
    ok = client.post(_ed(run_id, "apply"), json={"operations": [
        {"type": "lock", "session_group": good}, {"type": "lock", "session_group": other}]}, headers=h)
    assert ok.status_code == 200
    now = _entries(client, h, run_id)
    assert _find(now, "s1", "sub1")["is_locked"] and _find(now, "s1", "sub2")["is_locked"]


def test_substitute_options_respect_qualification_and_scope(client):
    h, run_id = _build(client)
    g = _find(_entries(client, h, run_id), "s1", "sub2")["session_group"]
    for scope in ("all_sessions", "session"):
        opts = client.get(_ed(run_id, "options"), params={"session_group": g, "scope": scope}, headers=h).json()
        assert {t["id"] for t in opts["teachers"]} == {"t2", "t3"}  # t1 is not qualified for sub2


def test_hand_added_class_survives_ai_regeneration_without_adding_hours(client):
    h, run_id = _build(client)
    a = _find(_entries(client, h, run_id), "s1", "sub1")
    ap = lambda ops: client.post(_ed(run_id, "apply"), json={"operations": ops}, headers=h)
    assert ap([{"type": "delete", "session_group": a["session_group"]}]).status_code == 200
    # Put the class back by hand into the slot it just vacated.
    day, period = (a["day"], a["period"])
    assert ap([{"type": "add", "section_id": "s1", "subject_id": "sub1", "teacher_id": a["teacher_id"],
                "room_id": a["room_id"], "day": day, "period": period}]).status_code == 200
    manual = _find(_entries(client, h, run_id), "s1", "sub1")
    assert manual["session_group"].startswith("manual:")

    regen = client.post(f"/api/timetable/runs/{run_id}/ai-apply", json={"actions": [{
        "action_type": "exclude_subject", "description": "drop sub2 for s2",
        "payload": {"section_id": "s2", "subject_id": "sub2", "exclude": True}}]}, headers=h)
    assert regen.status_code == 200, regen.text
    new_id = regen.json()["id"]
    assert client.get(f"/api/timetable/runs/{new_id}", headers=h).json()["status"] == "completed"
    new = _entries(client, h, new_id)
    s1_sub1 = [e for e in new if e["section_id"] == "s1" and e["subject_id"] == "sub1"]
    assert len(s1_sub1) == 1, "the hand-added class must replace the regenerated one, not add to it"
    assert s1_sub1[0]["is_manual"] and (s1_sub1[0]["day"], s1_sub1[0]["period"]) == (day, period)
    assert client.get(f"/api/timetable/runs/{new_id}/validate", headers=h).json()["valid"] is True
