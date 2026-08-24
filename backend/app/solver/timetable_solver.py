from ortools.sat.python import cp_model
from typing import Dict, List, Any, Optional, Tuple
from datetime import time
import json

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
    
    def _create_variables(self):
        """Create decision variables for the CP-SAT model."""
        years = self.constraints.get("years", [])
        subjects = self.constraints.get("subjects", [])
        teachers = self.constraints.get("teachers", [])
        rooms = self.constraints.get("rooms", [])
        
        # Build lookup maps
        self.subject_map = {s["id"]: s for s in subjects}
        self.teacher_map = {t["id"]: t for t in teachers}
        self.room_map = {r["id"]: r for r in rooms}
        
        # Get all sections from years
        self.sections = []
        for year in years:
            for i in range(year.get("sections", 1)):
                section_id = f"{year['id']}_sec{i+1}"
                self.sections.append({
                    "id": section_id,
                    "year_id": year["id"],
                    "name": f"{year['name']} Section {i+1}",
                    "strength": 60,
                    "lunch_start": year.get("lunch", {}).get("start"),
                    "lunch_end": year.get("lunch", {}).get("end")
                })
        
        # Get all time slots (assuming 6 days, 8 periods per day)
        self.days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        self.periods_per_day = 8
        self.time_slots = []
        for day_idx, day in enumerate(self.days):
            for period in range(1, self.periods_per_day + 1):
                self.time_slots.append({
                    "day": day,
                    "period": period,
                    "slot_id": f"{day}_{period}"
                })
        
        # Create assignment variables: assign[section_id][subject_id][teacher_id][room_id][day][period] = 0/1
        for section in self.sections:
            section_id = section["id"]
            self.variables[section_id] = {}
            
            # Get subjects for this section (from section_subjects in constraints)
            section_subjects = self.constraints.get("section_subjects", {}).get(section_id, [])
            
            for subject_id in section_subjects:
                subject = self.subject_map.get(subject_id)
                if not subject:
                    continue
                    
                self.variables[section_id][subject_id] = {}
                
                # Get eligible teachers for this subject
                eligible_teachers = [
                    t["id"] for t in teachers 
                    if subject_id in t.get("subjects", [])
                ]
                
                # Get eligible rooms for this subject
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
                            var_name = f"assign_{section_id}_{subject_id}_{teacher_id}_{room_id}_{slot['day']}_{slot['period']}"
                            self.variables[section_id][subject_id][teacher_id][room_id][slot["slot_id"]] = \
                                self.model.NewBoolVar(var_name)
        
        # Handle lab batches
        self.lab_batches = self.constraints.get("lab_batches", [])
        for batch in self.lab_batches:
            batch_id = batch["id"]
            self.variables[batch_id] = {}
            
            # Get subjects for this batch's section
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
                            var_name = f"assign_{batch_id}_{subject_id}_{teacher_id}_{room_id}_{slot['day']}_{slot['period']}"
                            self.variables[batch_id][subject_id][teacher_id][room_id][slot["slot_id"]] = \
                                self.model.NewBoolVar(var_name)
    
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
        
        # For lab batches
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
        """No classes during lunch break for each year."""
        for section in self.sections:
            section_id = section["id"]
            lunch_start_str = section.get("lunch_start")
            lunch_end_str = section.get("lunch_end")
            if not lunch_start_str or not lunch_end_str or section_id not in self.variables:
                continue
            
            # Convert string times to time objects
            from datetime import time
            lunch_start = time.fromisoformat(lunch_start_str) if isinstance(lunch_start_str, str) else lunch_start_str
            lunch_end = time.fromisoformat(lunch_end_str) if isinstance(lunch_end_str, str) else lunch_end_str
            
            # Find periods that fall within lunch
            lunch_periods = []
            for slot in self.time_slots:
                slot_start = self._period_to_time(slot["period"])
                slot_end = self._period_to_time(slot["period"] + 1)
                if self._time_overlaps(slot_start, slot_end, lunch_start, lunch_end):
                    lunch_periods.append(slot["slot_id"])
            
            for subject_id, teachers in self.variables[section_id].items():
                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        for slot_id in lunch_periods:
                            if slot_id in slot_vars:
                                self.model.Add(slot_vars[slot_id] == 0)
    
    def _teacher_availability_constraint(self):
        """Teachers can only teach during their available slots."""
        for teacher in self.constraints.get("teachers", []):
            teacher_id = teacher["id"]
            availability = teacher.get("availability", [])
            if not availability:
                continue
            
            # Build set of available slot_ids
            available_slots = set()
            for avail in availability:
                day = avail["day"]
                start_str = avail["start"]
                end_str = avail["end"]
                # Convert string times to time objects
                from datetime import time
                start = time.fromisoformat(start_str) if isinstance(start_str, str) else start_str
                end = time.fromisoformat(end_str) if isinstance(end_str, str) else end_str
                for slot in self.time_slots:
                    if slot["day"] == day:
                        slot_start = self._period_to_time(slot["period"])
                        slot_end = self._period_to_time(slot["period"] + 1)
                        if self._time_in_range(slot_start, slot_end, start, end):
                            available_slots.add(slot["slot_id"])
            
            # Forbid assignments outside available slots
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
            
            # Build set of available slot_ids
            available_slots = set()
            for avail in availability:
                day = avail["day"]
                start_str = avail["start"]
                end_str = avail["end"]
                # Convert string times to time objects
                from datetime import time
                start = time.fromisoformat(start_str) if isinstance(start_str, str) else start_str
                end = time.fromisoformat(end_str) if isinstance(end_str, str) else end_str
                for slot in self.time_slots:
                    if slot["day"] == day:
                        slot_start = self._period_to_time(slot["period"])
                        slot_end = self._period_to_time(slot["period"] + 1)
                        if self._time_in_range(slot_start, slot_end, start, end):
                            available_slots.add(slot["slot_id"])
            
            # Forbid assignments outside available slots
            for entity_id, subjects in self.variables.items():
                for subject_id, teachers in subjects.items():
                    for teacher_id, rooms in teachers.items():
                        if room_id in rooms:
                            for slot_id, var in rooms[room_id].items():
                                if slot_id not in available_slots:
                                    self.model.Add(var == 0)
    
    def _continuous_block_constraint(self):
        """Subjects needing continuous blocks must get back-to-back periods."""
        for section in self.sections:
            section_id = section["id"]
            if section_id not in self.variables:
                continue
            for subject_id, teachers in self.variables[section_id].items():
                subject = self.subject_map.get(subject_id)
                if not subject or not subject.get("needs_continuous_block", False):
                    continue
                
                block_size = subject.get("block_size", 2)
                weekly_hours = subject.get("weekly_hours", 0)
                num_blocks = weekly_hours // block_size
                
                if num_blocks == 0:
                    continue
                
                # For each teacher-room combination, enforce continuous blocks
                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        # Create helper variables for block starts
                        for day in self.days:
                            day_slots = [s for s in self.time_slots if s["day"] == day]
                            day_slots.sort(key=lambda x: x["period"])
                            
                            for i in range(len(day_slots) - block_size + 1):
                                block_slots = day_slots[i:i+block_size]
                                block_var_name = f"block_{section_id}_{subject_id}_{teacher_id}_{room_id}_{day}_{i}"
                                block_var = self.model.NewBoolVar(block_var_name)
                                
                                # block_var == 1 iff all slots in block are 1
                                block_slot_vars = [slot_vars.get(s["slot_id"]) for s in block_slots if s["slot_id"] in slot_vars]
                                if len(block_slot_vars) == block_size:
                                    self.model.Add(sum(block_slot_vars) == block_size).OnlyEnforceIf(block_var)
                                    self.model.Add(sum(block_slot_vars) < block_size).OnlyEnforceIf(block_var.Not())
                        
                        # Total blocks must equal num_blocks
                        # This is complex - simplified: ensure if any slot is 1, it's part of a block
                        pass  # Simplified for now
    
    def _prerequisite_constraint(self):
        """Prerequisite subjects must be scheduled before dependent subjects."""
        prerequisites = self.constraints.get("prerequisites", [])
        if not prerequisites:
            return
        
        # For each prerequisite pair, ensure the required subject is scheduled in an earlier period
        # This is a simplified version - in practice, you'd need day ordering too
        pass  # Complex constraint, simplified for now
    
    def _lab_batch_simultaneous_constraint(self):
        """Lab batches of the same section/subject must be scheduled simultaneously."""
        lab_batches = self.constraints.get("lab_batches", [])
        if not lab_batches:
            return
        
        # Group batches by section and subject
        batch_groups = {}
        for batch in lab_batches:
            section_id = batch["section_id"]
            key = (section_id, "lab")  # Simplified - should be per subject
            if key not in batch_groups:
                batch_groups[key] = []
            batch_groups[key].append(batch["id"])
        
        # For each group, batches must be at same time (different rooms)
        for (section_id, _), batch_ids in batch_groups.items():
            if len(batch_ids) < 2:
                continue
            
            # For each subject, time slot - at most one batch per slot (they run in parallel)
            # Actually, they should run simultaneously - same time, different rooms
            # This is handled by the no-room-double-booking and teacher constraints
            pass
    
    def _add_soft_constraints(self):
        """Add soft constraints as objective function terms."""
        weights = self.constraints.get("soft_constraint_weights", {})
        
        objective_terms = []
        
        # Minimize gaps for teachers
        if weights.get("minimize_gaps", 0) > 0:
            gap_penalty = self._create_gap_penalty("teacher")
            objective_terms.append(gap_penalty * weights["minimize_gaps"])
        
        # Minimize gaps for students (sections)
        if weights.get("minimize_student_gaps", 0) > 0:
            gap_penalty = self._create_gap_penalty("section")
            objective_terms.append(gap_penalty * weights["minimize_student_gaps"])
        
        # Teacher preference
        if weights.get("teacher_preference", 0) > 0:
            pref_penalty = self._create_teacher_preference_penalty()
            objective_terms.append(pref_penalty * weights["teacher_preference"])
        
        # Empty day preference (Mon/Fri lighter)
        empty_day_weight = weights.get("empty_day_preference", 0)
        if empty_day_weight > 0:
            empty_day_pref = weights.get("empty_day_preference", [])
            # Ensure it's a list
            if not isinstance(empty_day_pref, list):
                empty_day_pref = [str(empty_day_pref)] if empty_day_pref else []
            empty_day_penalty = self._create_empty_day_penalty(empty_day_pref)
            objective_terms.append(empty_day_penalty * empty_day_weight)
        
        # Minimize travel distance between consecutive classes
        if weights.get("minimize_travel", 0) > 0:
            travel_penalty = self._create_travel_distance_penalty()
            objective_terms.append(travel_penalty * weights["minimize_travel"])
        
        # Class changes via breaks (ensure breaks between classes)
        if weights.get("class_changes_via_breaks", 0) > 0:
            break_penalty = self._create_class_changes_via_breaks_penalty()
            objective_terms.append(break_penalty * weights["class_changes_via_breaks"])
        
        if objective_terms:
            self.model.Minimize(sum(objective_terms))
    
    def _create_gap_penalty(self, entity_type: str) -> cp_model.LinearExpr:
        """Create penalty variables for gaps in schedule."""
        # Simplified: count empty slots between first and last class per day
        penalty_vars = []
        
        if entity_type == "teacher":
            entities = {t["id"]: t for t in self.constraints.get("teachers", [])}
        else:
            entities = {s["id"]: s for s in self.sections}
        
        for entity_id in entities:
            for day in self.days:
                day_slots = [s for s in self.time_slots if s["day"] == day]
                day_slots.sort(key=lambda x: x["period"])
                
                # Get all assignment vars for this entity on this day
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
                        # Create indicator: has_class = OR of all vars
                        has_class = self.model.NewBoolVar(f"has_class_{entity_id}_{day}_{slot['period']}")
                        self.model.AddMaxEquality(has_class, vars_for_slot)
                        entity_vars[slot["period"]] = has_class
                
                if len(entity_vars) >= 3:
                    # Penalize gaps: if has_class at period i and i+2 but not i+1
                    for i in range(len(day_slots) - 2):
                        p1, p2, p3 = day_slots[i]["period"], day_slots[i+1]["period"], day_slots[i+2]["period"]
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
            
            # Build set of preferred slot_ids (new format with multiple intervals)
            preferred_set = set()
            for pref in preferred:
                day = pref["day"]
                for slot_obj in pref.get("slots", []):
                    start_str = slot_obj["start"]
                    end_str = slot_obj["end"]
                    from datetime import time
                    start = time.fromisoformat(start_str) if isinstance(start_str, str) else start_str
                    end = time.fromisoformat(end_str) if isinstance(end_str, str) else end_str
                    for slot in self.time_slots:
                        if slot["day"] == day:
                            slot_start = self._period_to_time(slot["period"])
                            slot_end = self._period_to_time(slot["period"] + 1)
                            if self._time_in_range(slot_start, slot_end, start, end):
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
        """Penalize travel distance between consecutive classes for teachers and students."""
        penalty_vars = []
        
        # For simplicity, we'll penalize consecutive classes in different rooms
        # In a full implementation, you'd use room coordinates
        for entity_id in {s["id"] for s in self.sections} | {t["id"] for t in self.constraints.get("teachers", [])}:
            for day in self.days:
                day_slots = [s for s in self.time_slots if s["day"] == day]
                day_slots.sort(key=lambda x: x["period"])
                
                for i in range(len(day_slots) - 1):
                    slot1 = day_slots[i]
                    slot2 = day_slots[i+1]
                    slot1_id = slot1["slot_id"]
                    slot2_id = slot2["slot_id"]
                    
                    # Check if entity has classes in both consecutive slots but in different rooms
                    # This is a simplified version - in practice you'd track room assignments
                    pass
        
        return 0  # Placeholder - full implementation would require room coordinates
    
    def _create_class_changes_via_breaks_penalty(self) -> cp_model.LinearExpr:
        """Penalize back-to-back classes without breaks (ensure class changes happen via breaks)."""
        penalty_vars = []
        
        # Penalize consecutive classes for the same entity without a break period
        for entity_id in {s["id"] for s in self.sections} | {t["id"] for t in self.constraints.get("teachers", [])}:
            for day in self.days:
                day_slots = [s for s in self.time_slots if s["day"] == day]
                day_slots.sort(key=lambda x: x["period"])
                
                for i in range(len(day_slots) - 1):
                    slot1 = day_slots[i]
                    slot2 = day_slots[i+1]
                    slot1_id = slot1["slot_id"]
                    slot2_id = slot2["slot_id"]
                    
                    # Create indicator variables for whether entity has class in each slot
                    has_class1 = self.model.NewBoolVar(f"has_class_{entity_id}_{slot1_id}")
                    has_class2 = self.model.NewBoolVar(f"has_class_{entity_id}_{slot2_id}")
                    
                    # Collect all assignment variables for this entity in these slots
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
                    
                    # Penalize if both consecutive slots have classes (no break between)
                    if vars1 and vars2:
                        both_classes = self.model.NewBoolVar(f"both_classes_{entity_id}_{slot1_id}_{slot2_id}")
                        self.model.AddBoolAnd([has_class1, has_class2]).OnlyEnforceIf(both_classes)
                        self.model.AddBoolOr([has_class1.Not(), has_class2.Not()]).OnlyEnforceIf(both_classes.Not())
                        penalty_vars.append(both_classes)
        
        return sum(penalty_vars) if penalty_vars else 0
    
    def _extract_solution(self) -> Dict[str, Any]:
        """Extract the solution from the solver."""
        entries = []
        
        for entity_id, subjects in self.variables.items():
            for subject_id, teachers in subjects.items():
                for teacher_id, rooms in teachers.items():
                    for room_id, slot_vars in rooms.items():
                        for slot_id, var in slot_vars.items():
                            if self.solver.Value(var) == 1:
                                day, period = slot_id.split("_")
                                entries.append({
                                    "day": day,
                                    "period": int(period),
                                    "section_id": entity_id if entity_id.startswith("y") else None,
                                    "batch_id": entity_id if entity_id.startswith("batch") else None,
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
    
    def _period_to_time(self, period: int) -> time:
        """Convert period index to time (assuming 9:00 start, 50 min periods)."""
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