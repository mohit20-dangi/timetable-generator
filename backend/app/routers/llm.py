import json
from fastapi import APIRouter, Depends, HTTPException
from app.models import NLConstraintParseRequest, NLConstraintParseResponse
from app.llm.client import nvidia_client
from app.auth.dependencies import get_current_admin

router = APIRouter(prefix="/api/constraints", tags=["LLM"])

@router.post("/parse-nl", response_model=NLConstraintParseResponse)
def parse_natural_language_constraints(request: NLConstraintParseRequest, _admin: dict = Depends(get_current_admin)):
    """Parse natural language constraints into structured JSON."""
    try:
        parsed = nvidia_client.parse_constraints(request.text)
        return NLConstraintParseResponse(
            parsed_constraints=parsed,
            raw_response=json.dumps(parsed, indent=2)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM parsing failed: {str(e)}")

@router.post("/prototype")
def prototype_timetable(request: NLConstraintParseRequest, _admin: dict = Depends(get_current_admin)):
    """Generate a prototype timetable using LLM (for testing only)."""
    try:
        parsed = nvidia_client.parse_constraints(request.text)
        prototype = nvidia_client.prototype_timetable(parsed)
        return {
            "prototype": prototype,
            "warning": "This is an LLM-generated prototype. Not verified by solver. Use for testing only."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prototype generation failed: {str(e)}")
