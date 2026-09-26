# Timetable Generator

A constraint-programming based university timetable generator. Give it your departments, subjects,
teachers, rooms and a bell schedule, and it produces conflict-free timetables — with an independent
verifier, plain-language priorities instead of numeric weights, and an AI assistant for bulk edits.

## Architecture

```
backend/    FastAPI + SQLAlchemy + OR-Tools CP-SAT solver
frontend/   React + Vite + TypeScript + Tailwind
```

**Why CP-SAT, not ILP or a genetic algorithm.** Timetabling is almost entirely disjunctive/logical
structure ("these two things can't overlap"), which CP-SAT is purpose-built for — it proves
infeasibility (which powers the diagnostics below), and it runs a portfolio of search strategies
internally, so you get the benefits of local search without hand-tuning a GA's hyperparameters per
college. See `backend/app/solver/model_builder.py` for the full encoding rationale.

**The solver is the only thing that ever emits a schedule.** The AI assistant (§ below) can propose
data changes — teacher limits, constraint rules — for an admin to review and apply, but it can never
generate a timetable itself. This boundary is deliberate: an AI-authored schedule would need the same
verification a solver-authored one gets, with none of the guarantees.

## Core concepts

- **Department-scoped generation.** The solver always solves one department at a time — departments
  have separate students, faculty and rooms, so there's no benefit to modelling them jointly. Sharing
  (a Maths professor teaching CSE, a shared central lab) is handled by freezing already-published
  bookings as hard unavailability before the next department solves — see `scope_mode` below.
- **`scope_mode` on generation**: `fit_into_existing` (default) freezes every already-published class
  outside the requested scope, so a new run can never clash with what's already live. `fresh` ignores
  everything outside scope — faster, but the caller accepts the collision risk.
- **Delivery mode, not just subject type.** A subject's `delivery_mode` (`IN_PERSON`, `MOOC_NPTEL`,
  `SELF_STUDY`, `INDUSTRY`) decides whether it consumes a timetable slot at all. NPTEL courses and
  internships have real `scheme_hours_per_week` (for credits/transcripts) but `weekly_hours = 0`
  (nothing to schedule) — see `app/models/subject.py`.
- **L + T split.** A curriculum row with both lecture and tutorial hours (e.g. L=3, T=1) is entered as
  two Subject rows — one `theory`, one `tutorial` — sharing `linked_group_id`. This keeps each
  component's hours from being silently dropped, which a single `type` + `weekly_hours` field cannot
  express.
- **Elective baskets.** `ElectiveGroup.offered_subject_ids` is the subset of a basket (e.g.
  "Elective-1 offers 8 options") actually running this term. Only offered options are co-scheduled
  into one shared slot, and `GET /api/elective-groups/{id}/preflight` tells you *before* generating
  whether you have enough rooms and teachers for that — instead of a bare INFEASIBLE afterward.

## Quick start

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env       # fill in JWT_SECRET_KEY at minimum
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

SQLite is used automatically in development (`DATABASE_URL=sqlite:///./timetable.db` in `.env`) and
the schema is created on startup. For production, point `DATABASE_URL` at PostgreSQL and run Alembic
migrations instead (see **Production** below).

### Frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, proxies /api to :8000
```

### Seed example data

```bash
cd backend
python seed_example.py
```

Creates an admin account, a demo institution/department, a bell schedule, one section with real
subjects (including an NPTEL course and an internship, to demonstrate they're correctly excluded from
scheduling), generates a timetable, validates it, and publishes it.

## Configuring for a new college

1. **Institution & Department** (Setup Wizard → Department step, or `POST /api/institutions`,
   `POST /api/departments`). Everything else in the wizard applies to the department selected here.
2. **Class times** (Setup Wizard → Class Times, or `POST /api/constraints/time-slots`). Define your
   bell schedule — days and periods. Irregular schedules (a short Saturday, no period 5 on Fridays) are
   fine; the solver only ever treats genuinely back-to-back periods as contiguous.
3. **Academic Years & Sections.** A year (e.g. "III Year") holds a lunch window; sections belong to a
   year.
4. **Subjects.** For each curriculum row: pick `type` (theory/lab/tutorial), `delivery_mode`, and
   `weekly_hours` (the *contact* hours that need scheduling — not the scheme's credit hours, which go
   in `scheme_hours_per_week`). A lab needs `block_size` set to its contiguous block length.
5. **Lab Batches.** Any subject of type `lab` needs at least one `LabBatch` per section, or it will
   never be scheduled (and the pre-flight check will tell you so by name).
6. **Teachers & qualifications.** Map teachers to the subjects they can teach. A lab with N
   simultaneous batches needs at least N qualified teachers.
7. **Rooms.** Set `type`, `capacity`, `equipment`, and optionally `department_id` (a room with no
   department is treated as shared across the whole institution).
8. **Electives** (if applicable). Create an `ElectiveGroup`, mark which options are actually offered
   this term, and run its pre-flight check.
9. **Constraints.** Pick a preset (Balanced / Student-friendly / Teacher-friendly) or set each rule's
   importance in plain language — no numeric weights anywhere in the UI.
10. **Generate.** Choose scope (all / one year / specific sections), scope mode, and how many
    alternative timetables to produce, then generate. A failed generation names the specific subject,
    teacher, or resource shortfall that caused it — never a bare "INFEASIBLE".

## Bulk import

`POST /api/import/excel` (or `/csv`) accepts a workbook with one sheet per entity
(`AcademicYears`, `Sections`, `Subjects`, `Teachers`, `Rooms`, `SectionSubjects`, `TeacherSubjects`,
`LabBatches`, `Prerequisites`, `TimeSlots`). Download a pre-formatted template from
`GET /api/import/excel-template`. `/excel/preview` validates without writing anything.

## AI-assisted features (optional)

Set `LLM_API_KEY` (plus `LLM_BASE_URL` and `LLM_MODEL` for your provider - OpenRouter,
OpenAI, NVIDIA NIM, a local Ollama server, or any other OpenAI-compatible endpoint) in
`backend/.env` to enable:

- **Natural-language constraint parsing** (Constraints step): describe priorities in plain English;
  the AI maps them onto the same rule catalog the UI uses, grounded in your institution's real
  teacher/room/section/subject ids — it never invents one.
- **AI Assistant** (Constraints step): "Increase every teacher's max daily classes by 1", "Prof.
  Sharma is unavailable Friday afternoons". The agent can only ever *propose* changes
  (`POST /api/ai/agent/plan`) — nothing is written until you review and click Apply
  (`POST /api/ai/agent/apply`), which is logged to the audit trail with the original instruction as
  the reason.
- **Plain-language infeasibility explanations**: when generation fails, the deterministic diagnostic
  facts (always computed regardless of whether a key is set) are optionally restated more
  conversationally — the model is never allowed to add a cause beyond what's already verified.

Without a key, all three degrade gracefully (503 with a clear message) — the rest of the system is
unaffected.

## Testing

```bash
cd backend
pytest                          # unit + integration + property-based (Hypothesis)
```

Coverage includes:
- **Unit** — calendar/contiguity math, diagnostics, weight resolution.
- **Property-based** (`test_validator_property.py`) — for any solver-feasible randomly generated
  instance, the independently-written validator finds zero violations. This is the single most
  valuable test in the suite.
- **Golden regression** (`test_golden_regression.py`) — locks shut specific defects observed in a
  previous build's real output: a subject repeated 3× in one day, one subject taught by two different
  teachers for the same section, lab batches serialised instead of parallel.
- **Integration** (`test_full_flow.py`) — full HTTP flow via FastAPI's TestClient: bootstrap → build a
  department → generate → validate → publish → per-user scoped view; plus a test proving the
  `fit_into_existing` scope mechanism actually prevents a shared teacher being double-booked across two
  separately generated runs.

## Production

- Switch `DATABASE_URL` to PostgreSQL and run `alembic upgrade head` instead of relying on
  `Base.metadata.create_all` (which only runs for SQLite).
- Move timetable generation off FastAPI's `BackgroundTasks` and onto a real job queue (Celery/RQ) once
  solve times or concurrency exceed a single worker process — the solver code itself
  (`app/solver/engine.py`) doesn't change either way.
- Set a long, random `JWT_SECRET_KEY`; the example in `.env.example` is not for production use.
- `SOLVER_MAX_SECONDS` / `SOLVER_NUM_WORKERS` in `.env` tune the CP-SAT time budget and CPU parallelism
  per solve.

## Project layout

```
backend/app/
  models/          SQLAlchemy models (institution → department → ... → generated_entry)
  schemas/         Pydantic request/response models
  routers/         FastAPI endpoints, one file per resource
  solver/          The engine - types.py, calendar.py, model_builder.py, engine.py,
                   validator.py (independent of model_builder by design), diagnostics.py, weights.py,
                   data_loader.py (the only file that touches both ORM and solver types)
  services/        schedule_validator.py (independent post-hoc DB check), exporters.py, ai_agent.py
  llm/             OpenAI-compatible LLM client for NL constraint parsing / infeasibility explanations
  auth/            JWT auth, bcrypt hashing, role-based dependencies
frontend/src/
  pages/           Route-level views (SetupWizard, TimetableViewer, MyTimetable, ...)
  components/      Reusable pieces - one per setup-wizard step, plus AIAssistantPanel, ElectiveGroupManager
  context/         AuthContext, DepartmentContext (the active department, shared across the wizard)
  api/client.ts    All backend calls, one export per resource
```
