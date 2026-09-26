from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import text

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db import Base
from app import db as db_module
from app import models  # noqa: F401 - registers every model with Base.metadata

from app.routers import (
    institutions, departments, academic_terms, academic_years, sections,
    subjects, subject_types, equipment, teachers, rooms, constraints,
    constraint_rules, elective_groups, imports, timetable, admin, auth, llm, ai_agent,
)
from app.models import (
    SubjectType, Equipment as EquipmentModel, Subject, Room, Institution, Department, Teacher, TimetableRun,
)

# create_all only creates tables that don't exist yet - it never adds a
# column to a table an earlier version of the app already created. For
# zero-friction local SQLite dev (a real dev.db predating a model change
# is the common case here, not the exception) each entry additively backfills
# one column onto an existing table. Postgres (production) uses
# `alembic upgrade head` instead - see backend/README.md.
#
# The 4th element is the value existing rows get once the column is added -
# ALTER TABLE ADD COLUMN otherwise leaves every pre-existing row NULL, and
# several of these columns are non-optional in their response schema
# (SubjectResponse.lecture_hours: int, not Optional[int]), so without a
# backfill every GET on a table with pre-migration rows 500s with a
# response-validation error instead of ever reaching a page. None means the
# schema treats NULL as meaningful (e.g. sessions_per_week's "derive it").
SQLITE_COLUMN_BACKFILLS = [
    ("timetable_runs", "term_id", "VARCHAR", None),
    # Phase 2.3/2.4/2.6: L-T-P entry, honest session/period fields, and the
    # hard per-subject parallel-batches override.
    ("subjects", "lecture_hours", "INTEGER", 0),
    ("subjects", "tutorial_hours", "INTEGER", 0),
    ("subjects", "practical_hours", "INTEGER", 0),
    ("subjects", "sessions_per_week", "INTEGER", None),
    ("subjects", "periods_per_session", "INTEGER", 1),
    ("subjects", "back_to_back", "BOOLEAN", 1),
    # Phase 2.5/2.7: per-day lunch replaces the single lunch_start/lunch_end
    # window; default_section_strength backs the "create remaining
    # sections" action.
    ("academic_years", "lunch_windows", "TEXT", "{}"),
    ("academic_years", "default_section_strength", "INTEGER", 60),
    # Phase 4.1: PDF/Excel exports need a short printed code/initials on
    # every subject/teacher - existing rows get one derived below rather
    # than a fixed placeholder, since the right value differs per row.
    ("subjects", "code", "VARCHAR", None),
    ("teachers", "initials", "VARCHAR", None),
    # Phase 2.9: replaces the old boolean batches_run_together with a mode
    # (independent/parallel/sequential/merged); constraint_rules gets a
    # matching column for the per-subject/per-window override rule.
    ("subjects", "batch_scheduling_mode", "VARCHAR", "independent"),
    ("constraint_rules", "batch_mode", "VARCHAR", None),
    # AI edit-plan agent: per-run subject overrides applied on top of the
    # department's normal data when re-solving from a chat instruction.
    ("timetable_runs", "subject_overrides", "TEXT", None),
]

BUILTIN_SUBJECT_TYPES = [
    # id, name, default_block_size, default_room_type, colour_hex - the
    # exact three types the app used to hardcode (Phase 2.1). An admin can
    # add more (seminar, project, internship, workshop) from the catalog.
    ("theory", "Theory", 1, "lecture", "DBEAFE"),
    ("lab", "Lab / Practical", 2, "lab", "D1FAE5"),
    ("tutorial", "Tutorial", 1, None, "EDE9FE"),
]


def _seed_subject_types(db) -> None:
    existing_ids = {t.id for t in db.query(SubjectType).all()}
    for type_id, name, block_size, room_type, colour in BUILTIN_SUBJECT_TYPES:
        if type_id in existing_ids:
            continue
        db.add(SubjectType(
            id=type_id, name=name, default_block_size=block_size,
            default_room_type=room_type, colour_hex=colour, is_builtin=True,
        ))
    db.commit()


def _ensure_default_department(db) -> None:
    """Phase 3.1: the UI is a single-department experience - an admin should
    never have to create an institution and department before touching
    anything else. If nothing exists yet, provision one department so the
    rest of setup (subjects, teachers, rooms, generation) has something to
    attach to. Every column that supports multiple departments/institutions
    stays exactly as it is - this only removes the empty-state dead end,
    it doesn't remove the capability. Institution/Department management is
    still reachable from Settings for colleges that outgrow one department."""
    if db.query(Institution).count() or db.query(Department).count():
        return
    institution = Institution(id="default", name="My Institution")
    db.add(institution)
    db.add(Department(id="default", institution_id=institution.id, name="My Department"))
    db.commit()


_TITLE_PREFIXES = ("prof.", "prof", "dr.", "dr", "mr.", "mr", "mrs.", "mrs", "ms.", "ms")


def _derive_teacher_initials(name: str) -> str:
    words = [w.strip(".") for w in name.split() if w.strip(".")]
    words = [w for w in words if w.lower() not in _TITLE_PREFIXES]
    initials = "".join(w[0].upper() for w in words if w)
    return initials or name[:3].upper()


def _backfill_export_labels(db) -> None:
    """Phase 4.1: a subject/teacher created before `code`/`initials`
    existed has NULL there - give it the same derived default a brand new
    row would get on create, so every existing export target actually has
    something to print instead of a blank cell."""
    changed = False
    for subject in db.query(Subject).filter(Subject.code.is_(None)).all():
        subject.code = subject.id.upper()
        changed = True
    for teacher in db.query(Teacher).filter(Teacher.initials.is_(None)).all():
        teacher.initials = _derive_teacher_initials(teacher.name)
        changed = True
    if changed:
        db.commit()


def _fail_orphaned_runs(db) -> None:
    """A generation runs as a BackgroundTasks job tied to this process - if
    the process restarts (uvicorn --reload picking up a file change, a
    crash, a deploy) while one is in flight, the background thread dies
    mid-solve and the run's row is left stuck at "pending"/"solving"
    forever. Nothing else ever revisits it, so the admin sees the UI poll
    that status with no error and no way to know it will never finish
    (see _run_generation in app/routers/timetable.py, which DOES fail the
    row on any in-process exception - this covers the case where the
    process itself doesn't survive to run that handler). Any such row still
    open at startup could not have been solving for real, since this
    process wasn't running to solve it - fail it outright so a fresh
    generate is the obvious next step instead of an infinite spinner."""
    stuck = db.query(TimetableRun).filter(TimetableRun.status.in_(["pending", "solving"])).all()
    if not stuck:
        return
    now = datetime.now(timezone.utc)
    for run in stuck:
        run.status = "failed"
        run.completed_at = now
        run.llm_explanation = (
            "Generation was interrupted by a server restart before it could finish. "
            "Please generate again."
        )
    db.commit()


def _normalise_equipment_id(raw: str) -> str:
    return "-".join(raw.strip().lower().split())


def _migrate_equipment_catalog(db) -> None:
    """Phase 2.2: equipment used to be free text on both Subject and Room,
    matched by exact string - "Computer" vs "computers" meant zero
    eligible rooms. Backfills the catalog from whatever free text already
    exists (case/whitespace-normalised and deduplicated) and rewrites both
    sides to the canonical ids, idempotently - safe to run on every
    startup since a value already in canonical form is a no-op."""
    canonical_by_norm = {e.id: e.name for e in db.query(EquipmentModel).all()}

    def canonicalise(raw_values):
        result = []
        for raw in raw_values or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            norm_id = _normalise_equipment_id(raw)
            if norm_id not in canonical_by_norm:
                db.add(EquipmentModel(id=norm_id, name=raw.strip()))
                canonical_by_norm[norm_id] = raw.strip()
            if norm_id not in result:
                result.append(norm_id)
        return result

    for subject in db.query(Subject).all():
        canonical = canonicalise(subject.requires_equipment)
        if canonical != (subject.requires_equipment or []):
            subject.requires_equipment = canonical
    for room in db.query(Room).all():
        canonical = canonicalise(room.equipment)
        if canonical != (room.equipment or []):
            room.equipment = canonical
    db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Read app.db's engine/SessionLocal as live module attributes (not
    # names snapshotted at import time) so a test suite that monkeypatches
    # app.db.engine/SessionLocal to an isolated database actually reaches
    # this migration/seeding step - otherwise it silently runs against
    # whatever the real configured DATABASE_URL is instead, which (a)
    # leaves the isolated test db never seeded (subject_types, the default
    # department, ...) and (b) mutates the real dev database as a side
    # effect of running the test suite. Mirrors the same live-attribute
    # pattern _run_generation already uses for this exact reason.
    if settings.DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=db_module.engine)
        with db_module.engine.connect() as conn:
            for table, column, sql_type, default in SQLITE_COLUMN_BACKFILLS:
                existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
                    conn.commit()
                # Runs every startup, not just on the ALTER, so a db that
                # already had this column added (by an earlier version of
                # this same backfill, before it filled defaults) still gets
                # repaired - cheap and a no-op once nothing is NULL.
                if default is not None:
                    conn.execute(
                        text(f"UPDATE {table} SET {column} = :default WHERE {column} IS NULL"),
                        {"default": default},
                    )
                    conn.commit()
        db = db_module.SessionLocal()
        try:
            _ensure_default_department(db)
            _seed_subject_types(db)
            _migrate_equipment_catalog(db)
            _backfill_export_labels(db)
        finally:
            db.close()

    # Not sqlite-specific: any backend can restart mid-generation.
    db = db_module.SessionLocal()
    try:
        _fail_orphaned_runs(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Timetable Generator API",
    description="Constraint-programming based university timetable generation.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(institutions.router)
app.include_router(departments.router)
app.include_router(academic_terms.router)
app.include_router(academic_years.router)
app.include_router(sections.router)
app.include_router(subjects.router)
app.include_router(subject_types.router)
app.include_router(equipment.router)
app.include_router(teachers.router)
app.include_router(rooms.router)
app.include_router(constraints.router)
app.include_router(constraint_rules.router)
app.include_router(elective_groups.router)
app.include_router(imports.router)
app.include_router(timetable.router)
app.include_router(admin.router)
app.include_router(llm.router)
app.include_router(ai_agent.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
