export interface Department {
  id: string;
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
  /** A section of repeating students; it sits in other sections' classes
   * for the subjects set on its curriculum rows. */
  is_repeater?: boolean;
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
  // How many qualified teachers one session needs AT ONCE - 2+ for a lab
  // that needs a second supervisor on the floor. The extra teachers show
  // up on each generated entry as co_teacher_ids.
  teachers_required: number;
  // One-period self-study blocks a week for a subject not taught in person
  // (an NPTEL elective); always the first or last period of a day.
  self_study_hours: number;
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
  // Hours/week given to the first-year timetable; taken off max_weekly_hours.
  first_year_hours: number;
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
  /** Set when this section takes the subject by sitting in another section's class. */
  attends_with_section_id?: string | null;
  attends_with_batch_id?: string | null;
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
  /** regular: main timetable period; remedial: only remedial classes use it. */
  slot_kind?: 'regular' | 'remedial';
}

export interface RemedialGroup {
  id: string;
  department_id: string;
  name: string;
  subject_id: string;
  section_ids: string[];
  strength: number;
  periods_per_week: number;
  periods_per_session: number;
  teacher_id: string | null;
  allowed_days: string[] | null;
  is_active: boolean;
}

export interface RemedialSettings {
  preferred_max_per_day: number;
  hard_max_per_day: number;
  use_free_regular_slots: boolean;
  teacher_max_remedial_per_day: number;
  teacher_max_remedial_per_week: number;
  weight_mid_day_gap: number;
  weight_non_regular_teacher: number;
  weight_over_preferred_per_day: number;
  max_seconds: number;
}

export interface RemedialRun {
  id: number;
  department_id: string;
  status: 'pending' | 'solving' | 'completed' | 'failed';
  settings: RemedialSettings | null;
  solver_output: { warnings?: string[]; sessions_scheduled?: number } | null;
  explanation: string | null;
  created_at: string | null;
  completed_at: string | null;
  is_published: boolean;
}

export interface RemedialSectionView {
  sections: {
    section_id: string;
    name: string;
    main: { day: string; period: number; subject_id: string | null; teacher_id: string | null; room_id: string | null; batch_id: string | null }[];
    remedial: { day: string; period: number; group_id: string | null; group_name: string; subject_id: string | null; teacher_id: string | null; room_id: string | null; in_remedial_slot: boolean }[];
  }[];
  slots: { day: string; period_index: number; start_time: string; end_time: string; slot_kind: 'regular' | 'remedial' }[];
}

export type ImportanceLevel = 'must_have' | 'very_important' | 'nice_to_have' | 'dont_care';

export interface ConstraintProfile {
  id: string;
  name: string;
  department_id: string | null;
  soft_constraint_weights: Record<string, ImportanceLevel>;
  // Numbers typed into rules that take one, e.g. { max_consecutive_teaching: 2 }.
  rule_params?: Record<string, number> | null;
}

export interface ElectiveGroup {
  id: string;
  department_id: string;
  name: string;
  offered_subject_ids: string[];
  must_be_parallel: boolean;
}

// A set of lab subjects one section runs as a ROTATION: in each round every
// batch is in a different one of these labs, swapping until every batch has
// done every lab. This is what "run the labs together" almost always means -
// unlike batch_scheduling_mode: 'parallel', which puts every batch in the
// SAME lab at once and so needs one qualified teacher per batch.
export interface LabRotationGroup {
  id: string;
  department_id: string;
  name: string;
  section_id: string;
  subject_ids: string[];
  // Optional pinned window ("Monday 14:00-16:00"), all three or none.
  day: string | null;
  start_time: string | null;
  end_time: string | null;
  source: string;
  raw_instruction: string | null;
  is_active: boolean;
}

export interface LabRotationPreflightIssue {
  severity: 'blocking' | 'warning';
  message: string;
  kind?: 'subjects' | 'batches' | 'teachers' | 'rooms' | 'window' | null;
}

export interface LabRotationPreflightResult {
  feasible: boolean;
  batch_count: number;
  round_count: number;
  issues: LabRotationPreflightIssue[];
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
  params?: { max?: number; mode?: 'within' | 'avoid' } | null;
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
  // Both are empty for a self-study block (an NPTEL elective), which has no teacher or room.
  teacher_id: string;
  room_id: string;
  is_locked?: boolean;
  is_manual?: boolean;
}

// ---- Manual timetable editor (backend: app/schemas/timetable_edit.py) ----
export type EditOperation =
  | { type: 'move'; session_group: string; day: string; period: number }
  | { type: 'swap'; session_group_a: string; session_group_b: string }
  | { type: 'change_teacher'; session_group: string; teacher_id: string; scope?: 'session' | 'all_sessions' }
  | { type: 'change_room'; session_group: string; room_id: string }
  | { type: 'delete'; session_group: string }
  | { type: 'add'; section_id?: string | null; batch_id?: string | null; subject_id: string; teacher_id: string; room_id: string; day: string; period: number; duration?: number }
  | { type: 'lock'; session_group: string }
  | { type: 'unlock'; session_group: string };

export interface EditConflict {
  type: string;
  message: string;
}

export interface EditCheckResult {
  ok: boolean;
  violations: EditConflict[];
  changed_groups: string[];
}

export interface SlotStatus {
  day: string;
  period: number;
  ok: boolean;
  reasons: string[];
  occupant_group?: string | null;
  swap_ok?: boolean | null;
  swap_reasons: string[];
}

export interface ResourceOption {
  id: string;
  name: string;
  free: boolean;
  reasons: string[];
}

export interface EditHistoryItem {
  id: number;
  action: string;
  reason: string | null;
  actor_user_id: number | null;
  created_at: string | null;
  undone: boolean;
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

export type FilterMode = 'classes' | 'free_slots';

export interface FilterSpec {
  mode: FilterMode;
  days: string[];
  time_from: string | null;
  time_to: string | null;
  teacher_ids: string[]; // may contain "$me"
  section_ids: string[];
  subject_ids: string[];
  room_ids: string[];
  room_types: string[];
  subject_types: string[];
  min_room_capacity: number | null;
}

export interface FilterCell {
  day: string;
  period: number;
  entries: TimetableEntry[];
  free_rooms: Array<{ id: string; name: string; capacity: number | null; type: string | null }>;
}

export interface SavedFilter {
  id: string;
  name: string;
  description: string | null;
  original_query: string | null;
  spec: FilterSpec;
  department_id: string | null;
  created_by: number | null;
  created_at: string | null;
}

// ---- First-year central timetable import -----------------------------------
export interface FirstYearPeriod { day: string; period: number }

export interface FirstYearCandidate { teacher_id: string; name: string; initials: string }

export interface FirstYearTeacherHit {
  code: string;
  // matched: exactly one of our teachers; ambiguous: several share the code;
  // unread: the OCR half-read it and these are the teachers it might be.
  status: 'matched' | 'ambiguous' | 'unread';
  teacher_id: string | null;
  teacher_name: string | null;
  candidates: FirstYearCandidate[];
}

export interface FirstYearPreviewRow {
  id: string;
  page: number;
  section: string;
  day: string;
  start: string;
  end: string;
  periods: FirstYearPeriod[];
  subject: string;
  cell_text: string;
  teachers: FirstYearTeacherHit[];
  room_text: string;
  room_id: string | null;
  room_name: string | null;
  faculty: FirstYearFaculty[];
  batches: string[];
}

export interface FirstYearFaculty { code: string; name: string | null }

/** The class as printed on the central timetable; kept so the by-teacher and
 * by-room views can draw the whole tile. */
export interface FirstYearTileDetails {
  section: string;
  subject: string;
  batches: string[];
  faculty: FirstYearFaculty[];
  room_text: string;
  start: string;
  end: string;
}

export interface FirstYearUnreadable {
  page: string; section: string; day: string; start: string; end: string; subject: string; text: string;
}

export interface FirstYearPreview {
  pages: { page: number; section: string; cells: number; warnings: string[] }[];
  rows: FirstYearPreviewRow[];
  unmatched_codes: { code: string; count: number; name: string | null }[];
  unreadable: FirstYearUnreadable[];
  warnings: string[];
}

export interface FirstYearApplyRow {
  periods: FirstYearPeriod[];
  teacher_ids: string[];
  room_id: string | null;
  reason: string;
  tile?: FirstYearTileDetails;
}

/** One first-year class as shown for ONE teacher or room; `periods` are only
 * the slots that resource is locked for. */
export interface FirstYearTile extends FirstYearTileDetails {
  tile_id: number;
  resource_type: 'teacher' | 'room';
  resource_id: string;
  day: string;
  periods: number[];
}

export interface FirstYearLock {
  id: number;
  resource_type: 'teacher' | 'room';
  resource_id: string;
  resource_name: string;
  day: string;
  period: number;
  reason: string | null;
}

export interface FirstYearManualLock {
  department_id: string;
  resource_type: 'teacher' | 'room';
  resource_id: string;
  periods: FirstYearPeriod[];
  reason: string;
  subject: string;
  section: string;
  batches: string[];
  faculty_text: string;
  room_text: string;
}
