"""Translates the plain-language importance levels shown to admins into
solver penalty weights. The UI never shows a raw number - see
ConstraintProfile.soft_constraint_weights, which stores one of these level
names per rule, not an integer.
"""
from typing import Dict

IMPORTANCE_LEVELS = ["must_have", "very_important", "nice_to_have", "dont_care"]

# "must_have" is handled specially by the caller (promoted to a hard
# constraint where the rule supports it); these numbers are for the three
# levels that stay in the objective function. Chosen so that one
# "very_important" unit clearly outweighs four "nice_to_have" units,
# which is what lets a solver actually trade off between rules instead of
# them all blurring together.
LEVEL_WEIGHT = {
    "must_have": 1000,  # only reached if the rule couldn't be made hard
    "very_important": 20,
    "nice_to_have": 5,
    "dont_care": 0,
}

# Every key here MUST have a matching objective term in
# app/solver/model_builder.py::_add_soft_objective. A key that resolves to
# a weight but is never read by the model builder would be a UI control
# that silently does nothing - CLAUDE.md forbids shipping that, so the two
# lists are kept in lockstep deliberately (see
# tests/unit/test_weights.py::test_every_soft_rule_key_is_read_by_the_model_builder).
SOFT_RULE_KEYS = [
    "minimize_student_gaps",
    "balance_load_across_days",
    "teacher_preferred_slots",
    "fair_teacher_workload",
    "parallel_lab_batches",
    "avoid_edge_periods",
]

PRESETS: Dict[str, Dict[str, str]] = {
    "balanced": {key: "very_important" for key in SOFT_RULE_KEYS},
    "student_friendly": {
        "minimize_student_gaps": "must_have",
        "balance_load_across_days": "very_important",
        "avoid_edge_periods": "very_important",
        "parallel_lab_batches": "very_important",
        "teacher_preferred_slots": "nice_to_have",
        "fair_teacher_workload": "nice_to_have",
    },
    "teacher_friendly": {
        "teacher_preferred_slots": "very_important",
        "fair_teacher_workload": "very_important",
        "balance_load_across_days": "nice_to_have",
        "minimize_student_gaps": "nice_to_have",
        "parallel_lab_batches": "nice_to_have",
        "avoid_edge_periods": "nice_to_have",
    },
    "room_efficient": {
        "balance_load_across_days": "very_important",
        "parallel_lab_batches": "very_important",
        "minimize_student_gaps": "nice_to_have",
        "teacher_preferred_slots": "nice_to_have",
        "fair_teacher_workload": "nice_to_have",
        "avoid_edge_periods": "nice_to_have",
    },
}


def resolve_weights(levels: Dict[str, str]) -> Dict[str, int]:
    """levels: {rule_key: importance_level_name}. Missing keys default to
    "nice_to_have" rather than silently zero, so an admin who never touches
    a rule still gets a sane default instead of it vanishing."""
    resolved = {}
    for key in SOFT_RULE_KEYS:
        level = levels.get(key, "nice_to_have")
        if level not in LEVEL_WEIGHT:
            level = "nice_to_have"
        resolved[key] = LEVEL_WEIGHT[level]
    return resolved


def is_must_have(levels: Dict[str, str], key: str) -> bool:
    return levels.get(key) == "must_have"
