"""The tool-calling agent behind "for all teachers, increase max hours by
2" style instructions.

Hard boundary, unconditional: the agent NEVER writes to the database
directly. Every tool it can call either reads data (find_teachers) or
RECORDS a proposed action into a plan (propose_*) - nothing more. The
proposed plan is shown to the admin, who reviews and can edit or drop any
action, and only POST /api/ai/agent/apply - a separate endpoint, called
with the admin's approved action list, never by the model - actually
writes anything, and every write it makes is recorded in AuditLog with
the original instruction as the reason. This mirrors exactly why the
solver, not the LLM, is the only thing ever allowed to emit a schedule:
an AI that can silently mutate institutional data one instruction away
from a typo is not a feature worth shipping.
"""
import json
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Teacher

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

MAX_TOOL_ITERATIONS = 6

TOOLS = [
    {
        "name": "find_teachers",
        "description": "List teachers in this department, optionally filtered by a substring of their name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name_contains": {"type": "string", "description": "Optional case-insensitive substring filter."},
            },
        },
    },
    {
        "name": "propose_update_teacher_limits",
        "description": (
            "Propose changing one numeric limit for a set of teachers. Does NOT apply the change - "
            "it only adds it to the plan for the admin to review. Use teacher ids returned by "
            "find_teachers, never invented ones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "teacher_ids": {"type": "array", "items": {"type": "string"}},
                "field": {
                    "type": "string",
                    "enum": ["max_daily_classes", "max_weekly_hours", "max_continuous_classes"],
                },
                "delta": {"type": "integer", "description": "Add this amount to the current value (use this OR new_value, not both)."},
                "new_value": {"type": "integer", "description": "Set the field to exactly this value (use this OR delta, not both)."},
            },
            "required": ["teacher_ids", "field"],
        },
    },
    {
        "name": "propose_constraint_rule",
        "description": (
            "Propose a new scheduling constraint (e.g. 'Prof Sharma is unavailable Friday afternoons'). "
            "Does NOT apply it - only adds it to the plan for review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_type": {
                    "type": "string",
                    "enum": ["teacher_unavailable", "room_unavailable", "section_unavailable", "teacher_preferred", "custom"],
                },
                "target_type": {"type": "string", "enum": ["teacher", "room", "section", "subject"]},
                "target_id": {"type": "string"},
                "day": {"type": ["string", "null"], "enum": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", None]},
                "start_time": {"type": ["string", "null"], "description": "HH:MM or null"},
                "end_time": {"type": ["string", "null"], "description": "HH:MM or null"},
                "priority": {"type": "string", "enum": ["hard", "soft"]},
                "description": {"type": "string"},
            },
            "required": ["rule_type", "target_type", "target_id", "priority", "description"],
        },
    },
]

SYSTEM_PROMPT = """You are a scheduling assistant for a university timetable admin. You can look up \
teachers and propose changes, but you can NEVER apply anything directly - every proposal goes through \
`propose_update_teacher_limits` or `propose_constraint_rule`, and the admin reviews it before it takes \
effect. Always call `find_teachers` first if the instruction refers to teachers you don't already have \
ids for - never invent an id. If the instruction is ambiguous or refers to something you can't find, \
say so plainly in your final response instead of guessing. When you're done proposing everything the \
instruction asked for, write a short plain-English summary of what you proposed and why."""


def _apply_teacher_filter(db: Session, department_id: str, name_contains: str = None) -> List[Dict[str, Any]]:
    query = db.query(Teacher).filter(Teacher.department_id == department_id)
    if name_contains:
        query = query.filter(Teacher.name.ilike(f"%{name_contains}%"))
    return [
        {
            "id": t.id, "name": t.name, "max_daily_classes": t.max_daily_classes,
            "max_weekly_hours": t.max_weekly_hours, "max_continuous_classes": t.max_continuous_classes,
        }
        for t in query.all()
    ]


def run_agent_plan(db: Session, department_id: str, instruction: str) -> Dict[str, Any]:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured. The AI assistant is disabled until an operator sets it.")
    if anthropic is None:
        raise RuntimeError("The anthropic package is not installed.")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    actions: List[Dict[str, Any]] = []
    messages = [{"role": "user", "content": f"Department: {department_id}\nInstruction: {instruction}"}]

    final_text = ""
    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=settings.ANTHROPIC_MODEL, max_tokens=2048,
            system=SYSTEM_PROMPT, tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
            break

        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            result_text = _execute_tool(db, department_id, block.name, block.input, actions)
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})
        messages.append({"role": "user", "content": tool_results})
    else:
        final_text = "Reached the maximum number of steps for this instruction; review the proposals below."

    return {"summary": final_text or "No changes were proposed.", "actions": actions}


def _execute_tool(db: Session, department_id: str, name: str, tool_input: Dict[str, Any], actions: List[Dict[str, Any]]) -> str:
    if name == "find_teachers":
        results = _apply_teacher_filter(db, department_id, tool_input.get("name_contains"))
        return json.dumps(results)

    if name == "propose_update_teacher_limits":
        teacher_ids = tool_input["teacher_ids"]
        field = tool_input["field"]
        delta = tool_input.get("delta")
        new_value = tool_input.get("new_value")
        teachers = db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all()
        for teacher in teachers:
            old = getattr(teacher, field)
            target = new_value if new_value is not None else old + (delta or 0)
            actions.append({
                "action_type": "update_teacher_limits",
                "description": f"{teacher.name}: {field} {old} -> {target}",
                "payload": {"teacher_id": teacher.id, "field": field, "old_value": old, "new_value": target},
            })
        return f"Proposed updating {field} for {len(teachers)} teacher(s)."

    if name == "propose_constraint_rule":
        rule_id = f"ai_{len(actions) + 1}_{tool_input['target_id']}"
        actions.append({
            "action_type": "create_constraint_rule",
            "description": tool_input.get("description", "New constraint rule"),
            "payload": {**tool_input, "id": rule_id, "department_id": department_id, "source": "ai_parsed"},
        })
        return "Proposed a new constraint rule."

    return f"Unknown tool: {name}"
