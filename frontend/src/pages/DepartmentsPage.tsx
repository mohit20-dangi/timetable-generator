import { useState } from 'react';
import { Building2, Check, Pencil, Plus, Trash2, X } from 'lucide-react';
import { departmentsApi } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useDepartment } from '../context/DepartmentContext';
import { Department } from '../types';

/**
 * Each department is solved and managed separately - its own years,
 * subjects, teachers, rooms, bell schedule and timetables. The superadmin
 * adds and removes departments; a department admin can rename their own.
 */
export function DepartmentsPage() {
  const { user } = useAuth();
  const { departments, departmentId, setDepartmentId, refresh } = useDepartment();
  const isSuperadmin = user?.role === 'SUPERADMIN';

  const [newDepartment, setNewDepartment] = useState({ id: '', name: '', code: '' });
  const [editing, setEditing] = useState<{ id: string; name: string; code: string } | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const run = async (action: () => Promise<unknown>, success: string) => {
    setError(''); setMessage('');
    try {
      await action();
      setMessage(success);
      refresh();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Something went wrong.');
    }
  };

  const createDepartment = () => {
    if (!newDepartment.id.trim() || !newDepartment.name.trim()) {
      setError('Department ID and name are required.');
      return;
    }
    run(async () => {
      await departmentsApi.create({ ...newDepartment, code: newDepartment.code || null });
      setNewDepartment({ id: '', name: '', code: '' });
    }, `${newDepartment.name} created.`);
  };

  const saveEdit = () => {
    if (!editing || !editing.name.trim()) return;
    run(async () => {
      await departmentsApi.update(editing.id, { name: editing.name, code: editing.code || null });
      setEditing(null);
    }, 'Department renamed.');
  };

  const deleteDepartment = (d: Department) => {
    if (!window.confirm(`Delete ${d.name}? This only works once nothing belongs to it any more.`)) return;
    run(() => departmentsApi.delete(d.id), `${d.name} deleted.`);
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-3xl font-bold text-gray-900"><Building2 size={28} /> Departments</h1>
        <p className="text-gray-600">
          Every department keeps its own years, subjects, teachers, rooms, bell schedule and timetables, and
          its admins and HODs only ever see their own.
        </p>
      </div>

      {error && <div className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</div>}
      {message && <div className="mb-4 rounded-lg bg-green-50 border border-green-200 p-3 text-sm text-green-700">{message}</div>}

      <div className="bg-white rounded-lg border border-gray-200 mb-6 overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-200">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Code</th>
              <th className="px-4 py-3">ID</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {departments.map((d) => {
              const isEditing = editing?.id === d.id;
              return (
                <tr key={d.id} className={`border-b border-gray-100 ${d.id === departmentId ? 'bg-blue-50/50' : ''}`}>
                  <td className="px-4 py-3 font-medium">
                    {isEditing ? (
                      <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                        className="w-full rounded border border-gray-300 px-2 py-1" />
                    ) : d.name}
                    {d.id === departmentId && !isEditing && <span className="ml-2 text-xs text-blue-700">(working in)</span>}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {isEditing ? (
                      <input value={editing.code} onChange={(e) => setEditing({ ...editing, code: e.target.value })}
                        className="w-24 rounded border border-gray-300 px-2 py-1" />
                    ) : d.code || '—'}
                  </td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">{d.id}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-3 text-gray-600">
                      {isEditing ? (
                        <>
                          <button onClick={saveEdit} className="flex items-center gap-1 hover:text-green-700"><Check size={16} /> Save</button>
                          <button onClick={() => setEditing(null)} className="flex items-center gap-1 hover:text-gray-900"><X size={16} /> Cancel</button>
                        </>
                      ) : (
                        <>
                          {isSuperadmin && d.id !== departmentId && (
                            <button
                              onClick={() => { setDepartmentId(d.id); window.location.reload(); }}
                              className="hover:text-blue-700"
                            >
                              Switch to
                            </button>
                          )}
                          <button onClick={() => setEditing({ id: d.id, name: d.name, code: d.code || '' })}
                            className="flex items-center gap-1 hover:text-gray-900"><Pencil size={14} /> Rename</button>
                          {isSuperadmin && (
                            <button onClick={() => deleteDepartment(d)} className="flex items-center gap-1 hover:text-red-700">
                              <Trash2 size={14} /> Delete
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {departments.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-gray-500">No departments yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {isSuperadmin && (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-1">Add a department</h2>
          <p className="text-sm text-gray-600 mb-3">
            Then create its department admin under Settings → Users &amp; roles.
          </p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <input placeholder="ID (e.g. ece)" value={newDepartment.id} onChange={(e) => setNewDepartment({ ...newDepartment, id: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
            <input placeholder="Name (e.g. Electronics)" value={newDepartment.name} onChange={(e) => setNewDepartment({ ...newDepartment, name: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
            <input placeholder="Code (optional, e.g. ECE)" value={newDepartment.code} onChange={(e) => setNewDepartment({ ...newDepartment, code: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          </div>
          <button onClick={createDepartment} className="mt-3 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
            <Plus size={16} /> Add department
          </button>
        </div>
      )}
    </div>
  );
}
