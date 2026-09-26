"""The tool-calling agent behind "remove Cloud Computing", "give DBMS one
more class a week for section B" style instructions on an already-generated
timetable run.

Same hard boundary as app/services/ai_agent.py: this agent NEVER writes to
the database and NEVER regenerates anything itself. Every tool it can call
either reads data (find_subjects) or RECORDS a proposed action into a plan
(propose_*) - nothing more. The admin reviews the plan, and only
POST /runs/{run_id}/ai-apply - called with the admin's approved action list,
never by the model - actually creates a new run and kicks off the solver.

What the proposed actions become, deliberately: a TimetableRun.subject_overrides
entry (see that column's docstring) - never a change to Subject.weekly_hours
or SectionSubject. "Remove/add a class for this timetable" is a one-off
request about THIS run, not a curriculum change, so the institution's real
subject data is untouched; only the next solve of this run's lineage sees
the override. This is also why there's no "move" tool here - the solver has
no notion of "avoid this slot for this subject" to feed a regeneration, so
moving an already-placed class stays the deterministic, conflict-checked
EditEntryModal / POST /runs/{run_id}/edit path instead of going through the
solver at all.
"""
import json
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Subject, SectionSubject, Section
from app.solver.data_loader import _resolve_target_sections

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

MAX_TOOL_ITERATIONS = 10

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_subjects",
            "description": (
                "List subjects actually taught within this timetable's scope, with the section(s) "
                "teaching each and its current hours/week. Optionally filtered by a substring of the "
                "subject's name. Always call this before proposing anything - never invent a subject "
                "or section id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_contains": {"type": "string", "description": "Optional case-insensitive substring filter on subject name."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_exclude_subject",
            "description": (
                "Propose dropping a subject entirely from a specific section, ONLY for this timetable "
                "- does NOT touch the subject's actual configured hours or its assignment to the "
                "section elsewhere in the system. Does NOT apply anything - only adds it to the plan "
                "for the admin to review. Call once per (section, subject) pair; if the instruction "
                "doesn't name a specific section, call it for every section find_subjects showed "
                "teaching that subject."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "subject_id": {"type": "string"},
                },
                "required": ["section_id", "subject_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_change_weekly_hours",
            "description": (
                "Propose changing how many hours/week a subject gets for a specific section, ONLY for "
                "this timetable - does NOT change the subject's actual configured hours/week anywhere "
                "else. Does NOT apply anything - only adds it to the plan for the admin to review. Use "
                "delta for 'one more/one fewer class' style requests, new_value for an exact count. "
                "Call once per (section, subject) pair; if the instruction doesn't name a specific "
                "section, call it for every section find_subjects showed teaching that subject."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "subject_id": {"type": "string"},
                    "delta": {"type": "integer", "description": "Add this amount to the current hours/week (use this OR new_value, not both)."},
                    "new_value": {"type": "integer", "description": "Set hours/week to exactly this value (use this OR delta, not both)."},
                },
                "required": ["section_id", "subject_id"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are a scheduling assistant that edits ONE already-generated university timetable. \
You can look up the subjects actually taught within it and propose changes, but you can NEVER apply \
anything directly - every proposal goes through `propose_exclude_subject` or \
`propose_change_weekly_hours`, and the admin reviews it before a new version of the timetable is \
generated. Always call `find_subjects` first to get real subject/section ids - never invent one. If \
the instruction is ambiguous or refers to a subject you can't find, say so plainly in your final \
response instead of guessing.

You cannot move an already-placed class to a different day/time here - say so in your final response \
and suggest the admin use the "Move Class" action on that class directly instead.

The instruction may ask for more than one change (e.g. "remove X and give Y one more class") - propose \
every part of it, one tool call per (section, subject) pair. When you're done, write a short \
plain-English summary of what you proposed and why."""


def _list_subjects_in_scope(db: Session, run, name_contains: str = None) -> List[Dict[str, Any]]:
    sections = _resolve_target_sections(db, run.department_id, run.year_ids, run.section_ids)
    section_by_id = {s.id: s for s in sections}
    if not section_by_id:
        return []
    rows = (
        db.query(SectionSubject)
        .filter(SectionSubject.section_id.in_(section_by_id.keys()))
        .all()
    )
    subject_ids = {row.subject_id for row in rows}
    subjects_by_id = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()}

    override_by_pair = {
        (o["section_id"], o["subject_id"]): o for o in (run.subject_overrides or [])
    }

    results = []
    for row in rows:
        subject = subjects_by_id.get(row.subject_id)
        section = section_by_id.get(row.section_id)
        if not subject or not section:
            continue
        if name_contains and name_contains.lower() not in subject.name.lower():
            continue
        override = override_by_pair.get((row.section_id, row.subject_id))
        results.append({
            "subject_id": subject.id,
            "subject_name": subject.name,
            "section_id": section.id,
            "section_name": section.name,
            "weekly_hours": subject.weekly_hours,
            "already_excluded_for_this_timetable": bool(override and override.get("exclude")),
            "already_overridden_weekly_hours_for_this_timetable": (
                override.get("weekly_hours") if override else None
            ),
        })
    return results


def run_timetable_edit_plan(db: Session, run, instruction: str) -> Dict[str, Any]:
    if not settings.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is not configured. The AI assistant is disabled until an operator sets it.")
    if OpenAI is None:
        raise RuntimeError("The openai package is not installed.")

    client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
    actions: List[Dict[str, Any]] = []
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Timetable run: #{run.id}\nInstruction: {instruction}"},
    ]

    final_text = ""
    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.chat.completions.create(
            model=settings.LLM_MODEL, max_tokens=2048,
            tools=TOOLS, messages=messages,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            final_text = message.content or ""
            break

        for tool_call in message.tool_calls:
            tool_input = json.loads(tool_call.function.arguments or "{}")
            result_text = _execute_tool(db, run, tool_call.function.name, tool_input, actions)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result_text})
    else:
        final_text = "Reached the maximum number of steps for this instruction; review the proposals below."

    return {"summary": final_text or "No changes were proposed.", "actions": actions}


def _execute_tool(db: Session, run, name: str, tool_input: Dict[str, Any], actions: List[Dict[str, Any]]) -> str:
    if name == "find_subjects":
        results = _list_subjects_in_scope(db, run, tool_input.get("name_contains"))
        return json.dumps(results)

    if name == "propose_exclude_subject":
        section_id = tool_input["section_id"]
        subject_id = tool_input["subject_id"]
        subject = db.query(Subject).filter(Subject.id == subject_id).first()
        section = db.query(Section).filter(Section.id == section_id).first()
        if not subject or not section:
            return "Unknown section_id or subject_id - call find_subjects again."
        actions.append({
            "action_type": "exclude_subject",
            "description": f"Remove {subject.name} from {section.name} for this timetable only",
            "payload": {"section_id": section_id, "subject_id": subject_id, "exclude": True},
        })
        return f"Proposed removing {subject.name} from {section.name} for this timetable."

    if name == "propose_change_weekly_hours":
        section_id = tool_input["section_id"]
        subject_id = tool_input["subject_id"]
        subject = db.query(Subject).filter(Subject.id == subject_id).first()
        section = db.query(Section).filter(Section.id == section_id).first()
        if not subject or not section:
            return "Unknown section_id or subject_id - call find_subjects again."
        delta = tool_input.get("delta")
        new_value = tool_input.get("new_value")
        target = new_value if new_value is not None else subject.weekly_hours + (delta or 0)
        if target < 0:
            return "That would make hours/week negative - not proposed. Use propose_exclude_subject to remove it entirely instead."
        actions.append({
            "action_type": "change_weekly_hours",
            "description": (
                f"{subject.name} for {section.name}: {subject.weekly_hours} -> {target} hours/week "
                "for this timetable only"
            ),
            "payload": {"section_id": section_id, "subject_id": subject_id, "weekly_hours": target},
        })
        return f"Proposed changing {subject.name} for {section.name} to {target} hours/week for this timetable."

    return f"Unknown tool: {name}"
