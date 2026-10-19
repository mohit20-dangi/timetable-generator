from datetime import time
from types import SimpleNamespace as NS

from app.schemas.custom_filter import FilterSpec
from app.services.custom_filter import evaluate

SLOTS = [
    {"day": d, "period_index": p, "start_time": time(9 + p - 1), "end_time": time(9 + p)}
    for d in ("Mon", "Tue") for p in (1, 2, 3)
]
ROOMS = {
    "r1": NS(id="r1", name="Hall", type="seminar", capacity=100, availability=[]),
    "r2": NS(id="r2", name="Class", type="lecture", capacity=40, availability=[]),
}
TEACHERS = {
    "t1": NS(id="t1", availability=[]),
    "t2": NS(id="t2", availability=[{"day": "Mon", "start": "09:00", "end": "10:00"}]),
}
SUBJECTS = {"s1": NS(id="s1", type="theory"), "s2": NS(id="s2", type="lab")}


def E(day, period, teacher="t1", section="A", room="r2", subject="s1", batch=None):
    return NS(day=day, period=period, teacher_id=teacher, section_id=section, batch_id=batch,
              room_id=room, subject_id=subject)


def run(spec, entries, external=(), batches=None, me=None):
    return evaluate(FilterSpec(**spec), entries, external, SLOTS, ROOMS, TEACHERS, SUBJECTS,
                    batches or {}, me_teacher_id=me)


def slots_of(cells):
    return {(c["day"], c["period"]) for c in cells}


def test_classes_and_across_fields_or_within():
    entries = [E("Mon", 1), E("Mon", 2, teacher="t2"), E("Tue", 1, section="B")]
    assert slots_of(run({"teacher_ids": ["t1", "t2"]}, entries)) == {("Mon", 1), ("Mon", 2), ("Tue", 1)}
    assert slots_of(run({"teacher_ids": ["t1", "t2"], "section_ids": ["A"]}, entries)) == {("Mon", 1), ("Mon", 2)}
    assert slots_of(run({"subject_types": ["lab"]}, entries)) == set()


def test_section_filter_catches_lab_batch_entries():
    entries = [E("Mon", 1, section=None, batch="b1")]
    assert slots_of(run({"section_ids": ["A"]}, entries, batches={"b1": "A"})) == {("Mon", 1)}
    assert run({"section_ids": ["A"]}, entries) == []


def test_day_and_time_window():
    entries = [E("Mon", 1), E("Mon", 3), E("Tue", 1)]
    spec = {"days": ["Mon"], "time_from": "11:00"}
    assert slots_of(run(spec, entries)) == {("Mon", 3)}


def test_me_resolution():
    entries = [E("Mon", 1), E("Mon", 2, teacher="t2")]
    assert slots_of(run({"teacher_ids": ["$me"]}, entries, me="t2")) == {("Mon", 2)}
    assert run({"teacher_ids": ["$me"]}, entries, me=None) == []


def test_free_slots_teachers_and_sections():
    entries = [E("Mon", 1, teacher="t1", section="A"), E("Mon", 2, teacher="t2", section="B")]
    spec = {"mode": "free_slots", "teacher_ids": ["t1"], "section_ids": ["B"], "days": ["Mon"]}
    # t1 busy Mon-1, section B busy Mon-2 -> only Mon-3 free.
    assert slots_of(run(spec, entries)) == {("Mon", 3)}


def test_free_slots_respect_teacher_availability_window():
    # t2 is only available Mon 09:00-10:00 (period 1).
    spec = {"mode": "free_slots", "teacher_ids": ["t2"]}
    assert slots_of(run(spec, [])) == {("Mon", 1)}


def test_free_slots_need_matching_free_room():
    entries = [E("Mon", 1, room="r1")]
    spec = {"mode": "free_slots", "room_types": ["seminar"], "days": ["Mon"]}
    cells = run(spec, entries)
    assert slots_of(cells) == {("Mon", 2), ("Mon", 3)}
    assert [r.id for r in cells[0]["free_rooms"]] == ["r1"]
    assert run({**spec, "min_room_capacity": 500}, entries) == []


def test_external_busy_blocks_rooms_but_is_not_shown():
    external = [E("Mon", 2, room="r1", teacher="t9", section="Z")]
    spec = {"mode": "free_slots", "room_ids": ["r1"], "days": ["Mon"]}
    assert slots_of(run(spec, [], external)) == {("Mon", 1), ("Mon", 3)}
