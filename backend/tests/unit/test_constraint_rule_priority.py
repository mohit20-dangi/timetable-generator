"""The priority of some structured rule types isn't the admin's choice:
"unavailable" means never (hard) and "prefers" is always a soft nudge. A row
that says otherwise (an old soft "unavailable", or an AI-proposed one) is
corrected on load rather than rejected."""
import pytest

from app.schemas.constraint_rule import ConstraintRuleCreate


def _rule(rule_type, target_type, **overrides):
    data = dict(
        id="r1", department_id="d1", rule_type=rule_type, target_type=target_type,
        target_id="x", day="Mon", start_time="09:00", end_time="10:00",
    )
    data.update(overrides)
    return ConstraintRuleCreate(**data)


@pytest.mark.parametrize("rule_type,target_type", [("teacher_unavailable", "teacher"), ("room_unavailable", "room")])
def test_unavailable_is_always_hard(rule_type, target_type):
    rule = _rule(rule_type, target_type, priority="soft", weight=10)
    assert rule.priority == "hard"
    assert rule.weight == 0


def test_teacher_preferred_is_always_soft_with_no_per_rule_weight():
    rule = _rule("teacher_preferred", "teacher", priority="hard", weight=7)
    assert rule.priority == "soft"
    assert rule.weight == 0


def test_section_unavailable_keeps_the_admins_choice():
    rule = _rule("section_unavailable", "section", priority="soft", weight=10)
    assert (rule.priority, rule.weight) == ("soft", 10)
