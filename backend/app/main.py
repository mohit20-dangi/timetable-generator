from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db import engine, Base
from app.routers import academic_years, sections, subjects, teachers, rooms, constraints, timetable, llm

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SGSITS Timetable Generator",
    description="Constraint-based timetable generation with OR-Tools CP-SAT and NVIDIA LLM",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(academic_years.router)
app.include_router(sections.router)
app.include_router(subjects.router)
app.include_router(teachers.router)
app.include_router(rooms.router)
app.include_router(constraints.router)
app.include_router(timetable.router)
app.include_router(llm.router)

@app.get("/")
def root():
    return {"message": "SGSITS Timetable Generator API", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}