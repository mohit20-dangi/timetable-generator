# SGSITS College Timetable Generator

A web application for generating conflict-free college timetables using Google OR-Tools CP-SAT solver and NVIDIA LLM for natural language constraint parsing.

## Architecture

- **Frontend**: React + TypeScript + Vite + Tailwind CSS
- **Backend**: FastAPI (Python)
- **Solver**: Google OR-Tools CP-SAT — the solver only decides *what goes where*; per-section, per-faculty, and per-room views are built afterwards in plain Python (`app/services/timetable_views.py`), not by the LLM.
- **LLM**: NVIDIA NIM API (OpenAI-compatible), used only to parse natural-language constraints and to explain infeasible solves
- **Database**: MongoDB (via `pymongo`)
- **Auth**: JWT-based admin accounts, invite-only registration

## Quick Start

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in MONGODB_URL, JWT_SECRET_KEY, NVIDIA_API_KEY, ...
python -m app.scripts.create_first_admin   # bootstrap the first admin account
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in:

```
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB_NAME=timetable_generator

JWT_SECRET_KEY=change-me-to-a-long-random-string
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=720
INVITE_EXPIRE_HOURS=72

NVIDIA_API_KEY=your_nvidia_api_key_here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=meta/llama-3.1-70b-instruct
CORS_ORIGINS=["http://localhost:5173"]
```

Add the college website's origin to `CORS_ORIGINS` so it can call the public API from the browser.

## Auth model

Admin registration is **invite-only**:
1. `python -m app.scripts.create_first_admin` creates the very first admin (one-time, run from the shell — there is no open signup endpoint).
2. That admin calls `POST /api/auth/invites` to mint a token for the next admin.
3. The new admin calls `POST /api/auth/register` with that token, then `POST /api/auth/login` to get a JWT.
4. Every write endpoint under `/api/years`, `/api/sections`, `/api/subjects`, `/api/teachers`, `/api/rooms`, `/api/constraints`, and `/api/timetable/generate` requires `Authorization: Bearer <token>`.

## API Endpoints

### Auth
- `POST /api/auth/invites` (admin) - mint an invite token
- `POST /api/auth/register` - create an admin account from an invite token
- `POST /api/auth/login` - get a JWT
- `GET /api/auth/me` (admin) - current admin info

### Academic Years (admin-only)
- `POST /api/years` / `GET /api/years` / `GET /api/years/{id}` / `DELETE /api/years/{id}`
- `POST /api/years/bulk` (CSV/Excel upload) / `GET /api/years/bulk/template`

### Sections (admin-only)
- `POST /api/sections` / `GET /api/sections` / `GET /api/sections/{id}` / `GET /api/sections/year/{year_id}` / `DELETE /api/sections/{id}`
- `POST /api/sections/bulk` (CSV/Excel upload) / `GET /api/sections/bulk/template`
- `POST /api/sections/{id}/subjects` / `DELETE /api/sections/{id}/subjects/{subject_id}` - assign/remove a subject
- `POST /api/sections/{id}/lab-batches` / `DELETE /api/sections/{id}/lab-batches/{batch_id}` - manage lab batches

### Subjects (admin-only)
- `POST /api/subjects` / `GET /api/subjects` / `GET /api/subjects/{id}` / `DELETE /api/subjects/{id}`
- `POST /api/subjects/bulk` (CSV/Excel upload) / `GET /api/subjects/bulk/template`
- `POST /api/subjects/{id}/prerequisites/{requires_id}` / `DELETE .../prerequisites/{requires_id}`

### Teachers (admin-only)
- `POST /api/teachers` / `GET /api/teachers` / `GET /api/teachers/{id}` / `DELETE /api/teachers/{id}`
- `POST /api/teachers/bulk` (CSV/Excel upload) / `GET /api/teachers/bulk/template`
- `POST /api/teachers/{id}/subjects` / `DELETE /api/teachers/{id}/subjects/{subject_id}`

### Rooms (admin-only)
- `POST /api/rooms` / `GET /api/rooms` / `GET /api/rooms/{id}` / `DELETE /api/rooms/{id}`
- `POST /api/rooms/bulk` (CSV/Excel upload) / `GET /api/rooms/bulk/template`

Bulk upload accepts a CSV or `.xlsx` file, one row per record, validating and inserting each row independently - the response reports which ids were created and which rows failed and why, so one bad row doesn't block the rest. List-valued columns (equipment, subject IDs, prerequisite IDs, etc.) use a semicolon-separated cell, e.g. `computers; projector`. `GET .../bulk/template` returns a starter CSV with the expected headers. Fields with nested structure (teacher availability/preferred slots, room availability) aren't part of the bulk format - add those per-record after upload via the existing endpoints.

### Constraints (admin-only)
- `POST/GET/DELETE /api/constraints/time-slots`
- `POST/GET/DELETE /api/constraints/profiles`
- `POST /api/constraints/parse-nl` - parse natural language constraints via LLM
- `POST /api/constraints/prototype` - experimental LLM-only prototype timetable

### Timetable (admin-only)
- `POST /api/timetable/generate` - generate a timetable (runs the solver in the background)
- `GET /api/timetable/runs` / `GET /api/timetable/runs/{id}` / `GET /api/timetable/runs/{id}/entries`
- `GET /api/timetable/runs/{id}/explain` - LLM explanation for an infeasible run
- `GET /api/timetable/runs/{id}/export?format=xlsx|pdf` - export

### Public (no auth — for embedding in the college website)
- `GET /api/public/timetables/sections` / `/sections/{section_id}` - per-class/section weekly grid
- `GET /api/public/timetables/faculty` / `/faculty/{teacher_id}` - per-faculty weekly grid
- `GET /api/public/timetables/rooms` / `/rooms/{room_id}` - room occupancy/availability grid

All public endpoints read the **latest completed** timetable run by default, or a specific one via `?run_id=`.

## Features

- Multi-step setup wizard for configuring entities
- Natural language constraint parsing via NVIDIA LLM
- CP-SAT solver for conflict-free timetable generation, including continuous blocks, prerequisite ordering, simultaneous lab batches, and travel-minimization
- Per-section, per-faculty, and per-room timetable views generated in code from the solver's output
- A public, read-only API for embedding timetables in the college website
- Invite-only admin accounts with JWT auth guarding every write
- Infeasibility explanation with suggested relaxations
- Export to Excel and PDF
- Soft constraint optimization (gaps, preferences, etc.)
