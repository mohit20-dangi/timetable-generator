import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach the admin JWT (if present) to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// A 401 means the token is missing/expired - drop it and send the user to log in.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  login: (username: string, password: string) => {
    const form = new URLSearchParams();
    form.set('username', username);
    form.set('password', password);
    return axios.post('/api/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
  },
  register: (data: { invite_token: string; username: string; password: string }) =>
    api.post('/auth/register', data),
  createInvite: () => api.post('/auth/invites', {}),
  me: () => api.get('/auth/me'),
};

export const yearsApi = {
  list: () => api.get('/years'),
  create: (data: any) => api.post('/years', data),
  get: (id: string) => api.get(`/years/${id}`),
  delete: (id: string) => api.delete(`/years/${id}`),
};

export const sectionsApi = {
  list: () => api.get('/sections'),
  create: (data: any) => api.post('/sections', data),
  get: (id: string) => api.get(`/sections/${id}`),
  getByYear: (yearId: string) => api.get(`/sections/year/${yearId}`),
  delete: (id: string) => api.delete(`/sections/${id}`),

  addSubject: (sectionId: string, data: any) => api.post(`/sections/${sectionId}/subjects`, data),
  removeSubject: (sectionId: string, subjectId: string) =>
    api.delete(`/sections/${sectionId}/subjects/${subjectId}`),

  createLabBatch: (sectionId: string, data: any) => api.post(`/sections/${sectionId}/lab-batches`, data),
  deleteLabBatch: (sectionId: string, batchId: string) =>
    api.delete(`/sections/${sectionId}/lab-batches/${batchId}`),
};

export const subjectsApi = {
  list: () => api.get('/subjects'),
  create: (data: any) => api.post('/subjects', data),
  get: (id: string) => api.get(`/subjects/${id}`),
  delete: (id: string) => api.delete(`/subjects/${id}`),

  addPrerequisite: (subjectId: string, requiresSubjectId: string) =>
    api.post(`/subjects/${subjectId}/prerequisites/${requiresSubjectId}`),
  removePrerequisite: (subjectId: string, requiresSubjectId: string) =>
    api.delete(`/subjects/${subjectId}/prerequisites/${requiresSubjectId}`),
};

export const teachersApi = {
  list: () => api.get('/teachers'),
  create: (data: any) => api.post('/teachers', data),
  get: (id: string) => api.get(`/teachers/${id}`),
  addSubject: (teacherId: string, subjectId: string) => api.post(`/teachers/${teacherId}/subjects`, { subject_id: subjectId }),
  removeSubject: (teacherId: string, subjectId: string) => api.delete(`/teachers/${teacherId}/subjects/${subjectId}`),
  delete: (id: string) => api.delete(`/teachers/${id}`),
};

export const roomsApi = {
  list: () => api.get('/rooms'),
  create: (data: any) => api.post('/rooms', data),
  get: (id: string) => api.get(`/rooms/${id}`),
  delete: (id: string) => api.delete(`/rooms/${id}`),
};

export const constraintsApi = {
  // Time Slots
  createTimeSlot: (data: any) => api.post('/constraints/time-slots', data),
  listTimeSlots: () => api.get('/constraints/time-slots'),
  deleteTimeSlot: (id: string) => api.delete(`/constraints/time-slots/${id}`),

  // Constraint Profiles
  createProfile: (data: any) => api.post('/constraints/profiles', data),
  listProfiles: () => api.get('/constraints/profiles'),
  getProfile: (id: string) => api.get(`/constraints/profiles/${id}`),
  deleteProfile: (id: string) => api.delete(`/constraints/profiles/${id}`),

  // LLM
  parseNL: (text: string) => api.post('/constraints/parse-nl', { text }),
  prototype: (text: string) => api.post('/constraints/prototype', { text }),
};

export const timetableApi = {
  generate: (data: any) => api.post('/timetable/generate', data),
  listRuns: () => api.get('/timetable/runs'),
  getRun: (id: number) => api.get(`/timetable/runs/${id}`),
  getEntries: (runId: number) => api.get(`/timetable/runs/${runId}/entries`),
  explain: (runId: number) => api.get(`/timetable/runs/${runId}/explain`),
  export: (runId: number, format: string) => api.get(`/timetable/runs/${runId}/export`, { params: { format }, responseType: 'blob' }),
};

// No-auth endpoints meant for the public college-website integration.
export const publicApi = {
  sections: (runId?: number) => api.get('/public/timetables/sections', { params: { run_id: runId } }),
  section: (sectionId: string, runId?: number) =>
    api.get(`/public/timetables/sections/${sectionId}`, { params: { run_id: runId } }),
  faculty: (runId?: number) => api.get('/public/timetables/faculty', { params: { run_id: runId } }),
  facultyMember: (teacherId: string, runId?: number) =>
    api.get(`/public/timetables/faculty/${teacherId}`, { params: { run_id: runId } }),
  rooms: (runId?: number) => api.get('/public/timetables/rooms', { params: { run_id: runId } }),
  room: (roomId: string, runId?: number) =>
    api.get(`/public/timetables/rooms/${roomId}`, { params: { run_id: runId } }),
};

export default api;
