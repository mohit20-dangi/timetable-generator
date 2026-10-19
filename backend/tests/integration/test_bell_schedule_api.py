"""The bell schedule is saved whole: the server numbers periods (regular
first, then remedial) and refuses overlaps without touching the old schedule."""
from tests.integration.test_department_roles import _setup


def _p(day, start, end, kind="regular"):
    return {"day": day, "start_time": start, "end_time": end, "slot_kind": kind}


def test_replace_numbers_regular_then_remedial(client):
    su, admin = _setup(client)
    body = {"periods": [
        _p("Mon", "17:00", "18:00", "remedial"),
        _p("Mon", "10:00", "11:00"),
        _p("Mon", "09:00", "10:00"),
    ]}
    r = client.put("/api/constraints/time-slots", json=body, headers=admin)
    assert r.status_code == 200, r.text
    assert [(s["period_index"], s["start_time"][:5], s["slot_kind"]) for s in r.json()] == [
        (1, "09:00", "regular"), (2, "10:00", "regular"), (3, "17:00", "remedial"),
    ]
    listed = client.get("/api/constraints/time-slots?kind=all", headers=admin).json()
    assert len(listed) == 3


def test_overlap_is_rejected_and_old_schedule_kept(client):
    su, admin = _setup(client)
    assert client.put("/api/constraints/time-slots", json={"periods": [_p("Mon", "09:00", "10:00")]}, headers=admin).status_code == 200
    r = client.put("/api/constraints/time-slots", json={"periods": [_p("Mon", "09:00", "10:00"), _p("Mon", "09:30", "10:30")]}, headers=admin)
    assert r.status_code == 400 and "overlaps" in r.json()["detail"]
    listed = client.get("/api/constraints/time-slots?kind=all", headers=admin).json()
    assert [(s["start_time"][:5], s["end_time"][:5]) for s in listed] == [("09:00", "10:00")]


def test_replace_only_touches_own_department(client):
    su, admin = _setup(client)
    client.put("/api/constraints/time-slots", json={"department_id": "ece", "periods": [_p("Tue", "09:00", "10:00")]}, headers=su)
    client.put("/api/constraints/time-slots", json={"periods": [_p("Mon", "09:00", "10:00")]}, headers=admin)
    ece = client.get("/api/constraints/time-slots?department_id=ece&kind=all", headers=su).json()
    assert [s["day"] for s in ece] == ["Tue"]


def test_update_edits_time_and_renumbers(client):
    su, admin = _setup(client)
    slots = client.put("/api/constraints/time-slots", json={"periods": [_p("Mon", "09:00", "10:00"), _p("Mon", "10:00", "11:00")]}, headers=admin).json()
    r = client.put(f"/api/constraints/time-slots/{slots[0]['id']}", json={"day": "Mon", "period_index": 1, "start_time": "11:00", "end_time": "12:00"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["period_index"] == 2
    # Ids follow the new numbering: cse_Mon_1 is now 10:00, cse_Mon_2 is 11:00.
    bad = client.put("/api/constraints/time-slots/cse_Mon_1", json={"day": "Mon", "period_index": 1, "start_time": "10:30", "end_time": "11:30"}, headers=admin)
    assert bad.status_code == 400 and "overlaps" in bad.json()["detail"]
