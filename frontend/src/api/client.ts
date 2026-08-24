import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

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
};

export const subjectsApi = {
  list: () => api.get('/subjects'),
  create: (data: any) => api.post('/subjects', data),
  get: (id: string) => api.get(`/subjects/${id}`),
  delete: (id: string) => api.delete(`/subjects/${id}`),
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

export default api;