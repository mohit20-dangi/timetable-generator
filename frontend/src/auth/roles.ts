// Mirrors backend/app/auth/dependencies.py - the server enforces every one
// of these rules; the UI only uses them to decide what to show.
export type Role = 'SUPERADMIN' | 'DEPT_ADMIN' | 'HOD' | 'TEACHER';

export const ROLE_LABELS: Record<Role, string> = {
  SUPERADMIN: 'Superadmin',
  DEPT_ADMIN: 'Department admin',
  HOD: 'HOD',
  TEACHER: 'Teacher',
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  SUPERADMIN: 'Every department - for the developer/operator',
  DEPT_ADMIN: 'Full control of one department: setup, users and timetables',
  HOD: "Generates, edits and publishes one department's timetables",
  TEACHER: 'Views their own published teaching schedule',
};

/** Roles that may change setup data (subjects, teachers, rooms, users...). */
export const ADMIN_ROLES: Role[] = ['SUPERADMIN', 'DEPT_ADMIN'];
/** Roles that may generate, edit and publish timetables. */
export const TIMETABLE_ROLES: Role[] = ['SUPERADMIN', 'DEPT_ADMIN', 'HOD'];

/** Which roles each role may create accounts for. */
export const GRANTABLE_ROLES: Record<Role, Role[]> = {
  SUPERADMIN: ['SUPERADMIN', 'DEPT_ADMIN', 'HOD', 'TEACHER'],
  DEPT_ADMIN: ['HOD', 'TEACHER'],
  HOD: [],
  TEACHER: [],
};

export const isAdmin = (role?: Role | null) => !!role && ADMIN_ROLES.includes(role);
export const canManageTimetables = (role?: Role | null) => !!role && TIMETABLE_ROLES.includes(role);
