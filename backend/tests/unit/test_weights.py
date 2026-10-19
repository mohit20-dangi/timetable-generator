import inspect

from app.solver import model_builder, priority_rules
from app.solver.weights import (
    resolve_weights, resolve_rule_params, is_must_have, SOFT_RULE_KEYS, LEVEL_WEIGHT, PRESETS,
    RULE_PARAM_DEFAULTS,
)


def test_every_soft_rule_key_is_read_by_the_model_builder():
    """A key in SOFT_RULE_KEYS that model_builder never reads would be a UI
    control that silently does nothing - CLAUDE.md forbids shipping that.
    The newer teacher/week-shape rules live in priority_rules.py, which
    model_builder calls, so either module counts as "reading" a key."""
    source = inspect.getsource(model_builder) + inspect.getsource(priority_rules)
    for key in SOFT_RULE_KEYS:
        assert f'"{key}"' in source, f"{key} is offered to admins but the solver never reads it"


def test_rule_params_default_to_two_consecutive_and_sanitise_bad_input():
    assert resolve_rule_params(None)["max_consecutive_teaching"] == 2
    assert resolve_rule_params({"max_consecutive_teaching": 3})["max_consecutive_teaching"] == 3
    for bad in (0, -1, "3", 2.5, True, None):
        assert resolve_rule_params({"max_consecutive_teaching": bad})["max_consecutive_teaching"] == 2
    assert set(resolve_rule_params({})) == set(RULE_PARAM_DEFAULTS)


def test_every_preset_only_uses_real_keys():
    for preset_name, levels in PRESETS.items():
        unknown = set(levels) - set(SOFT_RULE_KEYS)
        assert not unknown, f"preset {preset_name} references unknown keys: {unknown}"


def test_resolve_weights_fills_missing_keys_with_nice_to_have_default():
    resolved = resolve_weights({"minimize_student_gaps": "must_have"})
    assert resolved["minimize_student_gaps"] == LEVEL_WEIGHT["must_have"]
    for key in SOFT_RULE_KEYS:
        if key != "minimize_student_gaps":
            assert resolved[key] == LEVEL_WEIGHT["nice_to_have"]


def test_unknown_level_falls_back_to_nice_to_have():
    resolved = resolve_weights({"minimize_student_gaps": "not_a_real_level"})
    assert resolved["minimize_student_gaps"] == LEVEL_WEIGHT["nice_to_have"]


def test_very_important_outweighs_several_nice_to_have():
    assert LEVEL_WEIGHT["very_important"] > 3 * LEVEL_WEIGHT["nice_to_have"]


def test_is_must_have():
    levels = {"minimize_student_gaps": "must_have", "balance_load_across_days": "nice_to_have"}
    assert is_must_have(levels, "minimize_student_gaps") is True
    assert is_must_have(levels, "balance_load_across_days") is False
    assert is_must_have(levels, "unset_key") is False
