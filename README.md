# SGSITS College Timetable Generator

A web application for generating conflict-free college timetables using Google OR-Tools CP-SAT solver and NVIDIA LLM for natural language constraint parsing.

## Architecture

- **Frontend**: React + TypeScript + Vite + Tailwind CSS
- **Backend**: FastAPI (Python)
- **Solver**: Google OR-Tools CP-SAT
- **LLM**: NVIDIA NIM API (OpenAI-compatible)
- **Database**: SQLite (default) / PostgreSQL

## Quick Start

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

Create a `.env` file in the `backend/` directory:

```
DATABASE_URL=sqlite:///./timetable.db
NVIDIA_API_KEY=your_nvidia_api_key_here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=meta/llama-3.1-70b-instruct
CORS_ORIGINS=http://localhost:5173
```

## API Endpoints

### Academic Years
- `POST /api/years` - Create academic year
- `GET /api/years` - List all years
- `GET /api/years/{id}` - Get specific year
- `DELETE /api/years/{id}` - Delete year

### Sections
- `POST /api/sections` - Create section
- `GET /api/sections` - List all sections
- `GET /api/sections/year/{year_id}` - Get sections by year

### Subjects
- `POST /api/subjects` - Create subject
- `GET /api/subjects` - List all subjects

### Teachers
- `POST /api/teachers` - Create teacher
- `GET /api/teachers` - List all teachers
- `POST /api/teachers/{id}/subjects` - Assign subject to teacher

### Rooms
- `POST /api/rooms` - Create room
- `GET /api/rooms` - List all rooms

### Constraints
- `POST /api/constraints/parse-nl` - Parse natural language constraints
- `POST /api/constraints/profiles` - Create constraint profile
- `POST /api/constraints/section-subjects` - Assign subject to section
- `POST /api/constraints/lab-batches` - Create lab batch
- `POST /api/constraints/prerequisites` - Add prerequisite
- `POST /api/constraints/time-slots` - Create time slot

### Timetable
- `POST /api/timetable/generate` - Generate timetable
- `GET /api/timetable/runs` - List all runs
- `GET /api/timetable/runs/{id}` - Get run details
- `GET /api/timetable/runs/{id}/entries` - Get timetable entries
- `GET /api/timetable/runs/{id}/explain` - Get infeasibility explanation
- `GET /api/timetable/runs/{id}/export?format=xlsx|pdf` - Export timetable

## Features

- Multi-step setup wizard for configuring entities
- Natural language constraint parsing via NVIDIA LLM
- CP-SAT solver for conflict-free timetable generation
- Timetable viewer with section/teacher/room views
- Infeasibility explanation with suggested relaxations
- Export to Excel and PDF
- Soft constraint optimization (gaps, preferences, etc.)