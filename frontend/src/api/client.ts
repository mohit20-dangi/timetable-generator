import axios from 'axios';
import type { FirstYearApplyRow, FirstYearManualLock } from '../types';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach the JWT (if present) to every outgoing request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  // The department picked in the sidebar. Only the superadmin's requests
  // use it (everyone else is pinned to their own department server-side);
  // see app.auth.scope.active_department on the backend.
  const departmentId = localStorage.getItem('active_department_id');
  if (departmentId) {
    config.headers = config.headers ?? {};
    config.headers['X-Department-Id'] = departmentId;
  }
  return config;
});

// If the token is invalid/expired, boot back to login rather than showing
// a confusing 401 in the middle of some other page.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      const currentToken = localStorage.getItem('access_token');
      const requestAuthorization = error.config?.headers?.Authorization;
      const requestToken = typeof requestAuthorization === 'string'
        ? requestAuthorization.replace(/^Bearer\s+/i, '')
        : null;

      // Only invalidate the session if the failed request used the current
      // token. An older in-flight request must not erase a newer login.
      if (currentToken && requestToken === currentToken) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
      }
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  login: (email: string, password: string) => api.post('/auth/login', { email, password }),
  me: () => api.get('/auth/me'),
  register: (data: any) => api.post('/auth/register', data),
  bootstrapAdmin: (data: any) => api.post('/auth/bootstrap-admin', data),
  listUsers: () => api.get('/auth/users'),
  setUserActive: (id: number, isActive: boolean) =>
    api.patch(`/auth/users/${id}/active`, null, { params: { is_active: isActive } }),
};


export const departmentsApi = {
  list: () => api.get('/departments/'),
  create: (data: any) => api.post('/departments/', data),
  update: (id: string, data: { name: string; code?: string | null }) => api.put(`/departments/${id}`, data),
  delete: (id: string) => api.delete(`/departments/${id}`),
};

export const academicTermsApi = {
  list: () => api.get('/academic-terms/'),
  create: (data: any) => api.post('/academic-terms/', data),
  delete: (id: string) => api.delete(`/academic-terms/${id}`),
};

export const yearsApi = {
  list: () => api.get('/years/'),
  create: (data: any) => api.post('/years/', data),
  update: (id: string, data: any) => api.put(`/years/${id}`, data),
  get: (id: string) => api.get(`/years/${id}`),
  delete: (id: string) => api.delete(`/years/${id}`),
  createRemainingSections: (id: string) => api.post(`/years/${id}/create-remaining-sections`),
};

export const sectionsApi = {
  list: () => api.get('/sections/'),
  create: (data: any) => api.post('/sections/', data),
  update: (id: string, data: any) => api.put(`/sections/${id}`, data),
  get: (id: string) => api.get(`/sections/${id}`),
  getByYear: (yearId: string) => api.get(`/sections/year/${yearId}`),
  delete: (id: string) => api.delete(`/sections/${id}`),
};

export const subjectsApi = {
  list: () => api.get('/subjects/'),
  create: (data: any) => api.post('/subjects/', data),
  update: (id: string, data: any) => api.put(`/subjects/${id}`, data),
  get: (id: string) => api.get(`/subjects/${id}`),
  getTeachers: (id: string) => api.get(`/subjects/${id}/teachers`),
  getTeacherQualificationsMap: () => api.get('/subjects/teacher-qualifications-map'),
  delete: (id: string, dryRun = false) => api.delete(`/subjects/${id}`, { params: dryRun ? { dry_run: true } : {} }),
};

export const teachersApi = {
  list: () => api.get('/teachers/'),
  create: (data: any) => api.post('/teachers/', data),
  update: (id: string, data: any) => api.put(`/teachers/${id}`, data),
  get: (id: string) => api.get(`/teachers/${id}`),
  addSubject: (teacherId: string, subjectId: string) => api.post(`/teachers/${teacherId}/subjects`, { subject_id: subjectId }),
  removeSubject: (teacherId: string, subjectId: string) => api.delete(`/teachers/${teacherId}/subjects/${subjectId}`),
  getSubjects: (teacherId: string) => api.get(`/teachers/${teacherId}/subjects`),
  delete: (id: string, dryRun = false) => api.delete(`/teachers/${id}`, { params: dryRun ? { dry_run: true } : {} }),
};

export const subjectTypesApi = {
  list: () => api.get('/subject-types/'),
  create: (data: any) => api.post('/subject-types/', data),
  update: (id: string, data: any) => api.put(`/subject-types/${id}`, data),
  delete: (id: string) => api.delete(`/subject-types/${id}`),
};

export const equipmentApi = {
  list: () => api.get('/equipment/'),
  create: (data: any) => api.post('/equipment/', data),
  delete: (id: string) => api.delete(`/equipment/${id}`),
};

export const roomsApi = {
  list: () => api.get('/rooms/'),
  create: (data: any) => api.post('/rooms/', data),
  update: (id: string, data: any) => api.put(`/rooms/${id}`, data),
  get: (id: string) => api.get(`/rooms/${id}`),
  delete: (id: string) => api.delete(`/rooms/${id}`),
};

export const constraintsApi = {
  // Section-Subjects
  getAllSectionSubjects: () => api.get('/constraints/section-subjects'),
  addSectionSubject: (data: any) => api.post('/constraints/section-subjects', data),
  getSectionSubjects: (sectionId: string) => api.get(`/constraints/section-subjects/${sectionId}`),
  removeSectionSubject: (sectionId: string, subjectId: string) => api.delete(`/constraints/section-subjects/${sectionId}/${subjectId}`),
  /** Make a (repeater) section sit in another section's class for a subject; both ids null stops it. */
  setAttendance: (sectionId: string, subjectId: string, hostSectionId: string | null, hostBatchId: string | null = null) =>
    api.put(`/constraints/section-subjects/${sectionId}/${subjectId}/attends-with`, {
      attends_with_section_id: hostSectionId, attends_with_batch_id: hostBatchId,
    }),

  // Lab Batches
  createLabBatch: (data: any) => api.post('/constraints/lab-batches', data),
  getAllLabBatches: () => api.get('/constraints/lab-batches'),
  getLabBatches: (sectionId: string) => api.get(`/constraints/lab-batches/${sectionId}`),
  deleteLabBatch: (id: string) => api.delete(`/constraints/lab-batches/${id}`),
  preflightLabBatches: (sectionId: string, subjectId: string) =>
    api.get(`/constraints/lab-batches/${sectionId}/preflight`, { params: { subject_id: subjectId } }),

  // Prerequisites
  addPrerequisite: (data: any) => api.post('/constraints/prerequisites', data),
  listPrerequisites: () => api.get('/constraints/prerequisites'),
  removePrerequisite: (subjectId: string, requiresSubjectId: string) => api.delete(`/constraints/prerequisites/${subjectId}/${requiresSubjectId}`),
  
  // Time Slots
  createTimeSlot: (data: any) => api.post('/constraints/time-slots', data),
  /** kind: regular (default, the main timetable's periods), remedial, or all. */
  listTimeSlots: (kind: 'regular' | 'remedial' | 'all' = 'regular') => api.get('/constraints/time-slots', { params: { kind } }),
  deleteTimeSlot: (id: string) => api.delete(`/constraints/time-slots/${id}`),
  updateTimeSlot: (id: string, data: any) => api.put(`/constraints/time-slots/${id}`, data),
  /** Saves the whole bell schedule at once; the server numbers the periods. */
  replaceTimeSlots: (data: any) => api.put('/constraints/time-slots', data),
  
  // Constraint Profiles
  createProfile: (data: any) => api.post('/constraints/profiles', data),
  updateProfile: (id: string, data: any) => api.put(`/constraints/profiles/${id}`, data),
  listProfiles: () => api.get('/constraints/profiles'),
  getProfile: (id: string) => api.get(`/constraints/profiles/${id}`),
  deleteProfile: (id: string) => api.delete(`/constraints/profiles/${id}`),
  
  // LLM
  parseNL: (text: string) => api.post('/constraints/parse-nl', { text }),
  prototype: (text: string) => api.post('/constraints/prototype', { text }),
};

export const labRotationsApi = {
  list: (sectionId?: string) => api.get('/lab-rotations/', { params: sectionId ? { section_id: sectionId } : {} }),
  create: (data: any) => api.post('/lab-rotations/', data),
  update: (id: string, data: any) => api.put(`/lab-rotations/${id}`, data),
  delete: (id: string) => api.delete(`/lab-rotations/${id}`),
  preflight: (id: string) => api.get(`/lab-rotations/${id}/preflight`),
};

export const electiveGroupsApi = {
  list: () => api.get('/elective-groups/'),
  create: (data: any) => api.post('/elective-groups/', data),
  update: (id: string, data: any) => api.put(`/elective-groups/${id}`, data),
  delete: (id: string) => api.delete(`/elective-groups/${id}`),
  preflight: (id: string) => api.get(`/elective-groups/${id}/preflight`),
};

export const constraintRulesApi = {
  list: (departmentId?: string) => api.get('/constraint-rules/', { params: departmentId ? { department_id: departmentId } : {} }),
  create: (data: any) => api.post('/constraint-rules/', data),
  update: (id: string, data: any) => api.put(`/constraint-rules/${id}`, data),
  delete: (id: string) => api.delete(`/constraint-rules/${id}`),
};

export const aiAgentApi = {
  plan: (departmentId: string, instruction: string) => api.post('/ai/agent/plan', { department_id: departmentId, instruction }),
  apply: (departmentId: string, instruction: string, actions: any[]) =>
    api.post('/ai/agent/apply', { department_id: departmentId, instruction, actions }),
};

export const bulkImportApi = {
  // departmentId: where a department load workbook (which has no ids of
  // its own) is imported to. Template workbooks carry department_id per row.
  previewExcel: (file: File, departmentId?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (departmentId) formData.append('department_id', departmentId);
    return api.post('/import/excel/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  uploadExcel: (file: File, departmentId?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (departmentId) formData.append('department_id', departmentId);
    return api.post('/import/excel', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  downloadTemplate: () => api.get('/import/excel-template', { responseType: 'blob' }),
  downloadCollegeTemplate: () => api.get('/import/college-template', { responseType: 'blob' }),
};

export const firstYearImportApi = {
  // Reading a scanned PDF with OCR takes a while (minutes for 8 pages on a
  // CPU), so this call must not use the short default timeout.
  preview: (file: File, departmentId: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('department_id', departmentId);
    return api.post('/first-year-import/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 20 * 60 * 1000,
    });
  },
  apply: (departmentId: string, rows: FirstYearApplyRow[]) =>
    api.post('/first-year-import/apply', { department_id: departmentId, rows }),
  addManual: (lock: FirstYearManualLock) => api.post('/first-year-import/manual', lock),
  removeOne: (departmentId: string, lockId: number) =>
    api.delete(`/first-year-import/${lockId}`, { params: { department_id: departmentId } }),
  list: (departmentId: string) => api.get('/first-year-import', { params: { department_id: departmentId } }),
  tiles: (departmentId: string) => api.get('/first-year-import/tiles', { params: { department_id: departmentId } }),
  clear: (departmentId: string) => api.delete('/first-year-import', { params: { department_id: departmentId } }),
};

export const timetableApi = {
  generate: (data: any) => api.post('/timetable/generate', data),
  listRuns: () => api.get('/timetable/runs'),
  getRun: (id: number) => api.get(`/timetable/runs/${id}`),
  getEntries: (runId: number) => api.get(`/timetable/runs/${runId}/entries`),
  validate: (runId: number) => api.get(`/timetable/runs/${runId}/validate`),
  getAlternatives: (runId: number) => api.get(`/timetable/runs/${runId}/alternatives`),
  getAlternative: (runId: number, rank: number) => api.get(`/timetable/runs/${runId}/alternatives/${rank}`),
  useAlternative: (runId: number, rank: number) => api.post(`/timetable/runs/${runId}/alternatives/${rank}/use`),
  explain: (runId: number) => api.get(`/timetable/runs/${runId}/explain`),
  export: (runId: number, format: string, view?: string, entityId?: string, yearId?: string) =>
    api.get(`/timetable/runs/${runId}/export`, {
      params: {
        format, ...(view ? { view } : {}), ...(entityId ? { entity_id: entityId } : {}),
        ...(yearId ? { year_id: yearId } : {}),
      },
      responseType: 'blob',
    }),
  myTimetable: () => api.get('/timetable/me'),
  myCalendar: () => api.get('/timetable/me/calendar.ics', { responseType: 'blob' }),
  publish: (runId: number) => api.post(`/timetable/runs/${runId}/publish`),
  getVersions: (runId: number) => api.get(`/timetable/runs/${runId}/versions`),
  compare: (fromRunId: number, toRunId: number) => api.get(`/timetable/runs/${fromRunId}/compare/${toRunId}`),
  editEntry: (runId: number, body: any) => api.post(`/timetable/runs/${runId}/edit`, body),
  parseMoveNL: (runId: number, body: { text: string; subject_id: string; current_day: string; current_period: number }) =>
    api.post(`/timetable/runs/${runId}/parse-move-nl`, body),
  aiPlan: (runId: number, instruction: string) => api.post(`/timetable/runs/${runId}/ai-plan`, { instruction }),
  aiApply: (runId: number, actions: any[]) => api.post(`/timetable/runs/${runId}/ai-apply`, { actions }),
  deleteRun: (runId: number) => api.delete(`/timetable/runs/${runId}`),
};

// Manual timetable editor. Mutations are conflict-gated server-side: a change
// that would introduce a clash is refused with HTTP 409 and
// detail.violations = [{type, message}].
const editorPath = (runId: number, path: string) => `/timetable/runs/${runId}/editor/${path}`;
export const timetableEditorApi = {
  openDraft: (runId: number) => api.post(editorPath(runId, 'draft')),
  check: (runId: number, operations: any[]) => api.post(editorPath(runId, 'check'), { operations }),
  apply: (runId: number, operations: any[], reason?: string) => api.post(editorPath(runId, 'apply'), { operations, reason }),
  slotMap: (runId: number, sessionGroup: string, view: string, entityId: string) =>
    api.get(editorPath(runId, 'slot-map'), { params: { session_group: sessionGroup, view, entity_id: entityId } }),
  options: (runId: number, sessionGroup: string, scope: 'session' | 'all_sessions' = 'all_sessions') =>
    api.get(editorPath(runId, 'options'), { params: { session_group: sessionGroup, scope } }),
  freeSlots: (runId: number, sessionGroup: string, limit = 5) =>
    api.get(editorPath(runId, 'free-slots'), { params: { session_group: sessionGroup, limit } }),
  history: (runId: number) => api.get(editorPath(runId, 'history')),
  undo: (runId: number) => api.post(editorPath(runId, 'undo')),
  redo: (runId: number) => api.post(editorPath(runId, 'redo')),
};

export const remedialApi = {
  listGroups: () => api.get('/remedial/groups'),
  createGroup: (data: any) => api.post('/remedial/groups', data),
  updateGroup: (id: string, data: any) => api.put(`/remedial/groups/${id}`, data),
  deleteGroup: (id: string) => api.delete(`/remedial/groups/${id}`),
  generate: (data: any) => api.post('/remedial/runs', data),
  listRuns: () => api.get('/remedial/runs'),
  getRun: (id: number) => api.get(`/remedial/runs/${id}`),
  getEntries: (id: number) => api.get(`/remedial/runs/${id}/entries`),
  getSectionView: (id: number) => api.get(`/remedial/runs/${id}/section-view`),
  publish: (id: number) => api.post(`/remedial/runs/${id}/publish`),
  deleteRun: (id: number) => api.delete(`/remedial/runs/${id}`),
  export: (id: number) => api.get(`/remedial/runs/${id}/export`, { responseType: 'blob' }),
};

export const publicTimetableApi = {
  listSections: () => api.get('/timetable/public/sections'),
  getSectionView: (sectionId: string) => api.get(`/timetable/public/section/${sectionId}/view`),
  download: (sectionId: string, format: 'pdf' | 'xlsx' | 'ics') =>
    api.get(`/timetable/public/section/${sectionId}/export`, { params: { format }, responseType: 'blob' }),
};

export const adminDataApi = {
  reset: (scope: string) => api.post(`/admin/data/reset/${scope}`),
  previewReset: (scope: string) => api.get(`/admin/data/reset/${scope}/preview`),
};

export default api;

export const customFilterApi = {
  parse: (query: string, runId?: number) =>
    api.post('/custom-filters/parse', { query, ...(runId ? { run_id: runId } : {}) }),
  evaluate: (spec: any, runId?: number) =>
    api.post('/custom-filters/evaluate', { spec, ...(runId ? { run_id: runId } : {}) }),
  listSaved: () => api.get('/custom-filters/saved'),
  save: (body: { name: string; description?: string; original_query?: string; spec: any }) =>
    api.post('/custom-filters/saved', body),
  deleteSaved: (id: string) => api.delete(`/custom-filters/saved/${id}`),
};
