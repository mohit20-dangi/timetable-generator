# Timetable Generator: System Prompt for Claude

## Project Overview
**Timetable Generator** is an enterprise-grade scheduling system for universities that automates the complex process of creating conflict-free timetables across multiple departments, years, and branches while respecting dozens of hard and soft constraints.

**Goal**: Build a B2B SaaS product that solves university scheduling problems with production-quality code and industry-standard algorithms.

---

## Problem Domain

### What We're Solving
Universities need automated timetable generation because manual scheduling is:
- **Time-consuming**: Coordinating 1000s of classes, labs, and instructors takes weeks
- **Error-prone**: Manual conflicts are inevitable at scale
- **Inflexible**: Changing one class requires rescheduling cascades

### Constraints to Handle
**Hard Constraints (must not violate):**
1. No instructor teaches two classes simultaneously
2. No room is used by two classes at same time
3. No student batch attends two classes simultaneously
4. Classes fit within allocated room availability windows
5. Lab duration requirements respected (e.g., 3-hour blocks)

**Soft Constraints (optimize for):**
1. Workload distribution across instructors (fairness)
2. Minimize gaps in instructor schedules (efficiency)
3. Cluster related subjects for same batch (pedagogy)
4. Respect instructor preferences/availabilities (satisfaction)
5. Minimize room utilization (cost)
6. Keep schedules within standard hours (8am-5pm)

**Domain-Specific Constraints:**
1. Theory classes typically 1-1.5 hours
2. Labs typically 2-3 hours, fewer per week than theory
3. Prerequisites: Subject X cannot run before Subject Y in curriculum
4. Department room allocation: CSE gets Lab-A only Tue/Thu 10-12, Mon/Wed 2-4
5. Faculty workload: Max 24 hours/week teaching
6. Non-continuous timeslots: Same subject preferably same day/adjacent days

---

## Current State & Goals

### What Exists
- Existing project with average-quality implementation
- Unsure if current models/algorithms are optimal for this use case
- Current scope: Timetable generation ONLY

### What We're Building
**Phase 1 (Current): Timetable Generation**
- Production-grade algorithm for constraint satisfaction
- Admin UI to input institutional requirements
- Visualization of generated schedules
- Ability to tweak/override auto-generated schedules

**Phase 2 (Future): Scheme Generation**
- Generate curriculum schemes
- Track prerequisites and learning outcomes

---

## Architecture & Technology Decisions

### Algorithm Selection (CRITICAL)
When implementing the scheduling engine, evaluate these approaches:

**Option 1: Integer Linear Programming (ILP)**
- Pros: Guarantees optimal solution, handles all constraints mathematically
- Cons: Slow for large instances (100+ classes), needs commercial solver (CPLEX, Gurobi) or open-source (CBC, SCIP)
- Use case: Medium-sized colleges (< 50 classes), offline batch processing acceptable

**Option 2: Constraint Programming (CP)**
- Pros: Declarative (specify constraints), handles all hard constraints well, open-source solvers available (OR-Tools)
- Cons: Medium speed, less optimal on soft constraints
- Use case: Medium-large colleges, good for hard constraints, tunable for soft constraints

**Option 3: Genetic Algorithm (GA) + Local Search**
- Pros: Fast, scalable to 1000+ classes, can handle soft constraints well
- Cons: No guarantee of optimality, needs careful tuning
- Use case: Large colleges, real-time/interactive schedule generation

**Option 4: Greedy Heuristic + Simulated Annealing**
- Pros: Very fast, simple implementation
- Cons: Poor solution quality if not well-tuned
- Use case: Quick scheduling, not suitable for production

**Recommendation for Phase 1**: Start with Constraint Programming (Google OR-Tools). If performance insufficient, switch to GA+Local Search. DO NOT start with Greedy.

### Data Model Requirements
The system must support:
1. **Flexible organizational structure**: Departments → Years → Branches → Batches → Students
2. **Subject modeling**: Duration, type (theory/lab), frequency, prerequisites, faculty
3. **Resource modeling**: Rooms (capacity, amenities), timeslots, instructor availability
4. **Constraint configuration**: Per-institution rules (e.g., no 8am classes, max 2 labs/day)
5. **Audit trail**: Who made what changes, when, and why

### Technology Stack Guidance
**For each major decision:**
- Database: Use what's appropriate for volume/queries (PostgreSQL for most colleges, consider TimescaleDB if tracking schedule history)
- Backend: Python (scikit-optimize, PuLP) or Node.js (depends on team expertise) — prioritize algorithm clarity over language hype
- Frontend: React for interactive schedule builder, make it intuitive (drag-drop timeslots, real-time conflict detection)
- Deployment: Cloud-native (consider AWS/GCP for scalability, but ensure data residency for Indian institutions)

---

## Code Quality Standards

### What We Optimize For (in priority order)
1. **Correctness**: No constraint violations in hard constraints
2. **Maintainability**: Clear algorithm implementation, not clever/cryptic code
3. **Debuggability**: Constraint violation reporting, schedule visualization
4. **Performance**: Completes within reasonable time (< 5 minutes for 100 classes typical)
5. **Configurability**: Easy for institutions to customize without code changes

### What We DON'T optimize for
- Micro-optimizations that hurt readability
- Features for "hypothetical future use cases"
- Premature abstraction

### Code Style
- Use domain language: `timeslot`, `batch`, `workload`, not generic names
- Constraints should be readable as business rules, not mathematical notation
- Comment WHY constraints exist, not WHAT they do
- Logging should help debug constraint violations, not just track execution

---

## When Claude Assists

### Claude Should Focus On
1. **Algorithm research**: "Is this the best approach for this constraint problem?"
2. **Architecture review**: "Is this data model flexible enough for different colleges?"
3. **Code quality**: "Does this constraint implementation match the business rule?"
4. **Testing**: "What edge cases would break the schedule?"
5. **Integration**: "How do we connect the scheduling engine to the UI?"

### Claude Should Challenge
1. Technology choices that aren't justified by the problem
2. Implementations that aren't using the best algorithm for the task
3. Data models that can't scale to different institution sizes
4. Features added for reasons other than actual requirements

### Claude Should NOT
1. Add premature abstractions
2. Write half-finished features
3. Implement multiple algorithms without picking one
4. Over-engineer configuration (keep it simple until needed)

---

## Success Criteria

**For Phase 1 to be complete:**
- ✅ Generates conflict-free schedules for 100+ classes
- ✅ Handles all major constraints (no instructor/room/student conflicts)
- ✅ Completes scheduling in < 5 minutes typical case
- ✅ Admin can input requirements via web UI
- ✅ Schedules are visualizable and downloadable (PDF/Excel)
- ✅ Can handle edge cases (labs, prerequisites, faculty availability)
- ✅ No "magic numbers" — all constraints configurable

**Code Quality Checkpoints:**
- [ ] No unused code or dead branches
- [ ] Core algorithm documented at a high level
- [ ] Constraint violations produce readable error messages
- [ ] Tested on real-world institution data (if available)
- [ ] README explains how to configure for a new college

---

## Questions to Ask When Uncertain

Before implementing anything, answer:
1. Is this a hard or soft constraint?
2. What algorithm handles this constraint pattern best?
3. Will this scale to 500 classes? 5000 students?
4. Can different colleges disable/configure this constraint?
5. What's the simplest way to implement this correctly?

---

## References & Research Areas

When optimizing the algorithm, research:
1. **University Course Timetabling Problem (UCTP)**: Academic papers on constraint satisfaction approaches
2. **Google OR-Tools**: Production-tested constraint programming library
3. **Simulated Annealing**: If GA approach needed for speed
4. **Genetic Algorithms for Scheduling**: See papers on fitness functions and crossover operations
5. **Precedence Constraints in Scheduling**: For prerequisite handling
6. **Multi-Resource Scheduling**: Room + instructor + student simultaneous allocation

### Industry Examples to Study
- How institutions like IIT Bombay, Delhi University handle this
- Commercial products (if any) and their approaches
- Academic research on UCTP (many papers available)
