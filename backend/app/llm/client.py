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


nvidia_client = NVIDIAClient()