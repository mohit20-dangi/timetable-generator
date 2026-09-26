import { useState, useEffect } from 'react';
import { institutionsApi, departmentsApi } from '../api/client';
import { Institution } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Building2, GraduationCap } from 'lucide-react';

/**
 * A default institution and department are provisioned automatically, so
 * most colleges never need this page. It only matters once a college adds
 * a second department - departments are solved independently (see the
 * Department model docstring on the backend for why), so this is where
 * that becomes visible and configurable.
 */
export function DepartmentSetup() {
  const { departments, departmentId, setDepartmentId, refresh } = useDepartment();
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [institutionId, setInstitutionId] = useState('');

  const [newInstitution, setNewInstitution] = useState({ id: '', name: '', city: '' });
  const [newDepartment, setNewDepartment] = useState({ id: '', name: '', code: '' });
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const fetchInstitutions = async () => {
    const response = await institutionsApi.list();
    setInstitutions(response.data);
    if (response.data.length && !institutionId) setInstitutionId(response.data[0].id);
  };

  useEffect(() => { fetchInstitutions(); }, []);

  const createInstitution = async () => {
    setError(''); setMessage('');
    if (!newInstitution.id || !newInstitution.name) { setError('Institution ID and name are required.'); return; }
    try {
      await institutionsApi.create(newInstitution);
      setMessage('Institution created.');
      setNewInstitution({ id: '', name: '', city: '' });
      fetchInstitutions();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not create institution.');
    }
  };

  const createDepartment = async () => {
    setError(''); setMessage('');
    if (!institutionId) { setError('Create or select an institution first.'); return; }
    if (!newDepartment.id || !newDepartment.name) { setError('Department ID and name are required.'); return; }
    try {
      await departmentsApi.create({ ...newDepartment, institution_id: institutionId });
      setMessage('Department created.');
      setNewDepartment({ id: '', name: '', code: '' });
      refresh();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not create department.');
    }
  };

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && <div className="rounded-lg bg-green-50 p-3 text-sm text-green-700">{message}</div>}

      <div>
        <h3 className="flex items-center gap-2 text-lg font-semibold text-gray-900"><Building2 size={20} /> Institution</h3>
        <p className="text-sm text-gray-600 mb-3">The college or university this system is configured for.</p>
        {institutions.length > 0 && (
          <select
            value={institutionId} onChange={(e) => setInstitutionId(e.target.value)}
            className="mb-3 w-full rounded-lg border border-gray-300 px-3 py-2"
          >
            {institutions.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <input placeholder="ID (e.g. demo_college)" value={newInstitution.id} onChange={(e) => setNewInstitution({ ...newInstitution, id: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <input placeholder="Name" value={newInstitution.name} onChange={(e) => setNewInstitution({ ...newInstitution, name: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <input placeholder="City (optional)" value={newInstitution.city} onChange={(e) => setNewInstitution({ ...newInstitution, city: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
        </div>
        <button onClick={createInstitution} className="mt-2 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
          <Plus size={16} /> Add institution
        </button>
      </div>

      <div className="border-t pt-5">
        <h3 className="flex items-center gap-2 text-lg font-semibold text-gray-900"><GraduationCap size={20} /> Department</h3>
        <p className="text-sm text-gray-600 mb-3">
          The solver always generates one department's timetable at a time - separate departments have
          separate students, faculty and rooms. Everything else in this wizard applies to the department
          selected here.
        </p>
        {departments.length > 0 && (
          <select
            value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}
            className="mb-3 w-full rounded-lg border border-gray-300 px-3 py-2 font-medium"
          >
            {departments.map((d) => <option key={d.id} value={d.id}>{d.name}{d.code ? ` (${d.code})` : ''}</option>)}
          </select>
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <input placeholder="ID (e.g. cse)" value={newDepartment.id} onChange={(e) => setNewDepartment({ ...newDepartment, id: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <input placeholder="Name (e.g. Computer Science)" value={newDepartment.name} onChange={(e) => setNewDepartment({ ...newDepartment, name: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <input placeholder="Code (optional, e.g. CSE)" value={newDepartment.code} onChange={(e) => setNewDepartment({ ...newDepartment, code: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
        </div>
        <button onClick={createDepartment} className="mt-2 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
          <Plus size={16} /> Add department
        </button>
      </div>

      {departmentId && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
          Working in: <span className="font-semibold">{departments.find((d) => d.id === departmentId)?.name || departmentId}</span>
        </div>
      )}
    </div>
  );
}
