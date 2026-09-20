"""Claude client for the two AI-assisted (never AI-authoritative) features:
  1. Parsing an admin's natural-language instruction into structured
     ConstraintRule candidates, grounded in the institution's real catalog
     of teacher/room/section/subject ids - never invented ones.
  2. Turning a verified diagnostics report into a plain-language
     explanation of why generation failed.

Deliberately absent: anything that asks the model to invent a schedule.
The solver is the only component ever allowed to emit a timetable - see
CLAUDE.md and the diagnostics module's own docstring for why.
"""
import json
from typing import Any, Dict, List, Optional

from app.core.config import settings

try:
    import anthropic
except ImportError:  # pragma: no cover - the package is a hard requirement,
    anthropic = None  # but the app should still import if it's briefly missing.

PARSE_SYSTEM_PROMPT = """You convert a college admin's plain-English scheduling instruction into \
structured JSON constraints for a university timetable generator. You are given the institution's \
REAL catalog of teacher, section, subject and room ids - you must only ever reference ids that \
appear in that catalog. Never invent an id. If the instruction refers to something not in the \
catalog (a name that doesn't match, or something ambiguous), list it under "ambiguities" instead \
of guessing.

Respond with ONLY a JSON object (no markdown fences, no prose) of this exact shape:
{
  "constraints": [
    {
      "rule_type": "teacher_unavailable | room_unavailable | section_unavailable | teacher_preferred | max_daily_override | custom",
      "target_type": "teacher | room | section | subject",
      "target_id": "<id from the catalog>",
      "day": "Mon|Tue|Wed|Thu|Fri|Sat|null",
      "start_time": "HH:MM or null",
      "end_time": "HH:MM or null",
      "priority": "hard | soft",
      "description": "<plain-English restatement>"
    }
  ],
  "soft_constraint_weights": {"<rule_key>": "must_have|very_important|nice_to_have|dont_care"},
  "ambiguities": ["<text the model could not confidently map>"],
  "unsupported_requests": ["<things this system cannot express as a constraint>"]
}"""


class ClaudeConstraintClient:
    def __init__(self):
        self.model = settings.ANTHROPIC_MODEL
        self._client: Optional["anthropic.Anthropic"] = None

    @property
    def client(self) -> "anthropic.Anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not configured. AI-assisted constraint parsing is disabled "
                "until an operator sets it - the rest of the system works without it."
            )
        if self._client is None:
            if anthropic is None:
                raise RuntimeError("The anthropic package is not installed.")
            self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

    def parse_constraints(self, text: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        catalog = catalog or {}
        user_content = (
            f"Institution catalog (only use these ids):\n{json.dumps(catalog, indent=2)}\n\n"
            f"Admin instruction:\n{text}"
        )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=PARSE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        raw_text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return self._parse_json_response(raw_text)

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
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": verified_diagnostics_text}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")

    @staticmethod
    def _parse_json_response(raw_text: str) -> Dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AI response was not valid JSON: {exc}") from exc
        parsed.setdefault("constraints", [])
        parsed.setdefault("soft_constraint_weights", {})
        parsed.setdefault("ambiguities", [])
        parsed.setdefault("unsupported_requests", [])
        return parsed


claude_client = ClaudeConstraintClient()
