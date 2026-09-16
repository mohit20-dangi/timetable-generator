export interface AcademicYear {
  id: string;
  name: string;
  num_sections: number;
  lunch_start: string | null;
  lunch_end: string | null;
}

export interface Section {
  id: string;
  year_id: string;
  name: string;
  strength: number;
}

export interface Subject {
  id: string;
  name: string;
  type: 'theory' | 'lab' | 'tutorial';
  weekly_hours: number;
  needs_continuous_block: boolean;
  block_size: number;
  requires_room_type: string | null;
  requires_equipment: string[];
}

export interface Teacher {
  id: string;
  name: string;
  department: string | null;
  max_continuous_classes: number;
  max_daily_classes: number;
  availability: AvailabilitySlot[];
  preferred_slots: PreferredSlot[];
  is_guest_from_other_dept: boolean;
}

export interface AvailabilitySlot {
  day: string;
  start: string;
  end: string;
}

export interface PreferredSlot {
  day: string;
  slots: Array<{ start: string; end: string }>;
}

export interface Room {
  id: string;
  name: string;
  type: 'lecture' | 'lab' | 'seminar';
  capacity: number;
  equipment: string[];
  shared_with_departments: string[];
  availability: Array<{ day: string; start: string; end: string }>;
}

export interface SectionSubject {
  section_id: string;
  subject_id: string;
  is_elective: boolean;
  elective_group_id: string | null;
}

export interface LabBatch {
  id: string;
  section_id: string;
  batch_name: string;
  strength: number;
}

export interface Prerequisite {
  subject_id: string;
  requires_subject_id: string;
}

export interface TimeSlot {
  id: string;
  day: string;
  period_index: number;
  start_time: string;
  end_time: string;
}

export interface ConstraintProfile {
  id: string;
  name: string;
  soft_constraint_weights: Record<string, number>;
}

export interface TimetableRun {
  id: number;
  constraint_profile_id: string | null;
  status: 'pending' | 'solving' | 'completed' | 'failed';
  solver_output: any;
  llm_explanation: string | null;
  created_at: string;
  completed_at: string | null;
  is_published: boolean;
  published_at: string | null;
  parent_run_id: number | null;
  change_summary: string | null;
}

export interface TimetableEntry {
  id: number;
  timetable_run_id: number;
  day: string;
  period: number;
  section_id: string | null;
  batch_id: string | null;
  subject_id: string;
  teacher_id: string;
  room_id: string;
}

export interface NLConstraintParseRequest {
  text: string;
}

export interface NLConstraintParseResponse {
  parsed_constraints: any;
  raw_response: string;
}

export interface TimetableGenerateRequest {
  constraint_profile_id?: string;
  num_alternatives?: number;
}
