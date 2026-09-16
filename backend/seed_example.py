"""
Example seed script — shows how to populate the system with a small,
realistic CSE dataset via the real HTTP API (not direct DB writes), so it
exercises the exact same validation path a human using the frontend would.

Usage:
    1. Start the backend (see README.md).
    2. pip install requests --break-system-packages   (if not already installed)
    3. python seed_example.py

Edit the data below to match your actual department data before using this
for anything real. This is meant as a working template, not your final data.
"""
import requests

BASE = "http://127.0.0.1:8000"

# ---- 1. First-time only: create the one and only bootstrap admin ----
# This call only works once (while the users table is empty). If you've
# already bootstrapped an admin, skip this block and just log in below.
resp = requests.post(f"{BASE}/api/auth/bootstrap-admin", json={
    "email": "admin@college.edu",
    "password": "change-this-password",
    "full_name": "Department Admin",
    "role": "ADMIN",
})
if resp.status_code == 200:
    print("Created admin account.")
else:
    print("Admin bootstrap skipped (probably already exists):", resp.json())

# ---- 2. Log in as admin ----
resp = requests.post(f"{BASE}/api/auth/login", json={
    "email": "admin@college.edu",
    "password": "TestPassword123!",
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

print("\nCreating academic year...")
post("/api/years/", {"id": "y2026", "name": "2026-27", "num_sections": 1,
                      "lunch_start": "13:00:00", "lunch_end": "14:00:00"})

print("\nCreating sections...")
post("/api/sections/", {"id": "cse3a", "year_id": "y2026", "name": "CSE 3rd Year - A", "strength": 60})

print("\nCreating rooms...")
post("/api/rooms/", {"id": "lt1", "name": "Lecture Theatre 1", "type": "lecture", "capacity": 70})
post("/api/rooms/", {"id": "lab1", "name": "Programming Lab 1", "type": "lab", "capacity": 30})
post("/api/rooms/", {"id": "lab2", "name": "Programming Lab 2", "type": "lab", "capacity": 30})

print("\nCreating subjects...")
post("/api/subjects/", {"id": "dbms", "name": "Database Management Systems", "type": "theory", "weekly_hours": 4})
post("/api/subjects/", {"id": "os", "name": "Operating Systems", "type": "theory", "weekly_hours": 4})
post("/api/subjects/", {
    "id": "dbms_lab", "name": "DBMS Lab", "type": "lab", "weekly_hours": 2,
    "needs_continuous_block": True, "block_size": 2, "requires_room_type": "lab"
})

print("\nCreating teachers...")
post("/api/teachers/", {"id": "t_sharma", "name": "Prof. Sharma", "department": "CSE"})
post("/api/teachers/", {"id": "t_verma", "name": "Prof. Verma", "department": "CSE"})

print("\nMapping teachers to subjects...")
post("/api/teachers/t_sharma/subjects", {"teacher_id": "t_sharma", "subject_id": "dbms"})
post("/api/teachers/t_sharma/subjects", {"teacher_id": "t_sharma", "subject_id": "dbms_lab"})
post("/api/teachers/t_verma/subjects", {"teacher_id": "t_verma", "subject_id": "os"})
# dbms_lab needs a SECOND eligible teacher: the two lab batches run
# simultaneously in two different rooms, so one teacher can't cover both
# at once. Any lab subject with 2+ batches needs at least as many eligible
# teachers as it has simultaneous batches, or generation will correctly
# report infeasible.
post("/api/teachers/t_verma/subjects", {"teacher_id": "t_verma", "subject_id": "dbms_lab"})

print("\nMapping section to subjects...")
post("/api/constraints/section-subjects", {"section_id": "cse3a", "subject_id": "dbms"})
post("/api/constraints/section-subjects", {"section_id": "cse3a", "subject_id": "os"})
post("/api/constraints/section-subjects", {"section_id": "cse3a", "subject_id": "dbms_lab"})
# IMPORTANT: lab subjects need BOTH of these:
#  1. A section-subjects mapping (as above) - declares that this section
#     takes this subject at all.
#  2. LabBatch row(s) below - splits the section into groups for the lab.
# Skipping either one means the lab silently never gets scheduled.

print("\nCreating lab batches (required for any subject of type 'lab')...")
post("/api/constraints/lab-batches", {"id": "cse3a_b1", "section_id": "cse3a", "batch_name": "A1", "strength": 30})
post("/api/constraints/lab-batches", {"id": "cse3a_b2", "section_id": "cse3a", "batch_name": "A2", "strength": 30})

print("\nRegistering a faculty login and a student login...")
post("/api/auth/register", {
    "email": "sharma@college.edu", "password": "change-this-password", "full_name": "Prof. Sharma",
    "role": "FACULTY", "teacher_id": "t_sharma"
})
post("/api/auth/register", {
    "email": "student1@college.edu", "password": "change-this-password", "full_name": "A Student",
    "role": "STUDENT", "section_id": "cse3a"
})

print("\nTriggering timetable generation (runs in the background)...")
r = post("/api/timetable/generate", {})
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
        pub = post(f"/api/timetable/runs/{run_id}/publish", {})
        if pub.status_code == 200:
            print(f"Run #{run_id} published - it's now the live timetable.")
            print(f"Log in as sharma@college.edu / student1@college.edu (password: change-this-password)")
            print(f"and GET /api/timetable/me to see each person's own scoped schedule -")
            print(f"the exact same thing the frontend's 'My Timetable' page shows.")
    else:
        print(f"Generation did not complete (status={status}). Check GET /api/timetable/runs/{run_id}")
        print(f"and the 'llm_explanation' field (if an AI key is configured) for why.")

print("\nDone. See README.md for the full walkthrough and API reference.")
