from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db import create_indexes
from app.routers import (
    academic_years, sections, subjects, teachers, rooms,
    constraints, timetable, llm, auth, public,
)

app = FastAPI(
    title="SGSITS Timetable Generator",
    description="Constraint-based timetable generation with OR-Tools CP-SAT and NVIDIA LLM",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_indexes()


# Admin (auth-protected) routers
app.include_router(auth.router)
app.include_router(academic_years.router)
app.include_router(sections.router)
app.include_router(subjects.router)
app.include_router(teachers.router)
app.include_router(rooms.router)
app.include_router(constraints.router)
app.include_router(timetable.router)
app.include_router(llm.router)

# Public, read-only, no-auth router (for embedding in the college website)
app.include_router(public.router)


@app.get("/")
def root():
    return {"message": "SGSITS Timetable Generator API", "version": "2.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}
