from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json
from app.schemas import NLConstraintParseRequest, NLConstraintParseResponse
from app.llm.client import claude_client
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
    """Parses an admin's plain-English instruction into structured
    constraint candidates, grounded in the real catalog of teachers,
    sections, subjects and rooms so the model can only ever reference ids
    that actually exist. The admin reviews and approves before anything is
    applied - see ConstraintRule.source == 'ai_parsed' and the audit log
    entry written when a parsed rule is actually saved.
    """
    try:
        catalog = {
            "teachers": [{"id": item.id, "name": item.name} for item in db.query(Teacher).all()],
            "sections": [{"id": item.id, "name": item.name} for item in db.query(Section).all()],
            "subjects": [{"id": item.id, "name": item.name} for item in db.query(Subject).all()],
            "rooms": [{"id": item.id, "name": item.name} for item in db.query(Room).all()],
        }
        parsed = claude_client.parse_constraints(request.text, catalog=catalog)
        return NLConstraintParseResponse(
            parsed_constraints=parsed,
            raw_response=json.dumps(parsed, indent=2),
            ambiguities=parsed.get("ambiguities", []),
            unsupported_requests=parsed.get("unsupported_requests", []),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"AI provider request failed for model '{claude_client.model}'. Try again.",
        ) from e
