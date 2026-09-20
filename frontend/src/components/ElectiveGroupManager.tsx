import { useState, useEffect } from 'react';
import { electiveGroupsApi, subjectsApi } from '../api/client';
import { ElectiveGroup, ElectivePreflightResult, Subject } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Trash2, AlertTriangle, CheckCircle2 } from 'lucide-react';

/**
 * A basket (e.g. "Elective-1: 8 options") vs. what's actually OFFERED
 * this term - the offered subset is what gets co-scheduled into one
 * common slot. The preflight check answers the question raised during
 * planning: "what if I don't have N rooms and N teachers?" - it tells the
 * admin BEFORE generation whether the offered set is actually feasible,
 * naming exactly what's short.
 */
export function ElectiveGroupManager() {
  const { departmentId } = useDepartment();
  const [groups, setGroups] = useState<ElectiveGroup[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [form, setForm] = useState({ id: '', name: '', offered: [] as string[], mustBeParallel: true });
  const [preflight, setPreflight] = useState<Record<string, ElectivePreflightResult>>({});
  const [error, setError] = useState('');

  const fetchAll = async () => {
    const [groupsRes, subjectsRes] = await Promise.all([electiveGroupsApi.list(), subjectsApi.list()]);
    setGroups(groupsRes.data);
    setSubjects(subjectsRes.data);
  };

  useEffect(() => { fetchAll(); }, []);

  const runPreflight = async (groupId: string) => {
    const response = await electiveGroupsApi.preflight(groupId);
    setPreflight((prev) => ({ ...prev, [groupId]: response.data }));
  };

  const createGroup = async () => {
    setError('');
    if (!form.id || !form.name || !departmentId) { setError('Fill in an ID and name, and select a department first.'); return; }
    try {
      await electiveGroupsApi.create({
        id: form.id, department_id: departmentId, name: form.name,
        offered_subject_ids: form.offered, must_be_parallel: form.mustBeParallel,
      });
      setForm({ id: '', name: '', offered: [], mustBeParallel: true });
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not create elective group.');
    }
  };

  const deleteGroup = async (id: string) => {
    await electiveGroupsApi.delete(id);
    fetchAll();
  };

  const toggleOffered = (subjectId: string) => {
    setForm((prev) => ({
      ...prev,
      offered: prev.offered.includes(subjectId) ? prev.offered.filter((s) => s !== subjectId) : [...prev.offered, subjectId],
    }));
  };

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-600">
        A basket like "Elective-1" might list 8 options on the curriculum, but a college usually only
        runs a few of them in a given term. Mark which ones are actually offered below - only those get
        scheduled into a shared timeslot, and the preflight check tells you if you have enough rooms and
        teachers to run them all in parallel before you generate anything.
      </p>
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      <div className="rounded-lg border border-gray-200 p-4">
        <h4 className="font-medium text-gray-900 mb-3">New elective group</h4>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 mb-3">
          <input placeholder="ID (e.g. elective1)" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <input placeholder="Name (e.g. Elective-1)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
        </div>
        <label className="mb-2 block text-sm font-medium text-gray-700">Which options are offered this term?</label>
        <div className="mb-3 flex flex-wrap gap-2">
          {subjects.map((subject) => (
            <button
              key={subject.id} type="button" onClick={() => toggleOffered(subject.id)}
              className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                form.offered.includes(subject.id) ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              {subject.name}
            </button>
          ))}
          {subjects.length === 0 && <p className="text-sm text-gray-400">Add subjects first.</p>}
        </div>
        <button onClick={createGroup} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
          <Plus size={16} /> Create elective group
        </button>
      </div>

      <div className="space-y-3">
        {groups.map((group) => {
          const result = preflight[group.id];
          return (
            <div key={group.id} className="rounded-lg border border-gray-200 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-900">{group.name}</p>
                  <p className="text-sm text-gray-500">{group.offered_subject_ids.length} option(s) offered</p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => runPreflight(group.id)} className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">
                    Check feasibility
                  </button>
                  <button onClick={() => deleteGroup(group.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded">
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
              {result && (
                <div className={`mt-3 rounded-lg border p-3 text-sm ${result.feasible ? 'border-green-200 bg-green-50 text-green-800' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
                  <div className="flex items-center gap-2 font-medium">
                    {result.feasible ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                    {result.feasible ? 'This basket can be scheduled in parallel.' : 'This basket may not fit as configured.'}
                  </div>
                  <p className="mt-1">
                    {result.offered_count} offered, {result.rooms_available_in_common_slot} suitable rooms,{' '}
                    {result.qualified_teachers} qualified teachers.
                  </p>
                  {result.issues.map((issue, i) => <p key={i} className="mt-1">{issue.message}</p>)}
                </div>
              )}
            </div>
          );
        })}
        {groups.length === 0 && <p className="text-center text-gray-500 py-4">No elective groups yet.</p>}
      </div>
    </div>
  );
}
