import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { electiveGroupsApi, subjectsApi } from '../api/client';
import { ElectiveGroup, ElectivePreflightResult, Subject } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Trash2, AlertTriangle, CheckCircle2, Edit, Save, X, DoorOpen, Clock } from 'lucide-react';

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
  const emptyForm = () => ({ id: '', name: '', offered: [] as string[], mustBeParallel: true });
  const [form, setForm] = useState(emptyForm());
  const [editingId, setEditingId] = useState<string | null>(null);
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

  const startEdit = (group: ElectiveGroup) => {
    setEditingId(group.id);
    setForm({ id: group.id, name: group.name, offered: group.offered_subject_ids, mustBeParallel: group.must_be_parallel });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(emptyForm());
    setError('');
  };

  const saveGroup = async () => {
    setError('');
    if (!form.id || !form.name || !departmentId) { setError('Fill in an ID and name, and select a department first.'); return; }
    try {
      if (editingId) {
        await electiveGroupsApi.update(editingId, {
          id: editingId, department_id: departmentId, name: form.name,
          offered_subject_ids: form.offered, must_be_parallel: form.mustBeParallel,
        });
      } else {
        await electiveGroupsApi.create({
          id: form.id, department_id: departmentId, name: form.name,
          offered_subject_ids: form.offered, must_be_parallel: form.mustBeParallel,
        });
      }
      cancelEdit();
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not save elective group.');
    }
  };

  const deleteGroup = async (id: string) => {
    await electiveGroupsApi.delete(id);
    if (editingId === id) cancelEdit();
    fetchAll();
  };

  const toggleOffered = (subjectId: string) => {
    setForm((prev) => ({
      ...prev,
      offered: prev.offered.includes(subjectId) ? prev.offered.filter((s) => s !== subjectId) : [...prev.offered, subjectId],
    }));
  };

  const selectAllOffered = () => setForm((prev) => ({ ...prev, offered: subjects.map((s) => s.id) }));
  const clearAllOffered = () => setForm((prev) => ({ ...prev, offered: [] }));

  const offerFewerOptions = (group: ElectiveGroup) => {
    startEdit(group);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const runAtDifferentTimes = async (group: ElectiveGroup) => {
    if (!departmentId) return;
    await electiveGroupsApi.update(group.id, {
      id: group.id, department_id: departmentId, name: group.name,
      offered_subject_ids: group.offered_subject_ids, must_be_parallel: false,
    });
    await fetchAll();
    runPreflight(group.id);
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
        <h4 className="font-medium text-gray-900 mb-3">{editingId ? `Editing ${editingId}` : 'New elective group'}</h4>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 mb-3">
          <input placeholder="ID (e.g. elective1)" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} disabled={!!editingId} className="rounded-lg border border-gray-300 px-3 py-2 disabled:bg-gray-100" />
          <input placeholder="Name (e.g. Elective-1)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
        </div>
        <div className="mb-2 flex items-center justify-between">
          <label className="block text-sm font-medium text-gray-700">Which options are offered this term?</label>
          {subjects.length > 0 && (
            <div className="flex gap-3">
              <button type="button" onClick={selectAllOffered} className="text-xs text-blue-600 hover:text-blue-800">
                Select all
              </button>
              <button type="button" onClick={clearAllOffered} className="text-xs text-gray-500 hover:text-gray-700">
                Clear all
              </button>
            </div>
          )}
        </div>
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
        <label className="mb-3 flex items-start gap-2 text-sm text-gray-700">
          <input
            type="checkbox" checked={form.mustBeParallel}
            onChange={(e) => setForm({ ...form, mustBeParallel: e.target.checked })}
            className="mt-0.5 w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
          />
          <span>
            All offered options must run at the same time
            <span className="block text-xs text-gray-500">Turn this off if the options can run at different times instead - fewer rooms/teachers are needed at once.</span>
          </span>
        </label>
        <div className="flex gap-2">
          <button onClick={saveGroup} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
            {editingId ? <Save size={16} /> : <Plus size={16} />} {editingId ? 'Save changes' : 'Create elective group'}
          </button>
          {editingId && (
            <button onClick={cancelEdit} className="flex items-center gap-2 rounded-lg bg-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-300">
              <X size={16} /> Cancel
            </button>
          )}
        </div>
      </div>

      <div className="space-y-3">
        {groups.map((group) => {
          const result = preflight[group.id];
          return (
            <div key={group.id} className="rounded-lg border border-gray-200 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-900">{group.name}</p>
                  <p className="text-sm text-gray-500">
                    {group.offered_subject_ids.length} option(s) offered · {group.must_be_parallel ? 'run at the same time' : 'may run at different times'}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => runPreflight(group.id)} className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">
                    Check feasibility
                  </button>
                  <button onClick={() => startEdit(group)} className="p-1.5 text-blue-600 hover:bg-blue-50 rounded">
                    <Edit size={16} />
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
                    {result.feasible ? 'This basket can be scheduled in parallel.' : 'There aren\'t enough rooms or teachers to run these together.'}
                  </div>
                  <p className="mt-1">
                    {result.offered_count} offered, {result.rooms_available_in_common_slot} suitable rooms,{' '}
                    {result.qualified_teachers} qualified teachers.
                  </p>
                  {result.issues.map((issue, i) => <p key={i} className="mt-1">{issue.message}</p>)}
                  {!result.feasible && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button" onClick={() => offerFewerOptions(group)}
                        className="flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-900 hover:bg-amber-100"
                      >
                        <Edit size={14} /> Offer fewer options
                      </button>
                      <Link
                        to="/setup/rooms"
                        className="flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-900 hover:bg-amber-100"
                      >
                        <DoorOpen size={14} /> Add a room
                      </Link>
                      <button
                        type="button" onClick={() => runAtDifferentTimes(group)}
                        className="flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-900 hover:bg-amber-100"
                      >
                        <Clock size={14} /> Let them run at different times
                      </button>
                    </div>
                  )}
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
