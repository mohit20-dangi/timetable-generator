from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db import Base, engine
from app import models  # noqa: F401 - registers every model with Base.metadata

from app.routers import (
    institutions, departments, academic_terms, academic_years, sections,
    subjects, teachers, rooms, constraints, constraint_rules, elective_groups,
    imports, timetable, admin, auth, llm, ai_agent,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # SQLite (dev) gets its schema created here for zero-friction local
    # runs. Postgres (production) should use `alembic upgrade head`
    # instead - see backend/README.md - so this is a no-op there beyond
    # confirming tables that already match.
    if settings.DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
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
