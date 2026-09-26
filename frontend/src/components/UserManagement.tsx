import { useState, useEffect } from 'react';
import { authApi, departmentsApi, teachersApi, sectionsApi } from '../api/client';
import { Plus, UserPlus, ShieldCheck, ShieldOff } from 'lucide-react';

interface AccountUser {
  id: number;
  email: string;
  full_name: string;
  role: 'ADMIN' | 'HOD' | 'FACULTY' | 'STUDENT';
  department_id: string | null;
  teacher_id: string | null;
  section_id: string | null;
  is_active: boolean;
}

const ROLE_LABELS: Record<AccountUser['role'], string> = {
  ADMIN: 'Admin - full access',
  HOD: 'HOD - edit own department\'s timetable',
  FACULTY: 'Faculty - view own teaching schedule',
  STUDENT: 'Student - view own class schedule',
};

/**
 * Roles govern what a signed-in account can see and change:
 * ADMIN edits everything, HOD edits only their own department's
 * timetable, FACULTY/STUDENT can only view their own schedule
 * (enforced server-side in every /api/timetable route, not just here).
 */
export function UserManagement() {
  const [users, setUsers] = useState<AccountUser[]>([]);
  const [departments, setDepartments] = useState<{ id: string; name: string }[]>([]);
  const [teachers, setTeachers] = useState<{ id: string; name: string }[]>([]);
  const [sections, setSections] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const [form, setForm] = useState({
    email: '', password: '', full_name: '', role: 'HOD' as AccountUser['role'],
    department_id: '', teacher_id: '', section_id: '',
  });

  const refresh = async () => {
    const res = await authApi.listUsers();
    setUsers(res.data);
  };

  useEffect(() => {
    refresh();
    departmentsApi.list().then((res) => setDepartments(res.data)).catch(() => undefined);
    teachersApi.list().then((res) => setTeachers(res.data)).catch(() => undefined);
    sectionsApi.list().then((res) => setSections(res.data)).catch(() => undefined);
  }, []);

  const createUser = async () => {
    setError(''); setMessage('');
    if (!form.email || !form.password || !form.full_name) {
      setError('Email, password, and name are required.');
      return;
    }
    try {
      await authApi.register({
        email: form.email,
        password: form.password,
        full_name: form.full_name,
        role: form.role,
        department_id: form.role === 'HOD' ? form.department_id : undefined,
        teacher_id: form.role === 'FACULTY' ? form.teacher_id : undefined,
        section_id: form.role === 'STUDENT' ? form.section_id : undefined,
      });
      setMessage(`${form.full_name} added as ${form.role}.`);
      setForm({ email: '', password: '', full_name: '', role: form.role, department_id: '', teacher_id: '', section_id: '' });
      refresh();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not create the account.');
    }
  };

  const toggleActive = async (u: AccountUser) => {
    setError('');
    try {
      await authApi.setUserActive(u.id, !u.is_active);
      refresh();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not update this account.');
    }
  };

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && <div className="rounded-lg bg-green-50 p-3 text-sm text-green-700">{message}</div>}

      <div>
        <h3 className="flex items-center gap-2 text-lg font-semibold text-gray-900"><UserPlus size={20} /> Add an account</h3>
        <p className="text-sm text-gray-600 mb-3">
          Give a teacher, department coordinator, or student login access - and control exactly what
          they can see or change once signed in.
        </p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <input placeholder="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <input placeholder="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <input placeholder="Temporary password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as AccountUser['role'] })} className="rounded-lg border border-gray-300 px-3 py-2">
            {(Object.keys(ROLE_LABELS) as AccountUser['role'][]).map((r) => (
              <option key={r} value={r}>{ROLE_LABELS[r]}</option>
            ))}
          </select>

          {form.role === 'HOD' && (
            <select value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2 md:col-span-2">
              <option value="">Select the department they coordinate</option>
              {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          )}
          {form.role === 'FACULTY' && (
            <select value={form.teacher_id} onChange={(e) => setForm({ ...form, teacher_id: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2 md:col-span-2">
              <option value="">Link to their teacher record</option>
              {teachers.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          )}
          {form.role === 'STUDENT' && (
            <select value={form.section_id} onChange={(e) => setForm({ ...form, section_id: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2 md:col-span-2">
              <option value="">Link to their section</option>
              {sections.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
        </div>
        <button onClick={createUser} className="mt-3 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
          <Plus size={16} /> Create account
        </button>
      </div>

      <div className="border-t pt-5">
        <h3 className="text-lg font-semibold text-gray-900 mb-3">Accounts</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-200">
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Email</th>
                <th className="py-2 pr-4">Role</th>
                <th className="py-2 pr-4">Scope</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-gray-100">
                  <td className="py-2 pr-4 font-medium">{u.full_name}</td>
                  <td className="py-2 pr-4 text-gray-600">{u.email}</td>
                  <td className="py-2 pr-4">{u.role}</td>
                  <td className="py-2 pr-4 text-gray-600">{u.department_id || u.teacher_id || u.section_id || '—'}</td>
                  <td className="py-2 pr-4">
                    <span className={u.is_active ? 'text-green-700' : 'text-gray-400'}>
                      {u.is_active ? 'Active' : 'Deactivated'}
                    </span>
                  </td>
                  <td className="py-2">
                    <button
                      onClick={() => toggleActive(u)}
                      className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900"
                      title={u.is_active ? 'Revoke access' : 'Restore access'}
                    >
                      {u.is_active ? <ShieldOff size={14} /> : <ShieldCheck size={14} />}
                      {u.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
