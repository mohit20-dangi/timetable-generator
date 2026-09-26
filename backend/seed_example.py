"""
Example seed script - shows how to populate the system with a small,
realistic CSE dataset via the real HTTP API (not direct DB writes), so it
exercises the exact same validation path a human using the frontend would.

Usage:
    1. Start the backend (see README.md).
    2. pip install requests   (if not already installed)
    3. python seed_example.py

Edit the data below to match your actual department data before using this
for anything real. This is meant as a working template, not your final data.
"""
import requests

BASE = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@college.edu"
ADMIN_PASSWORD = "ChangeThisPassword123!"

# ---- 1. First-time only: create the one and only bootstrap admin ----
resp = requests.post(f"{BASE}/api/auth/bootstrap-admin", json={
    "email": ADMIN_EMAIL,
    "password": ADMIN_PASSWORD,
    "full_name": "Department Admin",
    "role": "ADMIN",
})
if resp.status_code == 200:
    print("Created admin account.")
else:
    print("Admin bootstrap skipped (probably already exists):", resp.json())

# ---- 2. Log in as admin ----
resp = requests.post(f"{BASE}/api/auth/login", json={
    "email": ADMIN_EMAIL,
    "password": ADMIN_PASSWORD,
})
resp.raise_for_status()
token = resp.json()["access_token"]
H = {"Authorization": f"Bearer {token}"}


def post(path, body):
    r = requests.post(f"{BASE}{path}", headers=H, json=body)
    if r.status_code >= 400:
        print(f"  ! {path} -> {r.status_code}: {r.text}")
    else:
        print(f"  ok {path}")
    return r


print("\nCreating institution and department...")
post("/api/institutions/", {"id": "demo_college", "name": "Demo Institute of Technology", "city": "Bhopal"})
post("/api/departments/", {"id": "cse", "institution_id": "demo_college", "name": "Computer Science & Engineering", "code": "CSE"})

print("\nCreating a bell schedule (Mon-Sat, 8 periods, with a lunch gap left open for the year to mark)...")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
period_times = [
    ("08:00", "08:50"), ("08:50", "09:40"), ("09:50", "10:40"), ("10:40", "11:30"),
    ("12:30", "13:20"), ("13:20", "14:10"), ("14:10", "15:00"), ("15:00", "15:50"),
]
for day in DAYS:
    for i, (start, end) in enumerate(period_times, start=1):
        post("/api/constraints/time-slots", {
            "id": f"{day}_{i}", "day": day, "period_index": i,
            "start_time": start, "end_time": end,
        })

print("\nCreating academic year (III Year CSE) with lunch 11:30-12:30 every weekday...")
post("/api/years/", {
    "id": "cse_y3", "name": "III Year", "department_id": "cse", "num_sections": 1,
    "lunch_windows": {day: ["11:30", "12:30"] for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]},
})

print("\nCreating sections...")
post("/api/sections/", {"id": "cse3a", "year_id": "cse_y3", "name": "CSE 3rd Year - A", "strength": 60})

print("\nCreating rooms...")
post("/api/rooms/", {"id": "lt1", "name": "Lecture Theatre 1", "type": "lecture", "capacity": 70, "department_id": "cse"})
post("/api/rooms/", {"id": "lab1", "name": "Programming Lab 1", "type": "lab", "capacity": 30, "department_id": "cse"})
post("/api/rooms/", {"id": "lab2", "name": "Programming Lab 2", "type": "lab", "capacity": 30, "department_id": "cse"})

print("\nCreating subjects (from the real III-Year Sem-A scheme: DS, DSA, Digital Comm, DBMS-style example)...")
post("/api/subjects/", {
    "id": "ds", "name": "Data Structures", "type": "theory", "department_id": "cse",
    "category": "PCC", "delivery_mode": "IN_PERSON", "scheme_hours_per_week": 3, "weekly_hours": 3,
})
post("/api/subjects/", {
    "id": "ds_tut", "name": "Data Structures Tutorial", "type": "tutorial", "department_id": "cse",
    "category": "PCC", "delivery_mode": "IN_PERSON", "scheme_hours_per_week": 1, "weekly_hours": 1,
    "linked_group_id": "ds_group",
})
post("/api/subjects/", {
    "id": "os", "name": "Operating Systems", "type": "theory", "department_id": "cse",
    "category": "PCC", "delivery_mode": "IN_PERSON", "scheme_hours_per_week": 3, "weekly_hours": 3,
    "max_per_day": 1,
})
post("/api/subjects/", {
    "id": "dbms_lab", "name": "DBMS Lab", "type": "lab", "department_id": "cse",
    "category": "PCC-LC", "delivery_mode": "IN_PERSON", "scheme_hours_per_week": 2, "weekly_hours": 2,
    "periods_per_session": 2, "back_to_back": True, "requires_room_type": "lab",
})
post("/api/subjects/", {
    "id": "envsci", "name": "Environmental Science", "type": "theory", "department_id": "cse",
    "category": "MC", "delivery_mode": "IN_PERSON", "scheme_hours_per_week": 1, "weekly_hours": 1,
})
post("/api/subjects/", {
    "id": "nptel_ai", "name": "NPTEL: Intro to AI", "type": "theory", "department_id": "cse",
    "category": "MOEC", "delivery_mode": "MOOC_NPTEL", "scheme_hours_per_week": 3, "weekly_hours": 0,
})
post("/api/subjects/", {
    "id": "internship", "name": "Summer Internship", "type": "theory", "department_id": "cse",
    "category": "INT", "delivery_mode": "INDUSTRY", "scheme_hours_per_week": 20, "weekly_hours": 0,
})

print("\nCreating teachers...")
post("/api/teachers/", {"id": "t_sharma", "name": "Prof. Sharma", "department_id": "cse", "max_weekly_hours": 24})
post("/api/teachers/", {"id": "t_verma", "name": "Prof. Verma", "department_id": "cse", "max_weekly_hours": 24})

print("\nMapping teachers to subjects...")
post("/api/teachers/t_sharma/subjects", {"teacher_id": "t_sharma", "subject_id": "ds"})
post("/api/teachers/t_sharma/subjects", {"teacher_id": "t_sharma", "subject_id": "ds_tut"})
post("/api/teachers/t_sharma/subjects", {"teacher_id": "t_sharma", "subject_id": "envsci"})
post("/api/teachers/t_verma/subjects", {"teacher_id": "t_verma", "subject_id": "os"})
post("/api/teachers/t_verma/subjects", {"teacher_id": "t_verma", "subject_id": "dbms_lab"})
# dbms_lab needs a SECOND eligible teacher: two lab batches run
# simultaneously in two different rooms, so one teacher can't cover both
# at once. Any lab subject with 2+ batches needs at least as many eligible
# teachers as it has simultaneous batches, or generation correctly reports
# infeasible (with a specific, named reason - see app/solver/diagnostics.py).
post("/api/teachers/t_sharma/subjects", {"teacher_id": "t_sharma", "subject_id": "dbms_lab"})

print("\nMapping section to subjects (NPTEL and internship deliberately included - they should")
print("NOT consume any timetable slot, since delivery_mode is MOOC_NPTEL / INDUSTRY)...")
for subject_id in ["ds", "ds_tut", "os", "dbms_lab", "envsci", "nptel_ai", "internship"]:
    post("/api/constraints/section-subjects", {"section_id": "cse3a", "subject_id": subject_id})

print("\nCreating lab batches (required for any subject of type 'lab')...")
post("/api/constraints/lab-batches", {"id": "cse3a_b1", "section_id": "cse3a", "batch_name": "A1", "strength": 30})
post("/api/constraints/lab-batches", {"id": "cse3a_b2", "section_id": "cse3a", "batch_name": "A2", "strength": 30})

print("\nCreating a constraint profile (balanced preset, expressed as plain-language levels)...")
post("/api/constraints/profiles", {
    "id": "balanced", "name": "Balanced", "department_id": "cse",
    "soft_constraint_weights": {
        "minimize_student_gaps": "very_important",
        "balance_load_across_days": "very_important",
        "avoid_edge_periods": "nice_to_have",
        "teacher_preferred_slots": "nice_to_have",
        "fair_teacher_workload": "nice_to_have",
        "parallel_lab_batches": "very_important",
    },
})

print("\nRegistering a faculty login and a student login...")
post("/api/auth/register", {
    "email": "sharma@college.edu", "password": "ChangeThisPassword123!", "full_name": "Prof. Sharma",
    "role": "FACULTY", "teacher_id": "t_sharma",
})
post("/api/auth/register", {
    "email": "student1@college.edu", "password": "ChangeThisPassword123!", "full_name": "A Student",
    "role": "STUDENT", "section_id": "cse3a",
})

print("\nTriggering timetable generation (runs in the background)...")
r = post("/api/timetable/generate", {"department_id": "cse", "constraint_profile_id": "balanced", "num_alternatives": 2})
if r.status_code == 200:
    run_id = r.json()["id"]
    print(f"\nGeneration started as run #{run_id}. Polling for completion...")
    import time as _time
    status = None
    for _ in range(60):
        rr = requests.get(f"{BASE}/api/timetable/runs/{run_id}", headers=H).json()
        status = rr["status"]
        if status in ("completed", "failed"):
            break
        _time.sleep(1)
    print(f"Final status: {status}")

    if status == "completed":
        validation = requests.get(f"{BASE}/api/timetable/runs/{run_id}/validate", headers=H).json()
        print(f"Independent validation: {'PASSED' if validation['valid'] else 'FAILED'}")
        if not validation["valid"]:
            for issue in validation["issues"]:
                print(f"  ! {issue['type']}: {issue['message']}")

        pub = post(f"/api/timetable/runs/{run_id}/publish", {})
        if pub.status_code == 200:
            print(f"Run #{run_id} published - it's now the live timetable.")
            print("Log in as sharma@college.edu / student1@college.edu (password: ChangeThisPassword123!)")
            print("and GET /api/timetable/me to see each person's own scoped schedule.")
    else:
        rr = requests.get(f"{BASE}/api/timetable/runs/{run_id}", headers=H).json()
        print(f"Generation did not complete. Explanation:\n{rr.get('llm_explanation')}")

print("\nDone. See README.md for the full walkthrough and API reference.")
