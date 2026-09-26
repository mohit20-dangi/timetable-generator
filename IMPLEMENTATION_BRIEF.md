# Timetable Generator — Rebuild Brief

> **How to use this document.** Paste the "Prompt" section below into a fresh Claude Code
> session in this repo, or just tell the session to read this file. Work **one phase at a
> time**, in order. Do not start Phase N+1 until Phase N's acceptance criteria pass.
>
> Written for: the engineer/agent implementing these changes.

---

## Prompt

You are working on **Timetable Generator**, a university scheduling product built with
FastAPI + SQLAlchemy + OR-Tools CP-SAT (`backend/`) and React + TypeScript + Tailwind
(`frontend/`). Read `CLAUDE.md` first — its priorities (correctness → maintainability →
debuggability → performance → configurability) still govern.

A full audit has been done. This document is the result. Your job is to implement it,
phase by phase.

**Ground rules for this work:**

1. **Do not write new tests until Phase 4.** The owner asked for this explicitly. Existing
   tests in `backend/tests/` must keep passing; update them when behaviour intentionally
   changes.
2. **Phases are ordered by risk, not by visibility.** Phase 0 and Phase 1 fix things that
   silently destroy data or silently ignore constraints. They come before any redesign.
3. **Every UI string is read by a college administrator, not an engineer.** See
   [§ Copy rules](#copy-rules). No mention of CP-SAT, solvers, objectives, ranks, or
   validation ever reaches the screen.
4. **Do not add abstraction for hypothetical futures.** CLAUDE.md forbids it and this
   codebase already has several dormant features (see Phase 1) that cost more than they
   earned.
5. **Ask before deleting a table or column.** Several tables are currently unused but
   intentional (`AcademicTerm`, `Prerequisite`). Phase 1 wires them up rather than
   dropping them.

**Reference assets, in the repo root:**

| File | What it is |
|---|---|
| `WhatsApp Image 2026-09-20 at 9.48.09 PM.jpeg` | **The target export format.** A real departmental timetable PDF (B.Tech IV A and IV B). Match this. |
| `WhatsApp Image 2026-09-16 at 1.06.*.jpeg` | Real curriculum scheme tables (L-T-P). The input documents Phase 2 and Phase 5 are built around. |
| `Screenshot 2026-09-20 2148*.png` | **What the app produces today.** These are the *bad* output — use them only to understand what's wrong. |

---

## Phase 0 — Stop the data loss

Nothing else is safe until these are fixed. No UI work in this phase.

### 0.1 Reset never destroys timetable history

**File:** `backend/app/routers/admin.py`

`reset("sections")`, `reset("years")`, and `reset("constraints")` each call
`db.query(TimetableRun).delete()` and `db.query(GeneratedEntry).delete()` with **no
filter**. Resetting sections currently destroys every timetable ever generated, for every
year and every department.

- Timetable history becomes its own explicit scope (`"timetables"`). No other scope
  touches `TimetableRun`, `GeneratedEntry`, or `Reservation`.
- Add `GET /api/admin/data/reset/{scope}/preview` returning exact counts of what will be
  deleted **and what will be kept**, e.g.
  `{"deletes": {"academic_years": 3, "sections": 7, "lab_batches": 14}, "keeps": {"timetables": 6}}`.
- `TimeSlot` must not be deleted by the `constraints` scope — it is the bell schedule, not
  a constraint.

**Acceptance:** generate a timetable, reset sections, confirm the run and its entries still
exist and the timetable still renders.

### 0.2 Cascades and referential integrity

- Enable SQLite foreign keys. Add a `PRAGMA foreign_keys=ON` connect-event listener in
  `backend/app/db.py`. Without it every delete in this app leaves orphans.
- `delete_academic_year` (`routers/academic_years.py`) and `delete_section`
  (`routers/sections.py`) perform no cascade at all today. Define and implement:

| Deleting | Cascade | Refuse if | Warn about |
|---|---|---|---|
| Academic year | its sections → their lab batches → their section-subject rows | — | count of sections/batches, and that timetables are kept |
| Section | its lab batches, its section-subject rows | — | same |
| Subject | its section-subject, teacher-subject, prerequisite rows; remove from every `ElectiveGroup.offered_subject_ids` | it appears in a **published** timetable | count of sections teaching it |
| Teacher | its teacher-subject rows | it appears in a **published** timetable | subjects that would be left with no qualified teacher |
| Room | its reservations | it appears in a **published** timetable | subjects that would be left with no eligible room |
| Lab batch | — | it appears in a **published** timetable | — |

- Every delete endpoint returns a preview when called with `?dry_run=true`, so the UI can
  show "this will also delete…" before confirming.

### 0.3 Editing a class must create a version, not mutate the live one

**File:** `backend/app/routers/timetable.py`, `edit_entry` (~line 447)

Today the endpoint mutates the current run's rows in place and returns the same run.
Consequences: the modal's "this creates a new draft" is false, `change_summary` is empty,
"View draft run #N" navigates to the run you're already on, and **editing a published
timetable silently changes the live one.**

- Copy all rank-1 entries into a new `TimetableRun` with `parent_run_id` set,
  `is_published=False`, `status="completed"`, and a human `change_summary`:
  `"Moved Data Structures from Monday period 2 to Tuesday period 4"`.
- Apply the move on the **new** run's rows. Return the new run.
- `use_alternative` (same file, ~line 291) already does exactly this — use it as the
  template.
- Refuse an in-place edit of a published run with a clear 409.
- Frontend `EditEntryModal.tsx`: the success panel must show the real summary and navigate
  to the genuinely new run id.

### 0.4 Duplicate-ID and existence checks on every create

These currently raise a raw `IntegrityError` → HTTP 500 with no `detail`, which the
frontend shows as a generic "could not create" message. This is the cause of the
intermittent lab-batch failure.

- `create_lab_batch` (`routers/constraints.py`): check the section exists (400), check the
  id is free (409).
- `add_section_subject`, `add_teacher_subject`, `add_prerequisite`: same treatment (409 on
  re-add, 400 on unknown reference).
- `create_academic_year`, `create_subject`, `create_teacher`: 409 on duplicate id.
- `create_constraint_profile`: 409 on duplicate id.

Match the message style already used in `create_section`:
`"A section with this id already exists"`.

### 0.5 Publish correctness

`publish_run` un-publishes other runs sharing a `section_id`, but ignores entries that
only have a `batch_id`. A lab-only run can stay published next to its replacement.
Resolve batch → section before comparing.

---

## Phase 1 — Make the controls that already exist actually work

Every item here is a field the admin fills in, the UI displays, and the solver ignores.
This is the most important phase in the document.

### 1.1 Teacher availability becomes a hard constraint

`data_loader.py` computes `TeacherInfo.unavailable_slot_indices`, and **nothing in
`model_builder.py` reads it.** A teacher marked unavailable on Friday is scheduled on
Friday. `services/schedule_validator.py` doesn't catch it either.

In `build_model`, for each group's `presence_teacher[t]` boolean, forbid any demand whose
occupied slots intersect that teacher's unavailable set:

```
for each demand d in group, for each teacher t in group.presence_teacher:
    forbidden = [s for s in d.valid_start_slot_indices
                 if set(occupied_indices(s, d.duration, ...)) & teachers[t].unavailable_slot_indices]
    if forbidden:
        model.AddLinearExpressionInDomain(
            start[d.id], Domain.FromValues(allowed)
        ).OnlyEnforceIf(presence_teacher[t])
```

### 1.2 Room availability becomes a hard constraint

Same shape, using `presence_room[(demand_id, room_id)]` and
`RoomInfo.unavailable_slot_indices`.

⚠️ **Semantic trap:** a room availability window currently means *the only time the room
may be used*. Adding one Monday window silently makes the room unusable Tue–Sat. Either
state that plainly next to the field, or — preferred — invert the model to **blocked
times**, which is what admins mean. Pick one, be consistent across teachers and rooms, and
migrate existing rows.

### 1.3 Teacher workload caps become hard constraints

`max_daily_classes`, `max_weekly_hours`, `max_continuous_classes` are collected, stored,
shown, and passed to the solver. None is constrained. Add all three:

- **Daily:** per teacher per day, `sum(periods occupied) <= max_daily_classes`.
- **Weekly:** per teacher, `sum over all days <= max_weekly_hours`.
- **Continuous:** for every window of `max_continuous_classes + 1` consecutive same-day
  slots, at most `max_continuous_classes` may be occupied by that teacher.

Count *periods occupied*, not sessions — a 2-period lab is 2 hours of load.

Also mirror all three (plus 1.1 and 1.2) in `services/schedule_validator.py`, so the
independent post-save check has the same coverage.

### 1.4 `ConstraintRule` rows must reach the solver

The AI assistant proposes rules, the admin approves them, they are written and audited —
and **no code path reads `ConstraintRule`.** "Prof. Sharma is unavailable Friday
afternoons" has zero effect on the timetable.

In `data_loader.load_department_problem`, load active `ConstraintRule` rows for the
department and fold them in:

| `rule_type` | Effect |
|---|---|
| `teacher_unavailable` | union into that teacher's `unavailable_slot_indices` |
| `room_unavailable` | union into that room's `unavailable_slot_indices` |
| `section_unavailable` | remove those slots from that section's demands' valid starts |
| `teacher_preferred` | union into `preferred_slot_indices` |
| `max_daily_override` | override that teacher's `max_daily_classes` |
| `custom` | not schedulable — surface as a warning, never silently drop |

Respect `priority`: `hard` constrains, `soft` contributes a weighted objective term.

### 1.5 "Must have" must actually be hard

`weights.py` defines `is_must_have()` and never calls it. Selecting "Must have" produces a
soft weight of 1000 while the UI promises *"Treated as a hard rule."* Either promote the
rules that can be made hard (`minimize_student_gaps` → zero gaps; `parallel_lab_batches` →
equality), or change the UI text to the truth. Prefer promoting.

### 1.6 Surface generation warnings

`solver_output.warnings` holds things like *"Database Systems Lab is a lab subject for
Section A but has no lab batches configured — it will not be scheduled."* It is stored and
displayed nowhere. A run can silently drop subjects and still report success.

- Show warnings on the run page and in the generation result, as
  **"3 things were skipped"** with the list expandable.
- A run with warnings gets a distinct status chip — not the same green as a clean run.

### 1.7 Wire up `Prerequisite` and `AcademicTerm`, or remove them

Both have models, routers, and zero readers.

- **Prerequisite** — CLAUDE.md lists it as a domain constraint. Within one term it means
  "don't schedule B before A on the same day." Implement that, or delete the table and say
  so in CLAUDE.md.
- **AcademicTerm** — holds real term dates, working days, and holidays. Link a
  `TimetableRun` to a term, and use it for (a) the `.ics` export's date range, which is
  currently hardcoded to 15 weeks, and (b) the `w.e.f.` date and `Session:` line in the PDF
  header.

---

## Phase 2 — Data model changes

### 2.1 Subject types become a catalog

`type` is a hard enum (`theory | lab | tutorial`) in `schemas/subject.py` and drives colour
coding throughout. The owner needs to add types (seminar, project, internship, workshop).

New table `subject_types`: `id`, `name`, `default_block_size`, `default_room_type`,
`colour_hex`, `is_builtin`. Seed the existing three. `Subject.type` becomes a FK. Every
colour lookup (`TimetableViewer.getSubjectColor`, `exporters.SUBJECT_COLORS`) reads the
catalog instead of a hardcoded map.

### 2.2 Equipment becomes a catalog

Free text on both sides, matched by exact string
(`set(subject.requires_equipment) <= set(room.equipment)`). One typo —
`Computer` vs `computers` — means zero eligible rooms and an infeasible run with a message
that never mentions equipment.

New table `equipment`: `id`, `name`. Rooms pick from it, subjects pick from it, both via
multi-select. "Add new equipment" writes to the catalog. Migrate existing free-text values
by normalising and de-duplicating.

### 2.3 L-T-P entry replaces the two confusing hour fields

Today the form asks for both `scheme_hours_per_week` and `weekly_hours` and explains the
difference in grey text. They *are* different, but the admin shouldn't compute it.

- Ask for **L**, **T**, **P** exactly as the scheme table prints them (see the scheme
  photos), plus `category` and `delivery_mode`.
- **Derive** contact hours: `IN_PERSON` → L+T+P; `MOOC_NPTEL`/`INDUSTRY` → 0;
  `SELF_STUDY` → 0 unless a block is reserved.
- Show the derived number with an **"override"** link. The override case is real and comes
  straight from the reference scheme: `Internship/Entrepreneurship (Up to TRL 5)
  Evaluation` is L=0 T=0 P=0 yet appears on the IV-year timetable as `CO4448_INTERN` —
  scheme hours 0, contact hours 1.
- Keep both columns in the database; only the input experience changes.

### 2.4 Block size vs continuous — make the checkbox real

`needs_continuous_block` is read by **nothing**; `block_size` is applied unconditionally,
so blocks are always contiguous. Replace the two fields with three honest questions:

- **Sessions per week** — how many times it meets
- **Periods per session** — 1 for theory, 2–3 for a lab
- **Must the periods be back-to-back?** — on by default for labs

When back-to-back is off, emit separate single-period demands and add a soft term
preferring the same day.

### 2.5 Lunch becomes per-day

Lunch is one window on `AcademicYear` and is enforced only by removing candidate start
slots. The reference timetable shows lunch is **not uniform**: IV-B has a class Thursday
12:00–13:00 while Mon–Wed are lunch.

Move to a per-day lunch definition on the year (`{"Mon": ["12:00","13:00"], ...}`, a day
may be absent). The grid and both exports render a lunch band that merges only across the
days that actually have lunch.

### 2.6 Per-subject hard parallel labs

`parallel_lab_batches` is soft-only. Add `Subject.batches_run_together: bool`. When true,
add the hard equality `model.Add(start[other] == anchor)` — the elective co-scheduling code
in `model_builder.py` already does exactly this. Leave the soft dial for everything else.

Note from the reference timetable: real labs there run **one batch per day** (A1 Monday,
A2 Tuesday, A3 Wednesday). Default this to **off**.

### 2.7 Section count enforcement

`AcademicYear.num_sections` is never checked. Keep it as a *target*: show "2 of 3 created",
block creating the 4th with a clear message, and add a **"create the remaining sections for
me"** button that generates A/B/C with the year's default strength.

### 2.8 Lab batch strength vs section strength

Sum of a section's batch strengths:
- **exceeds** section strength → block with a clear message
- **is under** section strength → warn, don't block (real batches are uneven and admins
  enter approximations)

---

## Phase 3 — Information architecture and redesign

### 3.1 Remove Institution and Department from the flow

Keep every column — retrofitting tenancy later is the migration that kills projects. Only
the *experience* becomes single-department:

- Delete the `department` step from the wizard.
- Auto-provision one institution + one department on first run.
- `DepartmentContext` resolves it silently.
- Department management moves to **Settings**, for when multi-department is turned on.
- Teacher and room "department" free-text inputs become dropdowns sourced from the
  `Department` table. This is the `cse` / `CSE` / `Computer Science` problem — free text
  cannot be fixed by validation, only by removing the keyboard.

**Related, not in scope for this phase but write it down:** `User.department_id` exists and
is enforced nowhere. Every list endpoint is `db.query(Model).all()`. A CSE admin sees every
department's data. That's the real answer to "the department only has access to its own
data" and it needs a scoping dependency on every query. Flag it; don't build it yet.

### 3.2 New navigation

Replace the 12-step wizard:

```
Dashboard            what's configured, what's missing, last timetable, Generate
Setup
  ├ Years & Sections      merged — same mental object; per-day lunch lives here
  ├ Subjects              L-T-P entry, type catalog, pagination
  ├ Curriculum            NEW — assign subjects to sections
  ├ Electives             shown only when a section has elective subjects
  ├ Lab Batches
  ├ Teachers              + their subjects, availability
  ├ Rooms                 + equipment
  └ Import from Excel     moved to the END — an accelerator, not step 2
Scheduling Rules     priorities + AI
Timetables           runs → viewer → versions
Settings             bell schedule, term dates, department, Danger Zone
```

Today "Bulk Excel" is step 2 — before the admin knows what any of the sheets mean.

### 3.3 The Curriculum page (new)

The current "Assign Subjects to Sections" matrix renders **one column per subject**. With
50 subjects it is a 50-column table.

- Section picker on the left; that section's subjects on the right.
- Search, filter by category/type, bulk add/remove.
- **"Copy from another section"** — sections within a year usually take identical subjects.
- **Total contact hours per week** for the selected section, against the number of periods
  the bell schedule offers. This single number tells the admin immediately whether the week
  is oversubscribed, which is the most common cause of an infeasible run.

### 3.4 Pagination and complete tables

Every list page currently renders every row, and most show a fraction of the fields:

| Page | Fields shown / total | Also needs |
|---|---|---|
| Subjects | 5 of 15 | pagination, column visibility |
| Teachers | 5 of 9 | weekly hours, availability summary, subject count |
| Rooms | 5 of 8 | department, shared with, availability summary |
| Sections | shows `year_id` instead of the year's name | — |

Build **one** reusable table component: search, column visibility, page size (25/50/100),
sticky header, row actions. Use it everywhere including Timetable runs, Electives, and Lab
batches.

Add server-side pagination and filtering to the list endpoints while you're there — they
all return whole tables today.

### 3.5 Electives

Keep the page separate from Subjects. A basket is not a subject; it is a constraint saying
*"these N subjects share one timeslot and one student cohort."* Merging it would put a
many-to-many grouping UI inside a single-row form. But:

- Move it directly after Curriculum in the flow.
- Show an "Elective-1" chip on those subjects in the Subjects table, linking here.
- **Render the `must_be_parallel` toggle.** It exists on the model and in the form's state
  but no checkbox is ever drawn, so it is hardcoded on. Parallel must be optional.
- **Add an edit form.** There is none today — only create and delete.
- Replace the "split the basket" sentence, which nobody understands, with three buttons:
  **"Offer fewer options" / "Add a room" / "Let them run at different times."**
- **Fix the preflight** (`routers/elective_groups.py`): it counts every room of the right
  type in the entire database, ignoring department ownership, availability windows, and
  whether the room is free at any common hour. It reports "feasible" and then generation
  fails.

### 3.6 Validation rules

Apply to teacher availability, teacher preferred times, and room availability alike:

| Rule | Message |
|---|---|
| End must be after start, same day | *"End time must be after start time. For 4 PM, enter 16:00."* |
| Two windows on the same day must not overlap | *"This overlaps 09:00–16:00 on Monday. Merge them into one window."* |
| Window contains no configured period | *"No classes are scheduled in this window."* (warn) |
| Preferred window outside availability | *"Prof. Sharma prefers 09:00–11:00 Friday but isn't available on Friday."* (warn) |
| `max_daily_classes` > periods per day | *"Max 8 — this schedule has 8 periods a day."* |
| `max_weekly_hours` > periods/day × teaching days | same pattern |
| `max_continuous_classes` > longest back-to-back run | same pattern |

On "a day has 24 hours": don't cap at 24. Cap at what the bell schedule actually offers and
show the reason in the hint.

Availability and preferred times may overlap each other — that's the normal case
(preferred ⊆ available). Only *internal* overlap within one list is an error.

### 3.7 Teacher ↔ subject assignment is broken

`TeacherForm.handleEdit` sets `subjects: []` — it never loads existing qualifications — and
`handleSubmit` strips `subjects` before the update call. You can never see or change a
teacher's subjects after creation.

- Add `GET /api/teachers/{id}/subjects` (does not exist).
- Load into the form on edit; send on update.
- Add the reverse view on the Subjects page: which teachers can teach this subject, and a
  warning when the answer is none.

### 3.8 The Danger Zone page

The reset panel currently sits at the top of every wizard step.

- Its own page under Settings, reached deliberately.
- Shows the Phase 0.1 preview: what will be deleted **and what will be kept**.
- Typed confirmation for destructive scopes.
- After completing: refresh the data and redirect to the affected page.

### 3.9 Generation flow

- Generate → progress → **land on the timetable automatically.** Today it leaves the admin
  on a wizard step with a paragraph telling them to go find it in another page.
- Fix the 5-minute abort: the `setTimeout` in `GenerateButton.tsx` reads a stale
  `isGenerating` closure and never fires. Also `SOLVER_MAX_SECONDS` is 240 while the UI
  promises 300 — reconcile them.
- Show warnings (Phase 1.6) on arrival.

### 3.10 Visual pass

- Wizard progress bar → persistent left sub-nav with completion ticks and a **blocking
  issues count per page**.
- One card style; one table component; forms two columns max with inline field-level
  validation and save/cancel pinned to the panel bottom.
- Replace the paragraphs of grey helper text under every field with a single
  **"What does this mean?"** popover pattern.
- `Layout.tsx` hardcodes "SGSITS Timetable" — make the product name configurable.
- Fix the N+1 request loops: `SubjectForm.fetchSections` issues one HTTP call **per
  section**, serially, before rendering; `TimetableViewer` does the same for lab batches.

### Copy rules

Never appears on screen: `CP-SAT`, `solver`, `objective value`, `alternative_rank`,
`diversity_from_previous`, `independent validation`, `preflight`, `infeasible`, `demand`,
`constraint profile` (say **"scheduling priorities"**).

| Today | Replace with |
|---|---|
| "Run the CP-SAT solver to generate a conflict-free timetable" | "Create a clash-free timetable from the information you've entered." |
| "Each option is generated by CP-SAT and differs from earlier solutions." | "We'll prepare a few timetables so you can pick the one you like." |
| "#2 · objective 148" | "Option 2 — 12 classes placed differently" |
| "Independent validation: passed" | remove, or a quiet "No clashes" chip |
| "Run #5" | "Timetable — 20 Sep, 9:48 PM" (number secondary) |
| "If sections outside this scope already have a published timetable" | "Other years already have timetables" |
| "Fit into the existing timetable (recommended)" | "Keep the other years' timetables valid (recommended)" |
| "Start fresh" | "Ignore other years — I'll redo them too" |
| "This basket may not fit as configured." | "There aren't enough rooms to run these together." |
| "Availability" (teacher) | "When can they teach?" |
| "Preferred Teaching Times" | "When do they prefer to teach?" |

---

## Phase 4 — Exports and the runs list

### 4.1 PDF must match the reference

**Reference:** `WhatsApp Image 2026-09-20 at 9.48.09 PM.jpeg`.
**What's wrong today:** `Screenshot 2026-09-20 214857.png`.

The root cause of most of it: `GeneratedEntry.session_group` exists *precisely* so exports
can merge a multi-period block into one cell, and **neither exporter reads it.** That's why
a 2-period DBMS lab prints twice in two stacked rows and overflows.

Required structure:

```
                 Department of Computer Engineering
                      Session: JUL-DEC 2026
                       Tentative Time Table
                          B.Tech. IV A
                                                    w.e.f. 20/07/2026
┌───────────────┬─────────┬─────────┬─────────┬─────────┬────────┬──────────┐
│               │ Monday  │ Tuesday │Wednesday│Thursday │ Friday │ Saturday │
├───────────────┼─────────┴─────────┴─────────┴─────────┴────────┴──────────┤
│ 12:00-01:00PM │                        Lunch                              │
├───────────────┼─────────┬─────────┬─────────┬─────────┬────────┬──────────┤
│ 01:00-02:00PM │ E-II    │         │ E-II    │ CO4_PDQA│        │          │
│               │ CO4_RL  │         │ CO4_RL  │ A1      │        │          │
│ 02:00-03:00PM │ MCH     │         │ MCH     │ AS,AsP  │        │          │
│               │Tut.Room │         │Tut.Room │ HW      │        │          │
└───────────────┴─────────┴─────────┴─────────┴─────────┴────────┴──────────┘

Subject Code    Subject Name              Faculty List
CO4__A          Product Dev & Workshop    DAM   Prof. D. A. Mehta
E-II CO4__RL    Reinforcement Learning    UT    Dr. Ojhi Thakur
...                                       ...

                                                 ______________________
                                                 Head, Computer Engg. Dept.
```

Checklist:

- [ ] Header block: department name, `Session:`, "Tentative Time Table", class name,
      right-aligned `w.e.f.` date (from `AcademicTerm` once Phase 1.7 lands)
- [ ] **Vertical merge** of multi-period blocks via `session_group`
- [ ] **Full-width lunch band**, merged only across days that have lunch (Phase 2.5)
- [ ] Cell content as **stacked lines**, not a pipe-joined string:
      subject code / batch / faculty initials / room
- [ ] Parallel batches stacked **inside one cell**, not as separate rows
- [ ] **Subject code → subject name** legend table
- [ ] **Faculty initials → full name** legend table, beside it
- [ ] Signature line, bottom right
- [ ] Column widths that fit A4 landscape without overflow
- [ ] Every configured period rendered, including empty ones

This needs `Subject.code` and `Teacher.initials` — neither exists. Add both, derive
sensible defaults (`CO4_PDQA`, `MCH`), let the admin override.

### 4.2 Excel must match the same structure

Real merged cells (`ws.merge_cells`) for blocks and the lunch band, frozen header, row
heights that fit stacked content, legend tables below the grid, and **one sheet per
section** when exporting a whole year.

### 4.3 Calendar export moves

The `.ics` file is opened in Google Calendar / Outlook. No administrator needs it.

- Remove it from the admin timetable page.
- Surface it on the student/faculty **My Timetable** page as "Add to my calendar", where
  it's genuinely useful.
- Use the real term date range (Phase 1.7) instead of the hardcoded 15 weeks.

### 4.4 Runs list

- **Times are UTC.** `created_at` is `server_default=func.now()` (UTC on SQLite) and
  `completed_at = datetime.utcnow()`, serialised with no timezone marker, so the browser
  reads them as local and shows a time 5h30m behind IST. Store timezone-aware UTC,
  serialise with `Z`, render in `Institution.timezone` (which already defaults to
  `Asia/Kolkata` and is read by nothing).
- **Search matches nothing useful.** It lowercases both sides correctly, but only searches
  `id + change_summary + llm_explanation` — the word "Run" is never in that string, so
  typing "run" returns zero results. Search what's on screen: label, status, department,
  year and section names. Add fuzzy matching on those fields. An embedding model would be
  overkill here.
- **Add delete.** There is no way to remove a timetable run from the UI at all.
- Rename runs to "Timetables" throughout.

### 4.5 Tests

Now write them. Cover, at minimum:
- reset scoping keeps timetable history
- editing a class creates a child run and leaves the parent untouched
- a teacher marked unavailable is never scheduled in that window
- daily/weekly/continuous caps are respected
- a `ConstraintRule` with `priority=hard` changes the result
- export merges a 2-period block into one cell and renders the lunch band

---

## Phase 5 — Build a timetable from a scheme

Its own page, deliberately separate from the rest of Setup. The scheme is a **curriculum**
document; everything else in the app is **this term's operational data**. Separating them
also means OCR can be wrong without endangering anything, because nothing commits until the
admin reviews it.

Flow: **upload or paste → parse → review and correct → commit.**

1. **Input.** Paste the L-T-P table, upload `.xlsx`, or upload a PDF/photo (the reference
   scheme images are scanned and rotated — expect OCR plus LLM extraction to land around
   85–95%).
2. **Parse** into rows: `code, category, subject_name, L, T, P, credits`.
3. **Review** — an editable table, with low-confidence cells highlighted. Nothing is
   written yet.
4. **Commit** — creates `Subject` rows (splitting L/T/P into theory/tutorial/lab siblings
   sharing `linked_group_id`), and optionally the `SectionSubject` rows for a chosen year.

Handle the real cases visible in the reference schemes: `MOEC` and NPTEL rows become
`delivery_mode=MOOC_NPTEL` with 0 contact hours; `INT` rows (0-0-0 in the scheme) prompt
for a contact-hours override; `Elective-N` rows become `ElectiveGroup` baskets.

---

## Open decisions

Ask the owner before implementing these; don't guess.

1. **Room/teacher availability semantics** — "only available then" (current) or "blocked
   then" (what admins mean)? Affects Phase 1.2.
2. **`num_sections`** — keep as a target with progress, or drop it and let the section list
   be the truth? The brief assumes keep.
3. **Prerequisites** — wire up as "not before, same day", or remove the table? The brief
   assumes wire up.
4. **Subject codes and faculty initials** — auto-derive with override, or require manual
   entry? The PDF export needs them either way.

---

## Things deliberately not in this brief

- Multi-department access scoping (§3.1). Real work, needs its own design.
- Drag-and-drop on the timetable grid. The conflict-check API already exists; the
  interaction is a separate piece of work once the grid is rebuilt.
- Moving off SQLite. Fine for now; revisit at real scale.
