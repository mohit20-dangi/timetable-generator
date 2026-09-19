from collections import defaultdict
from ortools.sat.python import cp_model
from typing import Dict, List, Any, Optional, Tuple
from datetime import time

CANONICAL_DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class TimetableSolver:
    def __init__(self, constraints: Dict[str, Any]):
        self.constraints = constraints
        self.model = cp_model.CpModel()
        self.variables = {}
        self.solver = cp_model.CpSolver()
        self.solver.parameters.max_time_in_seconds = 300
        self.solver.parameters.num_search_workers = 8

    def solve(self) -> Tuple[bool, Dict[str, Any], str]:
        """Solve the timetable problem. Returns (success, solution_dict, status_message)."""
        self._create_variables()
        self._add_hard_constraints()
        self._add_soft_constraints()

        status = self.solver.Solve(self.model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solution = self._extract_solution()
            return True, solution, "Feasible solution found"
        else:
            conflict_info = self._get_conflict_info(status)
            return False, {}, conflict_info

    # ------------------------------------------------------------------
    # Variable / time-grid setup
    # ------------------------------------------------------------------

    def _build_time_grid(self):
        """Build self.days/self.time_slots either from configured TimeSlot rows
        (each slot keeps its own start/end so lunch/availability checks are exact)
        or from the historical default of 6 days x 8 periods, 9:00 start, 50-min periods.
        """
        configured = self.constraints.get("time_slots", [])
        if configured:
            self.days = sorted(
                {s["day"] for s in configured},
                key=lambda d: CANONICAL_DAY_ORDER.index(d) if d in CANONICAL_DAY_ORDER else 99,
            )
            self.time_slots = []
            for s in configured:
                start = s["start_time"]
                end = s["end_time"]
                self.time_slots.append({
                    "day": s["day"],
                    "period": s["period_index"],
                    "slot_id": f"{s['day']}_{s['period_index']}",
                    "start": time.fromisoformat(start) if isinstance(start, str) else start,
                    "end": time.fromisoformat(end) if isinstance(end, str) else end,
                })
            self.periods_per_day = max((s["period"] for s in self.time_slots), default=8)
        else:
            self.days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            self.periods_per_day = 8
            self.time_slots = []
            for day in self.days:
                for period in range(1, self.periods_per_day + 1):
                    self.time_slots.append({
                        "day": day,
                        "period": period,
                        "slot_id": f"{day}_{period}",
                        "start": self._default_period_to_time(period),
                        "end": self._default_period_to_time(period + 1),
                    })

    def _create_variables(self):
        """Create decision variables for the CP-SAT model."""
        subjects = self.constraints.get("subjects", [])
        teachers = self.constraints.get("teachers", [])
        rooms = self.constraints.get("rooms", [])

        self.subject_map = {s["id"]: s for s in subjects}
        self.teacher_map = {t["id"]: t for t in teachers}
        self.room_map = {r["id"]: r for r in rooms}

        # Use the real sections from the database (not synthesized IDs) so that
        # section_subjects/section_id lookups elsewhere actually match up.
        self.sections = self.constraints.get("sections", [])
        for section in self.sections:
            section.setdefault("strength", 60)

        self._build_time_grid()

        # Create assignment variables: assign[section_id][subject_id][teacher_id][room_id][slot_id] = 0/1
        for section in self.sections:
            section_id = section["id"]
            self.variables[section_id] = {}

            section_subjects = self.constraints.get("section_subjects", {}).get(section_id, [])

            for subject_id in section_subjects:
                subject = self.subject_map.get(subject_id)
                if not subject:
                    continue

                self.variables[section_id][subject_id] = {}

                eligible_teachers = [
                    t["id"] for t in teachers
                    if subject_id in t.get("subjects", [])
                ]

                eligible_rooms = [
                    r["id"] for r in rooms
                    if (subject.get("requires_room_type") is None or
                        r["type"] == subject.get("requires_room_type")) and
                    r["capacity"] >= section["strength"] and
                    all(eq in r.get("equipment", []) for eq in subject.get("requires_equipment", []))
                ]

                if not eligible_teachers or not eligible_rooms:
                    continue

                for teacher_id in eligible_teachers:
                    self.variables[section_id][subject_id][teacher_id] = {}
                    for room_id in eligible_rooms:
                        self.variables[section_id][subject_id][teacher_id][room_id] = {}
                        for slot in self.time_slots:
                            var_name = f"assign_{section_id}_{subject_id}_{teacher_id}_{room_id}_{slot['slot_id']}"
                            self.variables[section_id][subject_id][teacher_id][room_id][slot["slot_id"]] = \
                                self.model.NewBoolVar(var_name)

        # Handle lab batches
        self.lab_batches = self.constraints.get("lab_batches", [])
        for batch in self.lab_batches:
            batch_id = batch["id"]
            self.variables[batch_id] = {}

            section_id = batch["section_id"]
            section_subjects = self.constraints.get("section_subjects", {}).get(section_id, [])

            for subject_id in section_subjects:
                subject = self.subject_map.get(subject_id)
                if not subject or subject["type"] != "lab":
                    continue

                self.variables[batch_id][subject_id] = {}

                eligible_teachers = [
                    t["id"] for t in teachers
                    if subject_id in t.get("subjects", [])
                ]

                eligible_rooms = [
                    r["id"] for r in rooms
                    if r["type"] == "lab" and
                    r["capacity"] >= batch["strength"] and
                    all(eq in r.get("equipment", []) for eq in subject.get("requires_equipment", []))
                ]

                if not eligible_teachers or not eligible_rooms:
                    continue

                for teacher_id in eligible_teachers:
                    self.variables[batch_id][subject_id][teacher_id] = {}
                    for room_id in eligible_rooms:
                        self.variables[batch_id][subject_id][teacher_id][room_id] = {}
                        for slot in self.time_slots:
                            var_name = f"assign_{batch_id}_{subject_id}_{teacher_id}_{room_id}_{slot['slot_id']}"
                            self.variables[batch_id][subject_id][teacher_id][room_id][slot["slot_id"]] = \
                                self.model.NewBoolVar(var_name)

    def _all_slot_vars_for(self, entity_id: str, subject_id: str) -> List[Tuple[str, int, Any]]:
        """All (day, period, var) triples for a given entity+subject, across every
        eligible teacher/room combo. Used by the prerequisite ordering constraint."""
        result = []
        teachers = self.variables.get(entity_id, {}).get(subject_id, {})
        for teacher_id, rooms in teachers.items():
            for room_id, slot_vars in rooms.items():
                for slot in self.time_slots:
                    var = slot_vars.get(slot["slot_id"])
                    if var is not None:
                        result.append((slot["day"], slot["period"], var))
        return result

    # ------------------------------------------------------------------
    # Hard constraints
    # ------------------------------------------------------------------

    def _add_hard_constraints(self):
        """Add all hard constraints to the model."""
        self._no_section_double_booking()
        self._no_teacher_double_booking()
        self._no_room_double_booking()
        self._weekly_hours_constraint()
        self._lunch_break_constraint()
        self._teacher_availability_constraint()
        self._room_availability_constraint()
        self._continuous_block_constraint()
        self._prerequisite_constraint()
        self._lab_batch_simultaneous_constraint()

    def _no_section_double_booking(self):
        """A section cannot have two classes at the same time."""
        for section in self.sections:
            section_id = section["id"]
            if section_id not in self.variables:
                continue
            for slot in self.time_slots:
                slot_vars = []
                for subject_id, teachers in self.variables[section_id].items():
                    for teacher_id, rooms in teachers.items():
                        for room_id, slot_vars_dict in rooms.items():
                            if slot["slot_id"] in slot_vars_dict:
                                slot_vars.append(slot_vars_dict[slot["slot_id"]])
                if slot_vars:
                    self.model.Add(sum(slot_vars) <= 1)

    def _no_teacher_double_booking(self):
        """A teacher cannot teach two classes at the same time."""
        teacher_slots = {}
        for entity_id, subjects in self.variables.items():
            for subject_id, teachers in subjects.items():
                for teacher_id, rooms in teachers.items():
                    if teacher_id not in teacher_slots:
                        teacher_slots[teacher_id] = {}
                    for room_id, slot_vars in rooms.items():
                        for slot_id, var in slot_vars.items():
                            if slot_id not in teacher_slots[teacher_id]:
                                teacher_slots[teacher_id][slot_id] = []
                            teacher_slots[teacher_id][slot_id].append(var)

        for teacher_id, slots in teacher_slots.items():
            for slot_id, vars_list in slots.items():
                if len(vars_list) > 1:
                    self.model.Add(sum(vars_list) <= 1)

    def _no_room_double_booking(self):
        """A room cannot host two classes at the same time."""
        room_slots = {}
        for entity_id, subjects in self.variables.items():
            for subject_id, teachers in subjects.items():
                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        if room_id not in room_slots:
                            room_slots[room_id] = {}
                        for slot_id, var in slot_vars.items():
                            if slot_id not in room_slots[room_id]:
                                room_slots[room_id][slot_id] = []
                            room_slots[room_id][slot_id].append(var)

        for room_id, slots in room_slots.items():
            for slot_id, vars_list in slots.items():
                if len(vars_list) > 1:
                    self.model.Add(sum(vars_list) <= 1)

    def _weekly_hours_constraint(self):
        """Each subject must be scheduled for exactly its weekly_hours."""
        for section in self.sections:
            section_id = section["id"]
            if section_id not in self.variables:
                continue
            for subject_id, teachers in self.variables[section_id].items():
                subject = self.subject_map.get(subject_id)
                if not subject:
                    continue
                weekly_hours = subject.get("weekly_hours", 0)
                if weekly_hours == 0:
                    continue

                all_vars = []
                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        all_vars.extend(slot_vars.values())

                if all_vars:
                    self.model.Add(sum(all_vars) == weekly_hours)

        for batch in self.lab_batches:
            batch_id = batch["id"]
            if batch_id not in self.variables:
                continue
            for subject_id, teachers in self.variables[batch_id].items():
                subject = self.subject_map.get(subject_id)
                if not subject:
                    continue
                weekly_hours = subject.get("weekly_hours", 0)
                if weekly_hours == 0:
                    continue

                all_vars = []
                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        all_vars.extend(slot_vars.values())

                if all_vars:
                    self.model.Add(sum(all_vars) == weekly_hours)

    def _lunch_break_constraint(self):
        """No classes during lunch break for each section's academic year."""
        for section in self.sections:
            section_id = section["id"]
            lunch_start_str = section.get("lunch_start")
            lunch_end_str = section.get("lunch_end")
            if not lunch_start_str or not lunch_end_str or section_id not in self.variables:
                continue

            lunch_start = time.fromisoformat(lunch_start_str) if isinstance(lunch_start_str, str) else lunch_start_str
            lunch_end = time.fromisoformat(lunch_end_str) if isinstance(lunch_end_str, str) else lunch_end_str

            lunch_periods = [
                slot["slot_id"] for slot in self.time_slots
                if self._time_overlaps(slot["start"], slot["end"], lunch_start, lunch_end)
            ]

            for subject_id, teachers in self.variables[section_id].items():
                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        for slot_id in lunch_periods:
                            if slot_id in slot_vars:
                                self.model.Add(slot_vars[slot_id] == 0)

    def _availability_slot_ids(self, availability: List[dict]) -> set:
        available_slots = set()
        for avail in availability:
            day = avail["day"]
            start_str = avail["start"]
            end_str = avail["end"]
            start = time.fromisoformat(start_str) if isinstance(start_str, str) else start_str
            end = time.fromisoformat(end_str) if isinstance(end_str, str) else end_str
            for slot in self.time_slots:
                if slot["day"] == day and self._time_in_range(slot["start"], slot["end"], start, end):
                    available_slots.add(slot["slot_id"])
        return available_slots

    def _teacher_availability_constraint(self):
        """Teachers can only teach during their available slots."""
        for teacher in self.constraints.get("teachers", []):
            teacher_id = teacher["id"]
            availability = teacher.get("availability", [])
            if not availability:
                continue

            available_slots = self._availability_slot_ids(availability)

            for entity_id, subjects in self.variables.items():
                for subject_id, teachers in subjects.items():
                    if teacher_id in teachers:
                        for room_id, slot_vars in teachers[teacher_id].items():
                            for slot_id, var in slot_vars.items():
                                if slot_id not in available_slots:
                                    self.model.Add(var == 0)

    def _room_availability_constraint(self):
        """Rooms can only be used during their available slots."""
        for room in self.constraints.get("rooms", []):
            room_id = room["id"]
            availability = room.get("availability", [])
            if not availability:
                continue

            available_slots = self._availability_slot_ids(availability)

            for entity_id, subjects in self.variables.items():
                for subject_id, teachers in subjects.items():
                    for teacher_id, rooms in teachers.items():
                        if room_id in rooms:
                            for slot_id, var in rooms[room_id].items():
                                if slot_id not in available_slots:
                                    self.model.Add(var == 0)

    def _continuous_block_constraint(self):
        """Subjects needing continuous blocks must get back-to-back periods.

        For each day, a given (section, subject, teacher, room) combo is either
        completely unused that day, or used for exactly one contiguous run of
        `block_size` periods - never scattered single periods. Across the week,
        exactly `num_blocks` days must be used this way.
        """
        for section in self.sections:
            section_id = section["id"]
            if section_id not in self.variables:
                continue
            for subject_id, teachers in self.variables[section_id].items():
                subject = self.subject_map.get(subject_id)
                if not subject or not subject.get("needs_continuous_block", False):
                    continue

                block_size = max(subject.get("block_size", 2), 1)
                weekly_hours = subject.get("weekly_hours", 0)
                num_blocks = weekly_hours // block_size

                if num_blocks == 0:
                    continue

                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        has_block_today_vars = []

                        for day in self.days:
                            day_slots = sorted(
                                [s for s in self.time_slots if s["day"] == day],
                                key=lambda x: x["period"],
                            )
                            day_slot_vars = [slot_vars[s["slot_id"]] for s in day_slots if s["slot_id"] in slot_vars]
                            if not day_slot_vars:
                                continue

                            block_vars_today = []
                            for i in range(len(day_slots) - block_size + 1):
                                block_slots = day_slots[i:i + block_size]
                                block_slot_vars = [slot_vars.get(s["slot_id"]) for s in block_slots]
                                if any(v is None for v in block_slot_vars):
                                    continue
                                block_var = self.model.NewBoolVar(
                                    f"block_{section_id}_{subject_id}_{teacher_id}_{room_id}_{day}_{i}"
                                )
                                self.model.Add(sum(block_slot_vars) == block_size).OnlyEnforceIf(block_var)
                                self.model.Add(sum(block_slot_vars) < block_size).OnlyEnforceIf(block_var.Not())
                                block_vars_today.append(block_var)

                            has_block_today = self.model.NewBoolVar(
                                f"hasblock_{section_id}_{subject_id}_{teacher_id}_{room_id}_{day}"
                            )
                            # Used today implies exactly one contiguous block (no scattered periods).
                            self.model.Add(sum(day_slot_vars) == block_size * has_block_today)
                            if block_vars_today:
                                self.model.Add(sum(block_vars_today) == has_block_today)
                            else:
                                self.model.Add(has_block_today == 0)
                            has_block_today_vars.append(has_block_today)

                        if has_block_today_vars:
                            self.model.Add(sum(has_block_today_vars) == num_blocks)

    def _prerequisite_constraint(self):
        """Every scheduled occurrence of a prerequisite subject must come
        strictly before every scheduled occurrence of the subject that
        requires it, for the same section."""
        prerequisites = self.constraints.get("prerequisites", [])
        if not prerequisites:
            return

        day_index = {day: i for i, day in enumerate(self.days)}

        for section in self.sections:
            section_id = section["id"]
            if section_id not in self.variables:
                continue
            for prereq in prerequisites:
                dependent_id = prereq["subject_id"]
                required_id = prereq["requires_subject_id"]
                if dependent_id not in self.variables[section_id] or required_id not in self.variables[section_id]:
                    continue

                required_slots = self._all_slot_vars_for(section_id, required_id)
                dependent_slots = self._all_slot_vars_for(section_id, dependent_id)

                for req_day, req_period, req_var in required_slots:
                    req_key = (day_index.get(req_day, 0), req_period)
                    for dep_day, dep_period, dep_var in dependent_slots:
                        dep_key = (day_index.get(dep_day, 0), dep_period)
                        if dep_key <= req_key:
                            # Dependent subject can't be scheduled at/before the prerequisite.
                            self.model.AddBoolOr([req_var.Not(), dep_var.Not()])

    def _lab_batch_simultaneous_constraint(self):
        """Lab batches belonging to the same section run their lab subjects in
        parallel: every batch must be in class at exactly the same slots as its
        sibling batches (different rooms/teachers is fine, different time is not).
        """
        if not self.lab_batches or len(self.lab_batches) < 2:
            return

        groups: Dict[str, List[str]] = defaultdict(list)
        for batch in self.lab_batches:
            groups[batch["section_id"]].append(batch["id"])

        for section_id, batch_ids in groups.items():
            if len(batch_ids) < 2:
                continue

            section_subjects = self.constraints.get("section_subjects", {}).get(section_id, [])
            for subject_id in section_subjects:
                subject = self.subject_map.get(subject_id)
                if not subject or subject.get("type") != "lab":
                    continue

                has_class: Dict[Tuple[str, str], Any] = {}
                for batch_id in batch_ids:
                    teachers = self.variables.get(batch_id, {}).get(subject_id, {})
                    if not teachers:
                        continue
                    for slot in self.time_slots:
                        slot_id = slot["slot_id"]
                        vars_for_slot = [
                            slot_vars[slot_id]
                            for rooms in teachers.values()
                            for slot_vars in rooms.values()
                            if slot_id in slot_vars
                        ]
                        if not vars_for_slot:
                            continue
                        indicator = self.model.NewBoolVar(f"labsim_{batch_id}_{subject_id}_{slot_id}")
                        self.model.AddMaxEquality(indicator, vars_for_slot)
                        has_class[(batch_id, slot_id)] = indicator

                reference_batch = batch_ids[0]
                for slot in self.time_slots:
                    slot_id = slot["slot_id"]
                    ref_var = has_class.get((reference_batch, slot_id))
                    if ref_var is None:
                        continue
                    for other_batch in batch_ids[1:]:
                        other_var = has_class.get((other_batch, slot_id))
                        if other_var is not None:
                            self.model.Add(ref_var == other_var)

    # ------------------------------------------------------------------
    # Soft constraints
    # ------------------------------------------------------------------

    def _add_soft_constraints(self):
        """Add soft constraints as objective function terms."""
        weights = self.constraints.get("soft_constraint_weights", {})

        objective_terms = []

        if weights.get("minimize_gaps", 0) > 0:
            gap_penalty = self._create_gap_penalty("teacher")
            objective_terms.append(gap_penalty * weights["minimize_gaps"])

        if weights.get("minimize_student_gaps", 0) > 0:
            gap_penalty = self._create_gap_penalty("section")
            objective_terms.append(gap_penalty * weights["minimize_student_gaps"])

        if weights.get("teacher_preference", 0) > 0:
            pref_penalty = self._create_teacher_preference_penalty()
            objective_terms.append(pref_penalty * weights["teacher_preference"])

        # Empty day preference: either a list of preferred-empty days (weight
        # defaults to 1) or a {"days": [...], "weight": N} style value - the
        # LLM's own documented schema emits a bare list, so that must not crash.
        empty_day_pref_raw = weights.get("empty_day_preference")
        if empty_day_pref_raw:
            if isinstance(empty_day_pref_raw, list):
                empty_day_days = empty_day_pref_raw
                empty_day_weight = 1
            elif isinstance(empty_day_pref_raw, dict):
                empty_day_days = empty_day_pref_raw.get("days", [])
                empty_day_weight = empty_day_pref_raw.get("weight", 1)
            else:
                empty_day_days = []
                empty_day_weight = empty_day_pref_raw if isinstance(empty_day_pref_raw, (int, float)) else 0
            if empty_day_days and empty_day_weight > 0:
                empty_day_penalty = self._create_empty_day_penalty(empty_day_days)
                objective_terms.append(empty_day_penalty * empty_day_weight)

        if weights.get("minimize_travel", 0) > 0:
            travel_penalty = self._create_travel_distance_penalty()
            objective_terms.append(travel_penalty * weights["minimize_travel"])

        if weights.get("class_changes_via_breaks", 0) > 0:
            break_penalty = self._create_class_changes_via_breaks_penalty()
            objective_terms.append(break_penalty * weights["class_changes_via_breaks"])

        if objective_terms:
            self.model.Minimize(sum(objective_terms))

    def _create_gap_penalty(self, entity_type: str) -> cp_model.LinearExpr:
        """Create penalty variables for gaps in schedule."""
        penalty_vars = []

        if entity_type == "teacher":
            entities = {t["id"]: t for t in self.constraints.get("teachers", [])}
        else:
            entities = {s["id"]: s for s in self.sections}

        for entity_id in entities:
            for day in self.days:
                day_slots = sorted([s for s in self.time_slots if s["day"] == day], key=lambda x: x["period"])

                entity_vars = {}
                for slot in day_slots:
                    slot_id = slot["slot_id"]
                    vars_for_slot = []

                    for sec_id, subjects in self.variables.items():
                        for subject_id, teachers in subjects.items():
                            for teacher_id, rooms in teachers.items():
                                for room_id, slot_vars in rooms.items():
                                    if entity_type == "teacher" and teacher_id == entity_id:
                                        if slot_id in slot_vars:
                                            vars_for_slot.append(slot_vars[slot_id])
                                    elif entity_type == "section" and sec_id == entity_id:
                                        if slot_id in slot_vars:
                                            vars_for_slot.append(slot_vars[slot_id])

                    if vars_for_slot:
                        has_class = self.model.NewBoolVar(f"has_class_{entity_id}_{day}_{slot['period']}")
                        self.model.AddMaxEquality(has_class, vars_for_slot)
                        entity_vars[slot["period"]] = has_class

                if len(entity_vars) >= 3:
                    for i in range(len(day_slots) - 2):
                        p1, p2, p3 = day_slots[i]["period"], day_slots[i + 1]["period"], day_slots[i + 2]["period"]
                        if p1 in entity_vars and p2 in entity_vars and p3 in entity_vars:
                            gap = self.model.NewBoolVar(f"gap_{entity_id}_{day}_{p1}_{p3}")
                            self.model.AddBoolAnd([entity_vars[p1], entity_vars[p3], entity_vars[p2].Not()]).OnlyEnforceIf(gap)
                            self.model.AddBoolOr([entity_vars[p1].Not(), entity_vars[p3].Not(), entity_vars[p2]]).OnlyEnforceIf(gap.Not())
                            penalty_vars.append(gap)

        return sum(penalty_vars) if penalty_vars else 0

    def _create_teacher_preference_penalty(self) -> cp_model.LinearExpr:
        """Penalize assignments outside teacher preferred slots."""
        penalty_vars = []

        for teacher in self.constraints.get("teachers", []):
            teacher_id = teacher["id"]
            preferred = teacher.get("preferred_slots", [])
            if not preferred:
                continue

            preferred_set = set()
            for pref in preferred:
                day = pref["day"]
                for slot_obj in pref.get("slots", []):
                    start_str = slot_obj["start"]
                    end_str = slot_obj["end"]
                    start = time.fromisoformat(start_str) if isinstance(start_str, str) else start_str
                    end = time.fromisoformat(end_str) if isinstance(end_str, str) else end_str
                    for slot in self.time_slots:
                        if slot["day"] == day and self._time_in_range(slot["start"], slot["end"], start, end):
                            preferred_set.add(slot["slot_id"])

            for entity_id, subjects in self.variables.items():
                for subject_id, teachers in subjects.items():
                    if teacher_id in teachers:
                        for room_id, slot_vars in teachers[teacher_id].items():
                            for slot_id, var in slot_vars.items():
                                if slot_id not in preferred_set:
                                    penalty_vars.append(var)

        return sum(penalty_vars) if penalty_vars else 0

    def _create_empty_day_penalty(self, preferred_empty_days: List[str]) -> cp_model.LinearExpr:
        """Penalize classes on preferred empty days."""
        penalty_vars = []

        for day in preferred_empty_days:
            for entity_id, subjects in self.variables.items():
                for subject_id, teachers in subjects.items():
                    for teacher_id, rooms in teachers.items():
                        for room_id, slot_vars in rooms.items():
                            for slot_id, var in slot_vars.items():
                                if slot_id.startswith(day + "_"):
                                    penalty_vars.append(var)

        return sum(penalty_vars) if penalty_vars else 0

    def _create_travel_distance_penalty(self) -> cp_model.LinearExpr:
        """Penalize an entity (section or teacher) having back-to-back classes
        in two different rooms - a real proxy for physical travel between
        classes, without needing room-coordinate data."""
        penalty_vars = []
        entities = {s["id"] for s in self.sections} | {t["id"] for t in self.constraints.get("teachers", [])}

        for entity_id in entities:
            for day in self.days:
                day_slots = sorted([s for s in self.time_slots if s["day"] == day], key=lambda x: x["period"])

                slot_room_indicators: Dict[str, Dict[str, Any]] = {}
                slot_has_class: Dict[str, Any] = {}

                for slot in day_slots:
                    slot_id = slot["slot_id"]
                    room_vars: Dict[str, List[Any]] = defaultdict(list)
                    any_vars = []

                    for sec_id, subjects in self.variables.items():
                        for subject_id, teachers in subjects.items():
                            for teacher_id, rooms in teachers.items():
                                if entity_id not in (sec_id, teacher_id):
                                    continue
                                for room_id, svars in rooms.items():
                                    if slot_id in svars:
                                        room_vars[room_id].append(svars[slot_id])
                                        any_vars.append(svars[slot_id])

                    room_indicators = {}
                    for room_id, vlist in room_vars.items():
                        if len(vlist) == 1:
                            room_indicators[room_id] = vlist[0]
                        else:
                            ind = self.model.NewBoolVar(f"travel_room_{entity_id}_{slot_id}_{room_id}")
                            self.model.AddMaxEquality(ind, vlist)
                            room_indicators[room_id] = ind
                    slot_room_indicators[slot_id] = room_indicators

                    if any_vars:
                        has_class = self.model.NewBoolVar(f"travel_hasclass_{entity_id}_{slot_id}")
                        self.model.AddMaxEquality(has_class, any_vars)
                        slot_has_class[slot_id] = has_class

                for i in range(len(day_slots) - 1):
                    s1, s2 = day_slots[i]["slot_id"], day_slots[i + 1]["slot_id"]
                    if s1 not in slot_has_class or s2 not in slot_has_class:
                        continue

                    rooms1, rooms2 = slot_room_indicators[s1], slot_room_indicators[s2]
                    common_rooms = set(rooms1) & set(rooms2)

                    same_room_vars = []
                    for room_id in common_rooms:
                        same = self.model.NewBoolVar(f"same_room_{entity_id}_{s1}_{s2}_{room_id}")
                        self.model.AddBoolAnd([rooms1[room_id], rooms2[room_id]]).OnlyEnforceIf(same)
                        self.model.AddBoolOr([rooms1[room_id].Not(), rooms2[room_id].Not()]).OnlyEnforceIf(same.Not())
                        same_room_vars.append(same)

                    same_room = self.model.NewBoolVar(f"same_room_any_{entity_id}_{s1}_{s2}")
                    if same_room_vars:
                        self.model.AddMaxEquality(same_room, same_room_vars)
                    else:
                        self.model.Add(same_room == 0)

                    travel = self.model.NewBoolVar(f"travel_{entity_id}_{s1}_{s2}")
                    self.model.AddBoolAnd(
                        [slot_has_class[s1], slot_has_class[s2], same_room.Not()]
                    ).OnlyEnforceIf(travel)
                    self.model.AddBoolOr(
                        [slot_has_class[s1].Not(), slot_has_class[s2].Not(), same_room]
                    ).OnlyEnforceIf(travel.Not())
                    penalty_vars.append(travel)

        return sum(penalty_vars) if penalty_vars else 0

    def _create_class_changes_via_breaks_penalty(self) -> cp_model.LinearExpr:
        """Penalize back-to-back classes without breaks (ensure class changes happen via breaks)."""
        penalty_vars = []

        for entity_id in {s["id"] for s in self.sections} | {t["id"] for t in self.constraints.get("teachers", [])}:
            for day in self.days:
                day_slots = sorted([s for s in self.time_slots if s["day"] == day], key=lambda x: x["period"])

                for i in range(len(day_slots) - 1):
                    slot1 = day_slots[i]
                    slot2 = day_slots[i + 1]
                    slot1_id = slot1["slot_id"]
                    slot2_id = slot2["slot_id"]

                    has_class1 = self.model.NewBoolVar(f"has_class_{entity_id}_{slot1_id}")
                    has_class2 = self.model.NewBoolVar(f"has_class_{entity_id}_{slot2_id}")

                    vars1 = []
                    vars2 = []

                    for sec_id, subjects in self.variables.items():
                        for subject_id, teachers in subjects.items():
                            for teacher_id, rooms in teachers.items():
                                for room_id, slot_vars in rooms.items():
                                    if entity_id in [sec_id, teacher_id]:
                                        if slot1_id in slot_vars:
                                            vars1.append(slot_vars[slot1_id])
                                        if slot2_id in slot_vars:
                                            vars2.append(slot_vars[slot2_id])

                    if vars1:
                        self.model.AddMaxEquality(has_class1, vars1)
                    if vars2:
                        self.model.AddMaxEquality(has_class2, vars2)

                    if vars1 and vars2:
                        both_classes = self.model.NewBoolVar(f"both_classes_{entity_id}_{slot1_id}_{slot2_id}")
                        self.model.AddBoolAnd([has_class1, has_class2]).OnlyEnforceIf(both_classes)
                        self.model.AddBoolOr([has_class1.Not(), has_class2.Not()]).OnlyEnforceIf(both_classes.Not())
                        penalty_vars.append(both_classes)

        return sum(penalty_vars) if penalty_vars else 0

    # ------------------------------------------------------------------
    # Solution extraction / helpers
    # ------------------------------------------------------------------

    def _extract_solution(self) -> Dict[str, Any]:
        """Extract the solution from the solver."""
        entries = []
        section_ids = {s["id"] for s in self.sections}
        batch_ids = {b["id"] for b in self.lab_batches}

        for entity_id, subjects in self.variables.items():
            for subject_id, teachers in subjects.items():
                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        for slot_id, var in slot_vars.items():
                            if self.solver.Value(var) == 1:
                                day, period = slot_id.rsplit("_", 1)
                                entries.append({
                                    "day": day,
                                    "period": int(period),
                                    "section_id": entity_id if entity_id in section_ids else None,
                                    "batch_id": entity_id if entity_id in batch_ids else None,
                                    "subject_id": subject_id,
                                    "teacher_id": teacher_id,
                                    "room_id": room_id
                                })

        return {"entries": entries}

    def _get_conflict_info(self, status: int) -> str:
        """Get human-readable conflict information."""
        status_names = {
            cp_model.UNKNOWN: "UNKNOWN",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE"
        }
        return f"Solver status: {status_names.get(status, status)}"

    def _default_period_to_time(self, period: int) -> time:
        """Fallback when no TimeSlot rows are configured: 9:00 start, 50 min periods."""
        hour = 9 + (period - 1) * 50 // 60
        minute = ((period - 1) * 50) % 60
        return time(hour, minute)

    def _time_overlaps(self, start1: time, end1: time, start2: time, end2: time) -> bool:
        """Check if two time ranges overlap."""
        return start1 < end2 and start2 < end1

    def _time_in_range(self, slot_start: time, slot_end: time, range_start: time, range_end: time) -> bool:
        """Check if slot is within availability range."""
        return slot_start >= range_start and slot_end <= range_end


def solve_timetable(constraints: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    """Main entry point for solving timetable."""
    solver = TimetableSolver(constraints)
    return solver.solve()
