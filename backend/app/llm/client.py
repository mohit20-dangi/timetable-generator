"""LLM client, via any OpenAI-compatible chat completions endpoint (OpenRouter,
Ollama, NVIDIA NIM, OpenAI itself, etc. - whatever LLM_BASE_URL points at),
for three AI-assisted (never AI-authoritative) features:
  1. Parsing an admin's natural-language instruction into structured
     ConstraintRule candidates, grounded in the institution's real catalog
     of teacher/room/section/subject ids - never invented ones.
  2. Turning a verified diagnostics report into a plain-language
     explanation of why generation failed.
  3. Parsing a plain-English "move this class..." instruction into a
     (day, period) pair, grounded in the run's real configured time slots
     - never an invented slot.

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
from app.solver.weights import IMPORTANCE_LEVELS, SOFT_RULE_DESCRIPTIONS, SOFT_RULE_KEYS

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - the package is a hard requirement,
    OpenAI = None  # but the app should still import if it's briefly missing.

# Built from the solver's own SOFT_RULE_KEYS/SOFT_RULE_DESCRIPTIONS rather
# than hardcoded here, so the model is always told about exactly the rules
# the system actually supports - a plain-English request that matches one
# of these must be mapped to it, never dropped into "unsupported_requests"
# just because the prompt didn't mention it existed.
_SOFT_RULE_LIST = "\n".join(
    f'  - "{key}": {SOFT_RULE_DESCRIPTIONS[key]}' for key in SOFT_RULE_KEYS
)

PARSE_SYSTEM_PROMPT = f"""You convert a college admin's plain-English scheduling instruction into \
structured JSON constraints for a university timetable generator. You are given the institution's \
REAL catalog of teacher, section, subject and room ids - you must only ever reference ids that \
appear in that catalog. Never invent an id. If the instruction refers to something not in the \
catalog (a name that doesn't match, or something ambiguous), list it under "ambiguities" instead \
of guessing.

The system supports exactly these soft scheduling priorities - if the instruction expresses any of \
these (in any wording), you MUST reflect it in "soft_constraint_weights" using the exact key below, \
never list it under "unsupported_requests":
{_SOFT_RULE_LIST}

Only use "unsupported_requests" for things that genuinely match none of the keys above and aren't a \
constraint on a specific teacher/room/section/subject (the "constraints" list) - e.g. requests about \
things this system has no concept of at all (room amenities, exam scheduling, etc.).

For each soft priority the instruction actually expresses an opinion about, set its level based on \
how strongly the admin phrased it - "must_have" for language like "always"/"must"/"never", \
"very_important" for clear emphasis, "nice_to_have" for a mild preference. Omit a key entirely from \
"soft_constraint_weights" if the instruction says nothing about it - do not guess a level for \
something it never mentioned.

Respond with ONLY a JSON object (no markdown fences, no prose) of this exact shape:
{{
  "constraints": [
    {{
      "rule_type": "teacher_unavailable | room_unavailable | section_unavailable | teacher_preferred | max_daily_override | custom",
      "target_type": "teacher | room | section | subject",
      "target_id": "<id from the catalog>",
      "day": "Mon|Tue|Wed|Thu|Fri|Sat|null",
      "start_time": "HH:MM or null",
      "end_time": "HH:MM or null",
      "priority": "hard | soft",
      "description": "<plain-English restatement>"
    }}
  ],
  "soft_constraint_weights": {{"<one of the exact keys listed above>": "must_have|very_important|nice_to_have|dont_care"}},
  "ambiguities": ["<text the model could not confidently map>"],
  "unsupported_requests": ["<things this system genuinely cannot express - not one of the keys above>"]
}}"""

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
        parsed.setdefault("soft_constraint_weights", {})
        parsed.setdefault("ambiguities", [])
        parsed.setdefault("unsupported_requests", [])
        parsed["soft_constraint_weights"] = {
            key: level
            for key, level in parsed["soft_constraint_weights"].items()
            if key in SOFT_RULE_KEYS and level in IMPORTANCE_LEVELS
        }
        return parsed


claude_client = ConstraintLLMClient()
