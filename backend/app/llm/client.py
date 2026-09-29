import os
import json
from typing import Dict, Any, Optional
from openai import OpenAI
from app.core.config import settings

class NVIDIAClient:
    def __init__(self):
        self._client: Optional[OpenAI] = None
        self.model = settings.NVIDIA_MODEL

    @property
    def client(self) -> OpenAI:
        """Lazily construct the underlying OpenAI client on first use.

        Deferred so a missing NVIDIA_API_KEY only breaks LLM endpoints,
        not the whole app at import/startup time.
        """
        if self._client is None:
            api_key = settings.NVIDIA_API_KEY or os.getenv("NVIDIA_API_KEY")
            if not api_key:
                raise ValueError("NVIDIA_API_KEY not found in environment or settings")
            self._client = OpenAI(
                base_url=settings.NVIDIA_BASE_URL,
                api_key=api_key
            )
        return self._client

    def parse_constraints(self, text: str) -> Dict[str, Any]:
        """Parse natural language constraints into structured JSON."""
        system_prompt = """You are a timetable constraint parser. Convert natural language descriptions into structured JSON following this exact schema:

{
  "years": [
    {
      "id": "string",
      "name": "string",
      "sections": integer,
      "lunch": {"start": "HH:MM", "end": "HH:MM"}
    }
  ],
  "subjects": [
    {
      "id": "string",
      "name": "string",
      "type": "theory|lab|tutorial",
      "weekly_hours": integer,
      "needs_continuous_block": boolean,
      "block_size": integer,
      "requires_room_type": "lecture|lab|seminar|null",
      "requires_equipment": ["string"]
    }
  ],
  "teachers": [
    {
      "id": "string",
      "name": "string",
      "subjects": ["subject_id"],
      "max_continuous_classes": integer,
      "max_daily_classes": integer,
      "availability": [{"day": "Mon|Tue|Wed|Thu|Fri|Sat", "start": "HH:MM", "end": "HH:MM"}],
      "preferred_slots": [{"day": "Mon|Tue|Wed|Thu|Fri|Sat", "slots": [{"start": "HH:MM", "end": "HH:MM"}]}],
      "is_guest_from_other_dept": boolean
    }
  ],
  "rooms": [
    {
      "id": "string",
      "name": "string",
      "type": "lecture|lab|seminar",
      "capacity": integer,
      "equipment": ["string"],
      "shared_with_departments": ["string"],
      "availability": [{"day": "Mon|Tue|Wed|Thu|Fri|Sat", "start": "HH:MM", "end": "HH:MM"}]
    }
  ],
  "soft_constraint_weights": {
    "minimize_gaps": integer,
    "lab_theory_mix": integer,
    "empty_day_preference": ["Mon", "Fri"],
    "teacher_preference": integer,
    "minimize_travel": integer,
    "class_changes_via_breaks": integer
  }
}

IMPORTANT SCHEDULING RULES:
- Class changes MUST occur during designated breaks (lunch, between periods)
- Never schedule classes back-to-back without a break in between
- Teachers and students require transition time between classes
- Violating this will cause people to be late or miss classes

Return ONLY valid JSON. No markdown, no explanations."""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"}
        )
        
        return json.loads(response.choices[0].message.content)
    
    def explain_infeasibility(self, constraints: Dict[str, Any], solver_status: str, conflict_info: str) -> str:
        """Generate plain English explanation of why timetable generation failed."""
        system_prompt = """You are a timetable scheduling expert. Given a set of constraints and solver conflict information, explain in plain English:
1. Which constraints are in tension/conflict
2. Why the solver couldn't find a feasible solution
3. Suggest 2-3 specific ways to relax constraints to make it feasible

Be concise, practical, and actionable. Address the admin user directly."""
        
        user_prompt = f"""Constraints:
{json.dumps(constraints, indent=2)}

Solver Status: {solver_status}
Conflict Info: {conflict_info}

Explain the infeasibility and suggest relaxations."""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )
        
        return response.choices[0].message.content
    
    def prototype_timetable(self, constraints: Dict[str, Any]) -> Dict[str, Any]:
        """Quick prototype timetable generation using LLM (for testing only)."""
        system_prompt = """You are a timetable generator. Given constraints, produce a feasible weekly timetable.
Return JSON with this structure:
{
  "entries": [
    {"day": "Mon", "period": 1, "section_id": "sec1", "subject_id": "sub1", "teacher_id": "t1", "room_id": "r1"}
  ],
  "warnings": ["string"]
}

This is a PROTOTYPE - label output as unverified. Do your best but note limitations."""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(constraints, indent=2)}
            ],
            temperature=0.2,
            max_tokens=4000,
            response_format={"type": "json_object"}
        )
        
        return json.loads(response.choices[0].message.content)

    def parse_timetable_edit(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a natural-language edit request against an existing timetable into
        structured operations. The caller is responsible for resolving each operation
        to a concrete entry and validating it before applying anything - this only
        proposes what to do, it never touches the timetable itself."""
        system_prompt = """You are a timetable editing assistant. You will be given the current timetable's entries, reference lists of teachers and rooms, and a natural-language instruction describing a change to make.

Convert the instruction into a JSON object with this exact schema:
{
  "operations": [
    {
      "op": "move" | "reassign_room" | "reassign_teacher" | "delete" | "swap",
      "match": {"day": "Mon", "period": 3, "section_id": "s1", "batch_id": null, "subject_id": "sub1", "teacher_id": "t1", "room_id": "r1"},
      "day": "Wed",
      "period": 5,
      "room_id": "r2",
      "teacher_id": "t2",
      "match_b": {"day": "Wed", "period": 5, "section_id": "s2"},
      "swap_field": "slot"
    }
  ],
  "explanation": "one sentence describing what you are about to do",
  "unclear": false
}

Rules:
- "match" (and "match_b" for swap) identifies exactly ONE existing entry. Only include the fields you can confidently determine from the instruction and the given entries/reference lists - use IDs, never names. Include as many identifying fields as you can (day, period, subject_id, teacher_id, room_id, section_id) to make the match unambiguous.
- "day"/"period" are only used for "move". "room_id" is only used for "reassign_room". "teacher_id" is only used for "reassign_teacher". "match_b" and "swap_field" ("slot", "room", or "teacher") are only used for "swap".
- Resolve any teacher/room names mentioned in the instruction to their IDs using the reference lists provided.
- These five operations are the ONLY things you can do. If the instruction asks for anything else (e.g. creating a brand-new class, changing subject requirements), set "unclear": true, leave "operations" empty, and explain why in "explanation".
- If the instruction is ambiguous or missing information needed to identify an entry, set "unclear": true and explain what's missing.
- Return ONLY valid JSON. No markdown, no explanations outside the JSON."""

        user_prompt = f"""Current timetable entries:
{json.dumps(context["entries_summary"], indent=2)}

Available teachers:
{json.dumps(context["teachers_list"], indent=2)}

Available rooms:
{json.dumps(context["rooms_list"], indent=2)}

Instruction: {instruction}"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"}
        )

        return json.loads(response.choices[0].message.content)


nvidia_client = NVIDIAClient()