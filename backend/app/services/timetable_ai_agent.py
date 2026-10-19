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

UPDATE: placement changes (move / swap / change teacher or room / delete /
lock) are now also proposable. They are not regenerated - each proposal is an
editor operation (app/services/timetable_editor.py), pre-checked here against
the SAME conflict gate the manual editor uses, so the model only ever hands
the admin changes that would actually be accepted. They are applied through
POST .../editor/apply on a draft, instantly and with undo.
"""
import json
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Subject, SectionSubject, Section
from app.solver.data_loader import _resolve_target_sections
from app.schemas.timetable_edit import (
    ChangeRoomOp, ChangeTeacherOp, DeleteOp, LockOp, MoveOp, SwapOp,
)
from app.services import timetable_editor as editor
from app.models import Teacher, Room

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
    {
        "type": "function",
        "function": {
            "name": "find_classes",
            "description": 'List classes already placed in this timetable (session_group, subject, section, teacher, room, day, period, length in periods, locked). All filters optional. Always call this before proposing a move/swap/change/delete/lock - never invent a session_group.',
            "parameters": {"type": "object", "properties": {"section_id": {"type": "string"}, "teacher_id": {"type": "string"}, "room_id": {"type": "string"}, "subject_name": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_free_slots",
            "description": 'Conflict-free day/period positions a placed class could be moved to.',
            "parameters": {"type": "object", "properties": {"session_group": {"type": "string"}}, "required": ["session_group"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_options",
            "description": 'Teachers qualified to teach, and suitable rooms for, a placed class, each marked free or blocked with the reason.',
            "parameters": {"type": "object", "properties": {"session_group": {"type": "string"}}, "required": ["session_group"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_move",
            "description": 'Propose moving a placed class (all its periods) to a new day/period. Checked against every rule; if it would conflict you are told why and nothing is proposed.',
            "parameters": {"type": "object", "properties": {"session_group": {"type": "string"}, "day": {"type": "string"}, "period": {"type": "integer"}}, "required": ["session_group", "day", "period"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_swap",
            "description": 'Propose two placed classes exchanging their times.',
            "parameters": {"type": "object", "properties": {"session_group_a": {"type": "string"}, "session_group_b": {"type": "string"}}, "required": ["session_group_a", "session_group_b"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_change_teacher",
            "description": 'Propose giving a placed class (and every other session of that subject for that audience) to a different qualified teacher. Use ids from find_options.',
            "parameters": {"type": "object", "properties": {"session_group": {"type": "string"}, "teacher_id": {"type": "string"}}, "required": ["session_group", "teacher_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_change_room",
            "description": 'Propose moving a placed class to a different room. Use ids from find_options.',
            "parameters": {"type": "object", "properties": {"session_group": {"type": "string"}, "room_id": {"type": "string"}}, "required": ["session_group", "room_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_delete",
            "description": 'Propose removing a placed class block from the timetable.',
            "parameters": {"type": "object", "properties": {"session_group": {"type": "string"}}, "required": ["session_group"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_lock",
            "description": 'Propose locking a placed class so it can never be moved, reassigned, or shifted by a regeneration.',
            "parameters": {"type": "object", "properties": {"session_group": {"type": "string"}}, "required": ["session_group"]},
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

You CAN also change when/who/where an already-placed class is: look classes up with `find_classes`, \
check alternatives with `find_free_slots` / `find_options`, then use `propose_move`, `propose_swap`, \
`propose_change_teacher`, `propose_change_room`, `propose_delete` or `propose_lock`. Each of these is \
checked against every scheduling rule before it is accepted as a proposal; if a tool reports a conflict, \
pick another option (or explain in your final response why it is impossible) rather than repeating it. \
Prefer these over hours changes whenever the request is about WHEN, WHO or WHERE. Earlier accepted \
proposals are taken into account by later ones.

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
    ctx = editor.EditContext(db, run)
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
            result_text = _execute_tool(db, run, tool_call.function.name, tool_input, actions, ctx)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result_text})
    else:
        final_text = "Reached the maximum number of steps for this instruction; review the proposals below."

    return {"summary": final_text or "No changes were proposed.", "actions": actions}


def _execute_tool(db: Session, run, name: str, tool_input: Dict[str, Any], actions: List[Dict[str, Any]], ctx=None) -> str:
    is_editor_tool = name in _EDITOR_READ_TOOLS or (name.startswith("propose_") and name not in _OVERRIDE_TOOLS)
    if ctx is not None and is_editor_tool:
        return _execute_editor_tool(db, ctx, name, tool_input, actions)
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


_OVERRIDE_TOOLS = {"propose_exclude_subject", "propose_change_weekly_hours"}
_EDITOR_READ_TOOLS = {"find_classes", "find_free_slots", "find_options"}


def _execute_editor_tool(db: Session, ctx, name: str, tool_input: Dict[str, Any], actions: List[Dict[str, Any]]) -> str:
    subjects = {s.id: s.name for s in db.query(Subject).all()}
    teachers = {t.id: t.name for t in db.query(Teacher).all()}
    rooms = {r.id: r.name for r in db.query(Room).all()}
    sections = {s.id: s.name for s in db.query(Section).all()}

    def block(group):
        return ctx.block(ctx.entries, group)

    def describe(group):
        rows = block(group)
        if not rows:
            return group
        e = rows[0]
        who = sections.get(ctx.section_of(e), ctx.section_of(e))
        return f"{subjects.get(e.subject_id, e.subject_id)} ({who}, {e.day} period {e.period})"

    if name == "find_classes":
        seen, out = set(), []
        needle = (tool_input.get("subject_name") or "").lower()
        for e in ctx.entries:
            g = editor.gk(e)
            if g in seen:
                continue
            if tool_input.get("section_id") and ctx.section_of(e) != tool_input["section_id"]:
                continue
            if tool_input.get("teacher_id") and e.teacher_id != tool_input["teacher_id"]:
                continue
            if tool_input.get("room_id") and e.room_id != tool_input["room_id"]:
                continue
            if needle and needle not in subjects.get(e.subject_id, "").lower():
                continue
            seen.add(g)
            rows = block(g)
            out.append({
                "session_group": g, "subject": subjects.get(e.subject_id, e.subject_id),
                "section_id": ctx.section_of(e), "section": sections.get(ctx.section_of(e)),
                "batch_id": e.batch_id, "teacher_id": e.teacher_id, "teacher": teachers.get(e.teacher_id),
                "room_id": e.room_id, "room": rooms.get(e.room_id), "day": rows[0].day,
                "period": rows[0].period, "periods_long": len(rows), "locked": e.is_locked,
            })
            if len(out) >= 60:
                break
        return json.dumps(out)

    group = tool_input.get("session_group") or tool_input.get("session_group_a")
    if not group or not block(group):
        return "Unknown session_group - call find_classes again."

    if name == "find_free_slots":
        return json.dumps([{"day": d, "period": p} for d, p in editor.free_slots_for(ctx, group, 8)])
    if name == "find_options":
        found = editor.resource_options(ctx, group)
        return json.dumps({"teachers": found[0], "rooms": found[1]})

    try:
        if name == "propose_move":
            op = MoveOp(session_group=group, day=tool_input["day"], period=int(tool_input["period"]))
            text = f"Move {describe(group)} to {op.day} period {op.period}"
        elif name == "propose_swap":
            other = tool_input["session_group_b"]
            if not block(other):
                return "Unknown session_group_b - call find_classes again."
            op = SwapOp(session_group_a=group, session_group_b=other)
            text = f"Swap {describe(group)} with {describe(other)}"
        elif name == "propose_change_teacher":
            op = ChangeTeacherOp(session_group=group, teacher_id=tool_input["teacher_id"], scope="all_sessions")
            text = f"Give {describe(group)} to {teachers.get(op.teacher_id, op.teacher_id)}"
        elif name == "propose_change_room":
            op = ChangeRoomOp(session_group=group, room_id=tool_input["room_id"])
            text = f"Move {describe(group)} to room {rooms.get(op.room_id, op.room_id)}"
        elif name == "propose_delete":
            op = DeleteOp(session_group=group)
            text = f"Remove {describe(group)}"
        elif name == "propose_lock":
            op = LockOp(session_group=group)
            text = f"Lock {describe(group)}"
        else:
            return f"Unknown tool: {name}"
    except (KeyError, ValueError) as exc:
        return f"Bad arguments: {exc}"

    result = editor.simulate(ctx, [op])
    if not result.ok:
        return "NOT PROPOSED - this would conflict: " + "; ".join(c.message for c in result.conflicts)
    ctx.entries = result.entries  # later proposals build on this one
    actions.append({"action_type": "editor_op", "description": text, "payload": op.model_dump()})
    return f"Proposed: {text}."
