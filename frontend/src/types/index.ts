export interface Institution {
  id: string;
  name: string;
  city: string | null;
  timezone: string;
}

export interface Department {
  id: string;
  institution_id: string;
  name: string;
  code: string | null;
}

export interface AcademicTerm {
  id: string;
  department_id: string;
  name: string;
  start_date: string;
  end_date: string;
  working_days: string[];
  holidays: string[];
  teaching_weeks?: number;
}

export interface AcademicYear {
  id: string;
  department_id: string | null;
  name: string;
  num_sections: number;
  default_section_strength: number;
  // {"Mon": ["12:00", "13:00"], ...} - a day left out has no lunch break.
  lunch_windows: Record<string, [string, string]>;
}

export interface SubjectType {
  id: string;
  name: string;
  default_block_size: number;
  default_room_type: string | null;
  colour_hex: string;
  is_builtin: boolean;
}

export interface Equipment {
  id: string;
  name: string;
}

export interface Section {
  id: string;
  year_id: string;
  name: string;
  strength: number;
}

export type DeliveryMode = 'IN_PERSON' | 'MOOC_NPTEL' | 'SELF_STUDY' | 'INDUSTRY';

// independent: no hard link between sibling lab batches (only the soft
//   "parallel_lab_batches" preference nudges them together).
// parallel: hard - same start slot, separate rooms (and usually teachers).
// sequential: hard - sibling batches may never overlap in time.
// merged: hard - same start slot, same room AND same teacher - taught as
//   one combined class (requires a room big enough for every batch
//   combined; see the lab-batches preflight check).
export type BatchSchedulingMode = 'independent' | 'parallel' | 'sequential' | 'merged';

export interface Subject {
  id: string;
  name: string;
  code: string | null;
  type: string;
  department_id: string | null;
  category: string | null;
  delivery_mode: DeliveryMode;
  lecture_hours: number;
  tutorial_hours: number;
  practical_hours: number;
  scheme_hours_per_week: number | null;
  weekly_hours: number;
  sessions_per_week: number | null;
  periods_per_session: number;
  back_to_back: boolean;
  batch_scheduling_mode: BatchSchedulingMode;
  max_per_day: number;
  requires_room_type: string | null;
  requires_equipment: string[];
  linked_group_id: string | null;
  elective_group_id: string | null;
}

export interface Teacher {
  id: string;
  name: string;
  initials: string | null;
  department_id: string | null;
  max_continuous_classes: number;
  max_daily_classes: number;
  max_weekly_hours: number;
  availability: AvailabilitySlot[];
  preferred_slots: PreferredSlot[];
  is_guest_from_other_dept: boolean;
  subjects?: string[];
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
  department_id: string | null;
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

export type ImportanceLevel = 'must_have' | 'very_important' | 'nice_to_have' | 'dont_care';

export interface ConstraintProfile {
  id: string;
  name: string;
  department_id: string | null;
  soft_constraint_weights: Record<string, ImportanceLevel>;
}

export interface ElectiveGroup {
  id: string;
  department_id: string;
  name: string;
  offered_subject_ids: string[];
  must_be_parallel: boolean;
}

export interface ElectivePreflightIssue {
  severity: 'blocking' | 'warning';
  message: string;
  kind?: 'rooms' | 'teachers' | null;
}

export interface ElectivePreflightResult {
  feasible: boolean;
  offered_count: number;
  rooms_available_in_common_slot: number;
  qualified_teachers: number;
  issues: ElectivePreflightIssue[];
}

export interface BatchPreflightIssue {
  severity: 'blocking' | 'warning';
  message: string;
  kind?: 'rooms' | 'teachers' | null;
}

export interface BatchPreflightResult {
  feasible: boolean;
  mode: BatchSchedulingMode;
  batch_count: number;
  combined_strength: number;
  rooms_available_in_common_slot: number;
  qualified_teachers: number;
  issues: BatchPreflightIssue[];
}

export interface ConstraintRule {
  id: string;
  department_id: string;
  rule_type: string;
  target_type: string;
  target_id: string;
  day: string | null;
  start_time: string | null;
  end_time: string | null;
  priority: 'hard' | 'soft';
  weight: number;
  batch_mode?: BatchSchedulingMode | null;
  description: string | null;
  source: 'manual' | 'ai_parsed';
  raw_instruction: string | null;
  is_active: boolean;
}

export type ScopeMode = 'fit_into_existing' | 'fresh';

export interface TimetableRun {
  id: number;
  department_id: string | null;
  constraint_profile_id: string | null;
  term_id: string | null;
  status: 'pending' | 'solving' | 'completed' | 'failed';
  scope_mode: ScopeMode | null;
  year_ids: string[] | null;
  section_ids: string[] | null;
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
  alternative_rank: number;
  session_group: string | null;
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
  department_id?: string;
}

export interface NLConstraintParseResponse {
  parsed_constraints: any;
  raw_response: string;
  ambiguities: string[];
  unsupported_requests: string[];
}

export interface TimetableGenerateRequest {
  department_id: string;
  constraint_profile_id?: string;
  num_alternatives?: number;
  year_ids?: string[];
  section_ids?: string[];
  scope_mode?: ScopeMode;
}

export interface AgentProposedAction {
  action_type: string;
  description: string;
  payload: Record<string, any>;
}

export interface AgentPlanResponse {
  summary: string;
  actions: AgentProposedAction[];
}
