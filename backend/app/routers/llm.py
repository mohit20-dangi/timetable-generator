from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json
import uuid

from app.schemas import (
    NLConstraintParseRequest, NLConstraintParseResponse, LabRotationGroupCreate,
)
from app.schemas.constraint_rule import ConstraintRuleBase
from app.llm.client import claude_client
from app.models import Room, Section, SectionSubject, Subject, Teacher, User
from app.db import get_db
from app.auth.dependencies import require_dept_admin
from app.auth.scope import scoped

router = APIRouter(prefix="/api/constraints", tags=["LLM"])

_TARGET_CATALOG_KEY = {"teacher": "teachers", "room": "rooms", "section": "sections", "subject": "subjects"}


def _validated_rules(candidates: list, catalog: dict, instruction: str):
    """Keeps only the model's candidates that are real, saveable rules: the
    target id must exist in the catalog and the rule must pass the same
    validation a manually created rule does. Everything else is reported back
    as an ambiguity rather than silently dropped or guessed at."""
    rules, rejected = [], []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        target_type = candidate.get("target_type")
        target_id = candidate.get("target_id")
        known_ids = {item["id"] for item in catalog.get(_TARGET_CATALOG_KEY.get(target_type, ""), [])}
        wildcard = candidate.get("rule_type") == "max_subjects_per_day" and target_id == "*"
        label = candidate.get("description") or f"{candidate.get('rule_type')} for {target_id}"
        if target_id not in known_ids and not wildcard:
            rejected.append(f"{label} (couldn't match it to anything in your setup)")
            continue
        payload = {k: v for k, v in candidate.items() if v not in (None, "", {}) or k in ("day",)}
        payload["day"] = candidate.get("day") or None
        payload["source"] = "ai_parsed"
        payload["raw_instruction"] = instruction
        try:
            rule = ConstraintRuleBase(**payload)
        except Exception as exc:
            reason = getattr(exc, "errors", lambda: [{"msg": str(exc)}])()[0]["msg"]
            rejected.append(f"{label} ({reason.removeprefix('Value error, ')})")
            continue
        rules.append(rule.model_dump(mode="json"))
    return rules, rejected


def _validated_rotations(candidates: list, catalog: dict, db: Session, instruction: str):
    """Turns the model's lab-rotation candidates into ones the admin could
    actually save: real section, two or more real LAB subjects that the
    section genuinely takes, same session length. Anything else comes back
    as an ambiguity - a rotation quietly saved against the wrong subjects
    would change when every one of those labs runs."""
    sections = {item["id"] for item in catalog.get("sections", [])}
    rotations, rejected = [], []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        label = candidate.get("description") or candidate.get("name") or "lab rotation"
        section_id = candidate.get("section_id")
        subject_ids = [s for s in (candidate.get("subject_ids") or []) if isinstance(s, str)]
        if section_id not in sections:
            rejected.append(f"{label} (couldn't match the section to anything in your setup)")
            continue
        subjects = [db.get(Subject, sid) for sid in subject_ids]
        unknown = [sid for sid, subj in zip(subject_ids, subjects) if subj is None]
        if unknown:
            rejected.append(f"{label} (unknown subject(s): {', '.join(unknown)})")
            continue
        non_lab = [subj.name for subj in subjects if subj.type != "lab"]
        if non_lab:
            rejected.append(f"{label} (only lab subjects can rotate; {', '.join(non_lab)} are not labs)")
            continue
        mapped = {
            row.subject_id for row in
            db.query(SectionSubject).filter(SectionSubject.section_id == section_id).all()
        }
        missing = [subj.name for subj, sid in zip(subjects, subject_ids) if sid not in mapped]
        if missing:
            rejected.append(f"{label} (that section doesn't take {', '.join(missing)})")
            continue
        if len({max(1, subj.periods_per_session or 1) for subj in subjects}) > 1:
            rejected.append(f"{label} (its labs are different lengths, so they can't share a round)")
            continue
        try:
            rotation = LabRotationGroupCreate(
                id=f"rot_{section_id}_{uuid.uuid4().hex[:6]}",
                name=candidate.get("name") or f"{section_id} lab rotation",
                section_id=section_id, subject_ids=subject_ids,
                day=candidate.get("day") or None,
                start_time=candidate.get("start_time") or None,
                end_time=candidate.get("end_time") or None,
            )
        except Exception as exc:
            reason = getattr(exc, "errors", lambda: [{"msg": str(exc)}])()[0]["msg"]
            rejected.append(f"{label} ({reason.removeprefix('Value error, ')})")
            continue
        payload = rotation.model_dump(mode="json")
        payload["source"] = "ai_parsed"
        payload["raw_instruction"] = instruction
        payload["description"] = candidate.get("description") or label
        rotations.append(payload)
    return rotations, rejected


def _validated_teacher_counts(candidates: list, db: Session):
    """"This lab needs two instructors" as a reviewable change to one
    Subject - never applied here, only proposed."""
    counts, rejected = [], []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        subject = db.get(Subject, candidate.get("subject_id"))
        label = candidate.get("description") or f"teacher count for {candidate.get('subject_id')}"
        if subject is None:
            rejected.append(f"{label} (couldn't match the subject to anything in your setup)")
            continue
        try:
            required = int(candidate.get("teachers_required"))
        except (TypeError, ValueError):
            rejected.append(f"{label} (no usable number of teachers)")
            continue
        if required < 1:
            rejected.append(f"{label} (a class needs at least one teacher)")
            continue
        counts.append({
            "subject_id": subject.id, "subject_name": subject.name,
            "teachers_required": required, "current_teachers_required": subject.teachers_required or 1,
            "description": candidate.get("description") or label,
        })
    return counts, rejected


@router.post("/parse-nl", response_model=NLConstraintParseResponse)
def parse_natural_language_constraints(
    request: NLConstraintParseRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_dept_admin),
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
            "teachers": [{"id": item.id, "name": item.name} for item in scoped(db.query(Teacher), Teacher, admin, request.department_id).all()],
            "sections": [{"id": item.id, "name": item.name} for item in scoped(db.query(Section), Section, admin, request.department_id).all()],
            "subjects": [{"id": item.id, "name": item.name} for item in scoped(db.query(Subject), Subject, admin, request.department_id).all()],
            "rooms": [{"id": item.id, "name": item.name} for item in scoped(db.query(Room), Room, admin, request.department_id).all()],
        }
        parsed = claude_client.parse_constraints(request.text, catalog=catalog)
        rules, rejected = _validated_rules(parsed.get("constraints", []), catalog, request.text)
        rotations, rot_rejected = _validated_rotations(
            parsed.get("lab_rotations", []), catalog, db, request.text,
        )
        counts, count_rejected = _validated_teacher_counts(parsed.get("subject_teacher_counts", []), db)
        parsed["constraints"] = rules
        parsed["lab_rotations"] = rotations
        parsed["subject_teacher_counts"] = counts
        return NLConstraintParseResponse(
            parsed_constraints=parsed,
            raw_response=json.dumps(parsed, indent=2),
            ambiguities=[*parsed.get("ambiguities", []), *rejected, *rot_rejected, *count_rejected],
            unsupported_requests=parsed.get("unsupported_requests", []),
            lab_rotations=rotations,
            subject_teacher_counts=counts,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=(
                f"The AI request failed for model '{claude_client.model}' "
                f"({type(e).__name__}: {e}). Nothing was changed - try rephrasing, or try again."
            ),
        ) from e
