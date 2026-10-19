"""Repeater sections (sit in other sections' classes) and the remedial
timetable (extra classes built around the published main timetable)."""
from collections import Counter

ADMIN = {"email": "admin@test.edu", "password": "TestPassword123!", "full_name": "Admin", "role": "SUPERADMIN"}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
REGULAR_TIMES = [("09:00", "09:50"), ("09:50", "10:40"), ("10:40", "11:30"), ("11:30", "12:20")]
REMEDIAL_TIMES = [("15:00", "15:50"), ("15:50", "16:40")]


def _login(client):
    assert client.post("/api/auth/bootstrap-admin", json=ADMIN).status_code == 200
    r = client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _post(client, headers, url, body):
    r = client.post(url, json=body, headers=headers)
    assert r.status_code == 200, f"{url}: {r.text}"
    return r


def _build_department(client, h):
    _post(client, h, "/api/departments/", {"id": "cse", "institution_id": "inst1", "name": "CSE"})
    for day in DAYS:
        for i, (start, end) in enumerate(REGULAR_TIMES, start=1):
            _post(client, h, "/api/constraints/time-slots", {
                "id": f"{day}_{i}", "day": day, "period_index": i, "start_time": start, "end_time": end,
            })
    _post(client, h, "/api/years/", {"id": "y3", "name": "III Year", "department_id": "cse", "num_sections": 3})
    for sid, name, repeater in [("sec_a", "A", False), ("sec_b", "B", False), ("sec_r", "R", True)]:
        _post(client, h, "/api/sections/", {
            "id": sid, "year_id": "y3", "name": name, "strength": 30, "is_repeater": repeater,
        })
    for room in ["lt1", "lt2", "lt3", "lt4"]:
        _post(client, h, "/api/rooms/", {"id": room, "name": room, "type": "lecture", "capacity": 80, "department_id": "cse"})

    for teacher in ["t1", "t2", "t3"]:
        _post(client, h, "/api/teachers/", {"id": teacher, "name": teacher, "department_id": "cse"})
    for subject, hours, teacher in [("ds", 3, "t1"), ("os", 3, "t2"), ("maths", 3, "t3"), ("own", 2, "t1")]:
        _post(client, h, "/api/subjects/", {
            "id": subject, "name": subject.upper(), "type": "theory", "department_id": "cse",
            "weekly_hours": hours, "max_per_day": 1,
        })
        _post(client, h, f"/api/teachers/{teacher}/subjects", {"teacher_id": teacher, "subject_id": subject})

    def assign(section, subject, **extra):
        _post(client, h, "/api/constraints/section-subjects", {"section_id": section, "subject_id": subject, **extra})

    assign("sec_a", "ds")
    assign("sec_a", "maths")
    assign("sec_b", "os")
    assign("sec_b", "maths")
    assign("sec_r", "ds", attends_with_section_id="sec_a")
    assign("sec_r", "os", attends_with_section_id="sec_b")
    assign("sec_r", "own")


def _generate_and_publish(client, h):
    run_id = _post(client, h, "/api/timetable/generate", {"department_id": "cse"}).json()["id"]
    run = client.get(f"/api/timetable/runs/{run_id}", headers=h).json()
    assert run["status"] == "completed", run.get("llm_explanation")
    _post(client, h, f"/api/timetable/runs/{run_id}/publish", {})
    return run_id


def _entries(client, h, run_id):
    return client.get(f"/api/timetable/runs/{run_id}/entries", headers=h).json()


def test_repeater_section_is_clash_free_across_its_host_classes(client):
    h = _login(client)
    _build_department(client, h)
    run_id = _generate_and_publish(client, h)
    entries = _entries(client, h, run_id)

    # The repeater has no class of its own for ds/os: it sits in A's and B's.
    assert not [e for e in entries if e["section_id"] == "sec_r" and e["subject_id"] in ("ds", "os")]
    assert client.get(f"/api/timetable/runs/{run_id}/validate", headers=h).json()["valid"]

    attended = [
        e for e in entries
        if (e["section_id"] == "sec_a" and e["subject_id"] == "ds")
        or (e["section_id"] == "sec_b" and e["subject_id"] == "os")
        or e["section_id"] == "sec_r"
    ]
    slots = Counter((e["day"], e["period"]) for e in attended)
    assert all(count == 1 for count in slots.values()), "repeater double-booked"
    assert len(attended) == 3 + 3 + 2

    # The repeater's own timetable shows the classes it sits in, tagged with the host section.
    publish_view = client.get("/api/timetable/public/section/sec_r/view").json()
    blocks = [b for cell in publish_view["cells"] for b in cell["blocks"]]
    assert sum(1 for b in blocks if any(line == "with A" for line in b)) == 3
    assert sum(1 for b in blocks if any(line == "with B" for line in b)) == 3
    assert sum(1 for b in blocks if not any(str(line).startswith("with ") for line in b)) == 2


def test_repeater_attendance_is_validated(client):
    h = _login(client)
    _build_department(client, h)
    url = "/api/constraints/section-subjects/{}/{}/attends-with"

    def attend(section, subject, host):
        return client.put(url.format(section, subject), json={"attends_with_section_id": host}, headers=h)

    assert attend("sec_a", "maths", "sec_b").status_code == 200  # sec_b teaches maths itself
    # attendance never chains: sec_a now attends sec_b for maths, so sec_r cannot attend sec_a for it
    client.post("/api/constraints/section-subjects", json={"section_id": "sec_r", "subject_id": "maths"}, headers=h)
    r = attend("sec_r", "maths", "sec_a")
    assert r.status_code == 400 and "attends" in r.json()["detail"]
    # the host must actually teach the subject
    assert attend("sec_r", "own", "sec_b").status_code == 400
    # a section cannot attend itself
    assert attend("sec_a", "ds", "sec_a").status_code == 400


def _add_remedial_slots(client, h):
    for day in DAYS:
        for i, (start, end) in enumerate(REMEDIAL_TIMES, start=5):
            _post(client, h, "/api/constraints/time-slots", {
                "id": f"R_{day}_{i}", "day": day, "period_index": i, "start_time": start, "end_time": end,
                "slot_kind": "remedial",
            })
    for i, (start, end) in enumerate([("09:00", "09:50"), ("09:50", "10:40")], start=1):
        _post(client, h, "/api/constraints/time-slots", {
            "id": f"R_Sat_{i}", "day": "Sat", "period_index": i, "start_time": start, "end_time": end,
            "slot_kind": "remedial",
        })


def _group(client, h, group_id, subject, sections, periods, strength=20, **extra):
    _post(client, h, "/api/remedial/groups", {
        "id": group_id, "name": group_id, "subject_id": subject, "section_ids": sections,
        "strength": strength, "periods_per_week": periods, "department_id": "cse", **extra,
    })


def test_remedial_slots_never_leak_into_the_main_timetable(client):
    h = _login(client)
    _build_department(client, h)
    _add_remedial_slots(client, h)
    run_id = _generate_and_publish(client, h)
    assert {e["period"] for e in _entries(client, h, run_id)} <= {1, 2, 3, 4}
    regular = client.get("/api/constraints/time-slots?department_id=cse", headers=h).json()
    assert all(s["slot_kind"] == "regular" for s in regular)
    everything = client.get("/api/constraints/time-slots?department_id=cse&kind=all", headers=h).json()
    assert any(s["slot_kind"] == "remedial" for s in everything)


def test_remedial_is_built_around_the_main_timetable(client):
    h = _login(client)
    _build_department(client, h)
    _add_remedial_slots(client, h)
    main_run = _generate_and_publish(client, h)
    main_before = sorted((e["day"], e["period"], e["section_id"], e["subject_id"], e["teacher_id"], e["room_id"])
                         for e in _entries(client, h, main_run))

    _group(client, h, "g_ds_a", "ds", ["sec_a"], 3)
    _group(client, h, "g_maths_ab", "maths", ["sec_a", "sec_b"], 2, strength=30)
    run_id = _post(client, h, "/api/remedial/runs", {"department_id": "cse"}).json()["id"]
    run = client.get(f"/api/remedial/runs/{run_id}", headers=h).json()
    assert run["status"] == "completed", run["explanation"]
    entries = client.get(f"/api/remedial/runs/{run_id}/entries", headers=h).json()
    assert Counter(e["group_id"] for e in entries) == {"g_ds_a": 3, "g_maths_ab": 2}

    main = _entries(client, h, main_run)
    # 1. nothing the member sections, teachers or rooms already have
    for e in entries:
        slot = (e["day"], e["period"])
        group_sections = ["sec_a"] if e["group_id"] == "g_ds_a" else ["sec_a", "sec_b"]
        assert not [m for m in main if (m["day"], m["period"]) == slot and m["section_id"] in group_sections]
        assert not [m for m in main if (m["day"], m["period"]) == slot and m["teacher_id"] == e["teacher_id"]]
        assert not [m for m in main if (m["day"], m["period"]) == slot and m["room_id"] == e["room_id"]]
    # 2. at most two remedial periods a day for any section, whatever the subject
    per_section_day = Counter()
    for e in entries:
        for sid in (["sec_a"] if e["group_id"] == "g_ds_a" else ["sec_a", "sec_b"]):
            per_section_day[(sid, e["day"])] += 1
    assert max(per_section_day.values()) <= 2
    #    ...and one a day when the week has room for it (5 periods over 6 days here)
    assert max(per_section_day.values()) == 1
    # 3. the main timetable is untouched
    main_after = sorted((e["day"], e["period"], e["section_id"], e["subject_id"], e["teacher_id"], e["room_id"])
                        for e in _entries(client, h, main_run))
    assert main_before == main_after
    # 4. never in the middle of the students' day: either a remedial-only slot or a free
    #    period after the member sections' last main class that day; regular teacher kept
    for e in entries:
        if e["in_remedial_slot"]:
            continue
        for sid in (["sec_a"] if e["group_id"] == "g_ds_a" else ["sec_a", "sec_b"]):
            last_main = max((m["period"] for m in main if m["section_id"] == sid and m["day"] == e["day"]), default=0)
            assert e["period"] > last_main
    assert {e["teacher_id"] for e in entries if e["group_id"] == "g_ds_a"} == {"t1"}

    assert client.get(f"/api/remedial/runs/{run_id}/section-view", headers=h).json()["sections"]
    export = client.get(f"/api/remedial/runs/{run_id}/export", headers=h)
    assert export.status_code == 200 and export.content[:2] == b"PK"


def test_remedial_uses_free_main_timetable_periods_when_no_remedial_slots_exist(client):
    h = _login(client)
    _build_department(client, h)
    main_run = _generate_and_publish(client, h)
    _group(client, h, "g_maths_a", "maths", ["sec_a"], 3)
    run_id = _post(client, h, "/api/remedial/runs", {"department_id": "cse"}).json()["id"]
    run = client.get(f"/api/remedial/runs/{run_id}", headers=h).json()
    assert run["status"] == "completed", run["explanation"]
    entries = client.get(f"/api/remedial/runs/{run_id}/entries", headers=h).json()
    assert len(entries) == 3 and not any(e["in_remedial_slot"] for e in entries)
    main = _entries(client, h, main_run)
    busy = {(m["day"], m["period"]) for m in main if m["section_id"] == "sec_a"}
    assert not {(e["day"], e["period"]) for e in entries} & busy


def test_remedial_explains_why_it_cannot_run(client):
    h = _login(client)
    _build_department(client, h)
    _group(client, h, "g1", "maths", ["sec_a"], 2)
    run_id = _post(client, h, "/api/remedial/runs", {"department_id": "cse"}).json()["id"]
    run = client.get(f"/api/remedial/runs/{run_id}", headers=h).json()
    assert run["status"] == "failed" and "published main timetable" in run["explanation"]

    _generate_and_publish(client, h)
    # one group wants more periods a week than the per-day limit allows
    _group(client, h, "g2", "ds", ["sec_a"], 12)
    run_id = _post(client, h, "/api/remedial/runs", {
        "department_id": "cse", "settings": {"hard_max_per_day": 2},
    }).json()["id"]
    run = client.get(f"/api/remedial/runs/{run_id}", headers=h).json()
    assert run["status"] == "failed" and "remedial periods a week" in run["explanation"]
