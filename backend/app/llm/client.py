"""LLM client, via any OpenAI-compatible chat completions endpoint (OpenRouter,
Ollama, NVIDIA NIM, OpenAI itself, etc. - whatever LLM_BASE_URL points at),
for four AI-assisted (never AI-authoritative) features:
  1. Parsing an admin's natural-language instruction into structured
     ConstraintRule candidates, grounded in the institution's real catalog
     of teacher/room/section/subject ids - never invented ones.
  2. Turning a verified diagnostics report into a plain-language
     explanation of why generation failed.
  3. Parsing a plain-English "move this class..." instruction into a
     (day, period) pair, grounded in the run's real configured time slots
     - never an invented slot.
  4. Turning a plain-English "show me..." request from a teacher into a
     structured Custom Filter spec (see app/schemas/custom_filter.py),
     grounded in the real catalog. The spec is evaluated by plain
     deterministic code (app/services/custom_filter.py) - the model never
     sees or produces timetable data, only the filter.

Deliberately absent: anything that asks the model to invent a schedule,
or to move/apply anything itself. Every one of these three only ever
returns a candidate for a human to review; the one thing that actually
writes a moved class to the database is POST /timetable/runs/{id}/edit,
called by the admin's own explicit click - see EditEntryModal.tsx and
app/routers/timetable.py::edit_entry, which also re-checks the move for
conflicts independently of whatever the model proposed. The solver is
the only component ever allowed to emit a timetable in the first place -
see CLAUDE.md and the diagnostics module's own docstring for why.
"""
import json
from typing import Any, Dict, List, Optional

from app.core.config import settings

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - the package is a hard requirement,
    OpenAI = None  # but the app should still import if it's briefly missing.

PARSE_SYSTEM_PROMPT = """You convert a college admin's plain-English instruction into structured rules for a university timetable generator. You are given the institution's REAL catalog of teacher, section, subject and room ids - you must only ever reference ids that appear in that catalog. Never invent an id. Match names loosely (titles like "Mr"/"Prof", typos, partial names), but if a name matches nothing or several entries, do not guess - list it under "ambiguities" instead.

Supported rule types:
  - "teacher_unavailable" / "room_unavailable" / "section_unavailable": that teacher/room/section can never be scheduled in the given day + start_time + end_time window. All three are required.
  - "teacher_preferred": a soft preference to schedule the teacher in the given day + window.
  - "max_daily_override": target a teacher; "weight" is the new max classes per day.
  - "batch_scheduling_mode": target a lab subject; "batch_mode" is parallel | sequential | merged | independent. The day/start_time/end_time window is optional.
  - "subject_time_window": target a subject; "params": {"mode": "within" | "avoid"} keeps the subject inside or outside start_time-end_time. day may be null for every day.
  - "max_subjects_per_day": target a section (or "*" for all sections); "params": {"max": N}.
  - "teacher_max_days_per_week": target a teacher; "params": {"max": N}.
  - "custom": anything else about a specific teacher/room/section/subject that can't be expressed above.

LAB ROTATIONS are NOT a rule type - they go in the separate "lab_rotations" list below. A lab rotation is what an admin means by "run these labs together", "schedule the labs in parallel", "A1 does one lab while A2 does another", or "lab slot on Monday afternoon": several DIFFERENT lab subjects for ONE section, run at the same time with a different batch in each, swapping round by round until every batch has done every lab. It needs at least two lab subjects of the same section. Only use "batch_scheduling_mode" with "parallel" when the admin really means every batch in the SAME single lab at once (which needs one qualified teacher per batch) - that is rarely what "together" means. The day/start_time/end_time window is optional and pins where the rotation sits.

LABS NEEDING SEVERAL TEACHERS go in the separate "subject_teacher_counts" list: "this lab needs two instructors", "both lab faculty must be present", "assign 2 teachers to the DBMS lab". `teachers_required` is how many qualified teachers must be in the room AT THE SAME TIME for one session.

Rules: use 24-hour HH:MM times. If an admin gives a bare hour range like "2 to 4" for a college day, assume daytime hours (14:00-16:00), not the early morning. Days are Mon|Tue|Wed|Thu|Fri|Sat|Sun. "Unavailable"/"never"/"must" means priority "hard"; "prefer"/"try to" means "soft" (give soft rules of the last three templates a "weight" of 10). Anything about global trade-offs (student gaps, balanced days, etc.) or things the system has no concept of goes in "unsupported_requests".

Respond with ONLY a JSON object (no markdown fences, no prose) of this exact shape:
{
  "constraints": [
    {
      "rule_type": "<one of the types above>",
      "target_type": "teacher | room | section | subject",
      "target_id": "<id from the catalog>",
      "day": "Mon|Tue|Wed|Thu|Fri|Sat|Sun|null",
      "start_time": "HH:MM or null",
      "end_time": "HH:MM or null",
      "priority": "hard | soft",
      "weight": 0,
      "batch_mode": "parallel|sequential|merged|independent or null",
      "params": {} ,
      "description": "<short plain-English restatement>"
    }
  ],
  "lab_rotations": [
    {
      "name": "<short name, e.g. '3rd year A labs'>",
      "section_id": "<section id from the catalog>",
      "subject_ids": ["<two or more lab subject ids from the catalog>"],
      "day": "Mon|Tue|Wed|Thu|Fri|Sat|Sun|null",
      "start_time": "HH:MM or null",
      "end_time": "HH:MM or null",
      "description": "<short plain-English restatement>"
    }
  ],
  "subject_teacher_counts": [
    {"subject_id": "<subject id from the catalog>", "teachers_required": 2,
     "description": "<short plain-English restatement>"}
  ],
  "ambiguities": ["<text the model could not confidently map>"],
  "unsupported_requests": ["<things this system genuinely cannot express as a rule>"]
}"""

MOVE_SYSTEM_PROMPT = """You convert a college admin's plain-English instruction for moving one \
already-scheduled class into a single (day, period) choice for a university timetable editor.

You are given the class's current day/period and the institution's REAL catalog of configured time \
slots (day, period, start time, end time) - you must choose one (day, period) pair that appears \
EXACTLY in that catalog. Never invent a day or period that isn't listed, and never invent a time.

You are not responsible for checking room/teacher/student conflicts at the target slot - a separate, \
deterministic check does that after you respond, and will reject the move and suggest alternatives if \
there's a clash. Your only job is turning the instruction's day/time language into one catalog slot.

If the instruction is ambiguous (doesn't clearly pick one slot - e.g. "sometime next week", or names a \
day/time with no matching slot in the catalog), do not guess: return null for both day and period and \
explain what's unclear in "note".

Respond with ONLY a JSON object (no markdown fences, no prose) of this exact shape:
{
  "new_day": "<one of the exact day values from the catalog, or null>",
  "new_period": <one of the exact period values from the catalog for that day, or null>,
  "note": "<one short sentence: what you picked and why, or why you couldn't decide>"
}"""

FILTER_SYSTEM_PROMPT = """You convert a teacher's plain-English request for a custom view of a university timetable into a structured filter. You are given the institution's REAL catalog of teacher, section, subject and room ids and the configured days/time range - only ever reference ids from that catalog, never invent one. Match names loosely (titles like "Mr"/"Prof", typos, initials, partial names). If a name matches nothing or several entries, do not guess - leave it out and mention it in "unsupported".

Two modes:
  - "classes": show scheduled classes that match. Every non-empty list must match (AND across fields, OR within a field).
  - "free_slots": show day/period slots where EVERY listed teacher and section is free. Use this for "when can we hold a seminar / meeting / extra class". If the request needs a room (a seminar hall, a lab, a room of N seats), set room_types and/or min_room_capacity and/or room_ids - a slot is only shown if a matching room is also free.

Fields: days (Mon|Tue|Wed|Thu|Fri|Sat|Sun; empty = all), time_from/time_to (24-hour HH:MM; a bare range like "2 to 4" means daytime 14:00-16:00; "afternoon" = 12:00-17:00, "morning" = before 12:00), teacher_ids, section_ids, subject_ids, room_ids, room_types (from the catalog's room types), subject_types (from the catalog's subject types), min_room_capacity. If the teacher says "me", "my" or "I", put the literal string "$me" in teacher_ids.

Anything you cannot express with these fields goes in "unsupported".

Respond with ONLY a JSON object (no markdown fences, no prose) of this exact shape:
{
  "title": "<2-5 word name for this view>",
  "explanation": "<one sentence restating what the view shows>",
  "spec": {
    "mode": "classes | free_slots",
    "days": [], "time_from": null, "time_to": null,
    "teacher_ids": [], "section_ids": [], "subject_ids": [], "room_ids": [],
    "room_types": [], "subject_types": [], "min_room_capacity": null
  },
  "unsupported": ["<parts of the request this filter cannot express>"]
}"""


class ConstraintLLMClient:
    def __init__(self):
        self.model = settings.LLM_MODEL
        self._client: Optional["OpenAI"] = None

    @property
    def client(self) -> "OpenAI":
        if not settings.LLM_API_KEY:
            raise RuntimeError(
                "LLM_API_KEY is not configured. AI-assisted constraint parsing is disabled "
                "until an operator sets it - the rest of the system works without it."
            )
        if self._client is None:
            if OpenAI is None:
                raise RuntimeError("The openai package is not installed.")
            self._client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        return self._client

    def parse_constraints(self, text: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        catalog = catalog or {}
        user_content = (
            f"Institution catalog (only use these ids):\n{json.dumps(catalog, indent=2)}\n\n"
            f"Admin instruction:\n{text}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        raw_text = response.choices[0].message.content or ""
        return self._parse_json_response(raw_text)

    def parse_move_instruction(
        self, text: str, current: Dict[str, Any], available_slots: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """current: {"subject_id", "day", "period"} for the class being moved.
        available_slots: the institution's real configured time slots, e.g.
        [{"day": "Mon", "period": 1, "start_time": "09:00", "end_time": "09:50"}, ...]
        - the only slots the model is allowed to choose from."""
        user_content = (
            f"Class being moved: {json.dumps(current)}\n\n"
            f"Available time slots (choose day/period only from this list):\n"
            f"{json.dumps(available_slots, indent=2)}\n\n"
            f"Admin instruction:\n{text}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=512,
            messages=[
                {"role": "system", "content": MOVE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        raw_text = response.choices[0].message.content or ""
        parsed = self._strip_and_load_json(raw_text)

        valid_pairs = {(slot["day"], slot["period"]) for slot in available_slots}
        new_day = parsed.get("new_day")
        new_period = parsed.get("new_period")
        note = parsed.get("note") or ""
        if (new_day, new_period) not in valid_pairs:
            # Never let a hallucinated or out-of-catalog slot reach the
            # admin as if it were a real choice - fall back to "couldn't
            # decide" exactly like the model saying so itself would.
            if new_day is not None or new_period is not None:
                note = note or "The suggested slot isn't one of the configured time slots."
            new_day, new_period = None, None

        return {"new_day": new_day, "new_period": new_period, "note": note}

    def parse_filter_query(self, query: str, catalog: Dict[str, Any]) -> Dict[str, Any]:
        """Returns the raw parsed JSON ({"title","explanation","spec","unsupported"}).
        Id grounding happens in the caller (routers/custom_filters.py), which
        owns the catalog and drops anything the model invented."""
        user_content = (
            f"Institution catalog (only use these ids):\n{json.dumps(catalog, indent=2)}\n\n"
            f"Teacher's request:\n{query}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": FILTER_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        parsed = self._strip_and_load_json(response.choices[0].message.content or "")
        parsed.setdefault("spec", {})
        parsed.setdefault("unsupported", [])
        return parsed

    def explain_infeasibility(self, verified_diagnostics_text: str) -> str:
        """Turns already-verified diagnostic facts into a friendlier
        explanation. The model is explicitly told not to invent causes -
        it may only restate/clarify what's already been proven."""
        system = (
            "You explain university timetable generation failures to a non-technical college "
            "admin. You are given VERIFIED facts about why generation failed - do not invent any "
            "additional causes, numbers, or names beyond what's given. Restate the facts in warm, "
            "plain, actionable language. Keep it under 200 words."
        )
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": verified_diagnostics_text},
            ],
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _strip_and_load_json(raw_text: str) -> Dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AI response was not valid JSON: {exc}") from exc

    @classmethod
    def _parse_json_response(cls, raw_text: str) -> Dict[str, Any]:
        parsed = cls._strip_and_load_json(raw_text)
        parsed.setdefault("constraints", [])
        parsed.setdefault("ambiguities", [])
        parsed.setdefault("unsupported_requests", [])
        return parsed


claude_client = ConstraintLLMClient()
