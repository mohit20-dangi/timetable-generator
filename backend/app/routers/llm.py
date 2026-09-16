from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json
from app.schemas import NLConstraintParseRequest, NLConstraintParseResponse
from app.llm.client import nvidia_client
from app.models import Room, Section, Subject, Teacher, User
from app.db import get_db
from app.auth.dependencies import require_admin

router = APIRouter(prefix="/api/constraints", tags=["LLM"])

@router.post("/parse-nl", response_model=NLConstraintParseResponse)
def parse_natural_language_constraints(
    request: NLConstraintParseRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Parse natural language constraints into structured JSON. Admin reviews before applying."""
    try:
        catalog = {
            "teachers": [{"id": item.id, "name": item.name} for item in db.query(Teacher).all()],
            "sections": [{"id": item.id, "name": item.name} for item in db.query(Section).all()],
            "subjects": [{"id": item.id, "name": item.name} for item in db.query(Subject).all()],
            "rooms": [{"id": item.id, "name": item.name} for item in db.query(Room).all()],
        }
        parsed = nvidia_client.parse_constraints(request.text, catalog=catalog)
        return NLConstraintParseResponse(
            parsed_constraints=parsed,
            raw_response=json.dumps(parsed, indent=2)
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI provider request failed for model '{nvidia_client.model}'. Check NVIDIA_MODEL and the provider response, then try again.") from e

@router.post("/prototype")
def prototype_timetable(request: NLConstraintParseRequest, _admin: User = Depends(require_admin)):
    """Generate a prototype timetable using LLM (for testing only, not used by real generation)."""
    try:
        parsed = nvidia_client.parse_constraints(request.text)
        prototype = nvidia_client.prototype_timetable(parsed)
        return {
            "prototype": prototype,
            "warning": "This is an LLM-generated prototype. Not verified by solver. Use for testing only."
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI provider request failed for model '{nvidia_client.model}'. Check NVIDIA_MODEL and the provider response, then try again.") from e
