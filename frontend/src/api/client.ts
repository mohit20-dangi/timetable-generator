import axios from 'axios';

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
};

export const institutionsApi = {
  list: () => api.get('/institutions/'),
  create: (data: any) => api.post('/institutions/', data),
  delete: (id: string) => api.delete(`/institutions/${id}`),
};

export const departmentsApi = {
  list: () => api.get('/departments/'),
  create: (data: any) => api.post('/departments/', data),
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
  delete: (id: string) => api.delete(`/subjects/${id}`),
};

export const teachersApi = {
  list: () => api.get('/teachers/'),
  create: (data: any) => api.post('/teachers/', data),
  update: (id: string, data: any) => api.put(`/teachers/${id}`, data),
  get: (id: string) => api.get(`/teachers/${id}`),
  addSubject: (teacherId: string, subjectId: string) => api.post(`/teachers/${teacherId}/subjects`, { subject_id: subjectId }),
  removeSubject: (teacherId: string, subjectId: string) => api.delete(`/teachers/${teacherId}/subjects/${subjectId}`),
  delete: (id: string) => api.delete(`/teachers/${id}`),
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
  addSectionSubject: (data: any) => api.post('/constraints/section-subjects', data),
  getSectionSubjects: (sectionId: string) => api.get(`/constraints/section-subjects/${sectionId}`),
  removeSectionSubject: (sectionId: string, subjectId: string) => api.delete(`/constraints/section-subjects/${sectionId}/${subjectId}`),
  
  // Lab Batches
  createLabBatch: (data: any) => api.post('/constraints/lab-batches', data),
  getLabBatches: (sectionId: string) => api.get(`/constraints/lab-batches/${sectionId}`),
  deleteLabBatch: (id: string) => api.delete(`/constraints/lab-batches/${id}`),
  
  // Prerequisites
  addPrerequisite: (data: any) => api.post('/constraints/prerequisites', data),
  listPrerequisites: () => api.get('/constraints/prerequisites'),
  removePrerequisite: (subjectId: string, requiresSubjectId: string) => api.delete(`/constraints/prerequisites/${subjectId}/${requiresSubjectId}`),
  
  // Time Slots
  createTimeSlot: (data: any) => api.post('/constraints/time-slots', data),
  listTimeSlots: () => api.get('/constraints/time-slots'),
  deleteTimeSlot: (id: string) => api.delete(`/constraints/time-slots/${id}`),
  
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
  previewExcel: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/import/excel/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  uploadExcel: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/import/excel', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  downloadTemplate: () => api.get('/import/excel-template', { responseType: 'blob' }),
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
  export: (runId: number, format: string, view?: string, entityId?: string) =>
    api.get(`/timetable/runs/${runId}/export`, {
      params: { format, ...(view ? { view } : {}), ...(entityId ? { entity_id: entityId } : {}) },
      responseType: 'blob',
    }),
  myTimetable: () => api.get('/timetable/me'),
  publish: (runId: number) => api.post(`/timetable/runs/${runId}/publish`),
  getVersions: (runId: number) => api.get(`/timetable/runs/${runId}/versions`),
  compare: (fromRunId: number, toRunId: number) => api.get(`/timetable/runs/${fromRunId}/compare/${toRunId}`),
  editEntry: (runId: number, body: any) => api.post(`/timetable/runs/${runId}/edit`, body),
};

export const adminDataApi = {
  reset: (scope: string) => api.post(`/admin/data/reset/${scope}`),
};

export default api;
