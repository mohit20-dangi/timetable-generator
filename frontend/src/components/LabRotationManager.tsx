import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { constraintsApi, labRotationsApi, sectionsApi, subjectsApi } from '../api/client';
import { LabBatch, LabRotationGroup, LabRotationPreflightResult, Section, Subject } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import {
  Plus, Trash2, AlertTriangle, CheckCircle2, Edit, Save, X, Users, DoorOpen, RefreshCw,
} from 'lucide-react';

/**
 * Lab rotations: several lab subjects one section runs at the same time
 * with a DIFFERENT batch in each, swapping round by round.
 *
 * This exists because "run the labs together" used to have only one
 * possible meaning in the app - batch scheduling mode "parallel", i.e.
 * every batch in the SAME lab at once, which needs one qualified teacher
 * per batch and produced a blocking "3 batches, only 2 teachers" for most
 * real departments. A rotation needs one teacher per LAB instead, which is
 * what colleges actually staff for. The preview below spells the swap out
 * batch by batch so it's obvious which of the two arrangements is being
 * set up.
 */
export function LabRotationManager() {
  const { departmentId } = useDepartment();
  const [rotations, setRotations] = useState<LabRotationGroup[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [batches, setBatches] = useState<LabBatch[]>([]);
  const emptyForm = () => ({
    id: '', name: '', sectionId: '', subjectIds: [] as string[],
    day: '', startTime: '', endTime: '',
  });
  const [form, setForm] = useState(emptyForm());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<Record<string, LabRotationPreflightResult>>({});
  const [error, setError] = useState('');

  const fetchAll = async () => {
    const [rotationsRes, sectionsRes, subjectsRes, batchesRes] = await Promise.all([
      labRotationsApi.list(), sectionsApi.list(), subjectsApi.list(), constraintsApi.getAllLabBatches(),
    ]);
    setRotations(rotationsRes.data);
    setSections(sectionsRes.data);
    setSubjects(subjectsRes.data);
    setBatches(batchesRes.data);
  };

  useEffect(() => { fetchAll(); }, []);

  const labSubjects = subjects.filter((s) => s.type === 'lab');
  const batchesOf = (sectionId: string) => batches.filter((b) => b.section_id === sectionId);
  const subjectName = (id: string) => subjects.find((s) => s.id === id)?.name || id;
  const sectionName = (id: string) => sections.find((s) => s.id === id)?.name || id;

  const runPreflight = async (rotationId: string) => {
    const response = await labRotationsApi.preflight(rotationId);
    setPreflight((prev) => ({ ...prev, [rotationId]: response.data }));
  };

  const startEdit = (rotation: LabRotationGroup) => {
    setEditingId(rotation.id);
    setForm({
      id: rotation.id, name: rotation.name, sectionId: rotation.section_id,
      subjectIds: rotation.subject_ids,
      day: rotation.day || '', startTime: rotation.start_time || '', endTime: rotation.end_time || '',
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(emptyForm());
    setError('');
  };

  const saveRotation = async () => {
    setError('');
    if (!form.id || !form.name || !form.sectionId || !departmentId) {
      setError('Fill in an ID and name, pick a section, and select a department first.');
      return;
    }
    if (form.subjectIds.length < 2) {
      setError('Pick at least two labs - a rotation needs something to swap between.');
      return;
    }
    const pinned = [form.day, form.startTime, form.endTime];
    if (pinned.some(Boolean) && !pinned.every(Boolean)) {
      setError('To pin the rotation, set the day, start time and end time - or leave all three blank.');
      return;
    }
    const payload = {
      id: editingId || form.id, department_id: departmentId, name: form.name,
      section_id: form.sectionId, subject_ids: form.subjectIds,
      day: form.day || null,
      start_time: form.startTime || null,
      end_time: form.endTime || null,
      is_active: true,
    };
    try {
      if (editingId) await labRotationsApi.update(editingId, payload);
      else await labRotationsApi.create(payload);
      cancelEdit();
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not save this lab rotation.');
    }
  };

  const deleteRotation = async (id: string) => {
    await labRotationsApi.delete(id);
    if (editingId === id) cancelEdit();
    fetchAll();
  };

  const toggleSubject = (subjectId: string) => {
    setForm((prev) => ({
      ...prev,
      subjectIds: prev.subjectIds.includes(subjectId)
        ? prev.subjectIds.filter((s) => s !== subjectId)
        : [...prev.subjectIds, subjectId],
    }));
  };

  // The round-by-round swap, spelled out. Round r puts batch i into the
  // lab (i + r) mod n - the same Latin square the solver fills in, shown
  // here so the admin can see "A1 does CN, A2 does DBMS, A3 does OOPS,
  // then they swap" rather than having to trust the word "rotation".
  const previewRounds = (sectionId: string, subjectIds: string[]) => {
    const sectionBatches = batchesOf(sectionId);
    if (sectionBatches.length < 2 || subjectIds.length < 2) return [];
    return subjectIds.map((_, round) =>
      sectionBatches.map((batch, i) => ({
        batch: batch.batch_name,
        subject: subjectName(subjectIds[(i + round) % subjectIds.length]),
      })),
    );
  };

  const formSectionBatches = batchesOf(form.sectionId);
  const formPreview = previewRounds(form.sectionId, form.subjectIds);
  const sectionLabSubjects = form.sectionId ? labSubjects : [];

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-600">
        A lab rotation runs several labs of one section <strong>at the same time, with a different
        batch in each</strong> - A1 in one lab, A2 in another, A3 in a third - then swaps them round
        until every batch has done every lab. Because each lab only ever runs with one batch at a
        time, it needs <strong>one qualified teacher per lab</strong>, not one per batch. That's the
        difference from setting a lab's batch mode to "parallel", which puts every batch in the same
        lab at once and needs a teacher for each of them.
      </p>
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      <div className="rounded-lg border border-gray-200 p-4">
        <h4 className="font-medium text-gray-900 mb-3">
          {editingId ? `Editing ${editingId}` : 'New lab rotation'}
        </h4>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3 mb-3">
          <input
            placeholder="ID (e.g. rot_sec3a)" value={form.id} disabled={!!editingId}
            onChange={(e) => setForm({ ...form, id: e.target.value })}
            className="rounded-lg border border-gray-300 px-3 py-2 disabled:bg-gray-100"
          />
          <input
            placeholder="Name (e.g. 3rd year A labs)" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="rounded-lg border border-gray-300 px-3 py-2"
          />
          <select
            value={form.sectionId}
            onChange={(e) => setForm({ ...form, sectionId: e.target.value, subjectIds: [] })}
            className="rounded-lg border border-gray-300 px-3 py-2"
          >
            <option value="">Select a section…</option>
            {sections.map((section) => (
              <option key={section.id} value={section.id}>{section.name}</option>
            ))}
          </select>
        </div>

        {form.sectionId && (
          <p className="mb-3 flex items-center gap-1.5 text-sm text-gray-500">
            <Users size={14} />
            {formSectionBatches.length === 0
              ? 'This section has no lab batches yet - add them before a rotation can do anything.'
              : `${formSectionBatches.length} batch(es): ${formSectionBatches.map((b) => b.batch_name).join(', ')}`}
          </p>
        )}

        <label className="block text-sm font-medium text-gray-700 mb-2">
          Which labs rotate? (pick at least two)
        </label>
        <div className="mb-3 flex flex-wrap gap-2">
          {sectionLabSubjects.map((subject) => (
            <button
              key={subject.id} type="button" onClick={() => toggleSubject(subject.id)}
              className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                form.subjectIds.includes(subject.id)
                  ? 'border-blue-600 bg-blue-600 text-white'
                  : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              {subject.name}
            </button>
          ))}
          {!form.sectionId && <p className="text-sm text-gray-400">Pick a section first.</p>}
          {form.sectionId && sectionLabSubjects.length === 0 && (
            <p className="text-sm text-gray-400">No lab subjects configured yet.</p>
          )}
        </div>

        <div className="mb-3">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Pin it to a time? <span className="font-normal text-gray-500">(optional - leave blank to let the generator place the rounds)</span>
          </label>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <select
              value={form.day} onChange={(e) => setForm({ ...form, day: e.target.value })}
              className="rounded-lg border border-gray-300 px-3 py-2"
            >
              <option value="">Any day</option>
              {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day) => (
                <option key={day} value={day}>{day}</option>
              ))}
            </select>
            <input
              type="time" value={form.startTime}
              onChange={(e) => setForm({ ...form, startTime: e.target.value })}
              className="rounded-lg border border-gray-300 px-3 py-2"
            />
            <input
              type="time" value={form.endTime}
              onChange={(e) => setForm({ ...form, endTime: e.target.value })}
              className="rounded-lg border border-gray-300 px-3 py-2"
            />
          </div>
        </div>

        {formPreview.length > 0 && (
          <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
            <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-blue-900">
              <RefreshCw size={14} /> How the batches will swap
            </p>
            <div className="space-y-1 text-sm text-blue-900">
              {formPreview.map((round, i) => (
                <p key={i}>
                  <span className="font-medium">Round {i + 1}:</span>{' '}
                  {round.map((cell) => `${cell.batch} → ${cell.subject}`).join(' · ')}
                </p>
              ))}
            </div>
            <p className="mt-2 text-xs text-blue-700">
              The generator decides the actual pairing and times; this shows the shape of the swap.
            </p>
          </div>
        )}

        <div className="flex gap-2">
          <button onClick={saveRotation} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
            {editingId ? <Save size={16} /> : <Plus size={16} />} {editingId ? 'Save changes' : 'Create lab rotation'}
          </button>
          {editingId && (
            <button onClick={cancelEdit} className="flex items-center gap-2 rounded-lg bg-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-300">
              <X size={16} /> Cancel
            </button>
          )}
        </div>
      </div>

      <div className="space-y-3">
        {rotations.map((rotation) => {
          const result = preflight[rotation.id];
          return (
            <div key={rotation.id} className="rounded-lg border border-gray-200 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-900">{rotation.name}</p>
                  <p className="text-sm text-gray-500">
                    {sectionName(rotation.section_id)} ·{' '}
                    {rotation.subject_ids.map(subjectName).join(', ')}
                    {rotation.day && ` · ${rotation.day} ${rotation.start_time}-${rotation.end_time}`}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => runPreflight(rotation.id)} className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">
                    Check feasibility
                  </button>
                  <button onClick={() => startEdit(rotation)} className="p-1.5 text-blue-600 hover:bg-blue-50 rounded">
                    <Edit size={16} />
                  </button>
                  <button onClick={() => deleteRotation(rotation.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded">
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
              {result && (
                <div className={`mt-3 rounded-lg border p-3 text-sm ${
                  result.feasible
                    ? 'border-green-200 bg-green-50 text-green-800'
                    : 'border-amber-200 bg-amber-50 text-amber-900'
                }`}>
                  <div className="flex items-center gap-2 font-medium">
                    {result.feasible ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                    {result.feasible
                      ? 'This rotation can be scheduled.'
                      : "This rotation won't fit as it stands."}
                  </div>
                  <p className="mt-1">
                    {result.batch_count} batch(es), {result.round_count} lab session(s) a week to
                    rotate through.
                  </p>
                  {result.issues.map((issue, i) => <p key={i} className="mt-1">{issue.message}</p>)}
                  {!result.feasible && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => { startEdit(rotation); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
                        className="flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-900 hover:bg-amber-100"
                      >
                        <Edit size={14} /> Change which labs rotate
                      </button>
                      <Link
                        to="/setup/lab-batches"
                        className="flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-900 hover:bg-amber-100"
                      >
                        <Users size={14} /> Edit lab batches
                      </Link>
                      <Link
                        to="/setup/rooms"
                        className="flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm text-amber-900 hover:bg-amber-100"
                      >
                        <DoorOpen size={14} /> Add a room
                      </Link>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {rotations.length === 0 && (
          <p className="text-center text-gray-500 py-4">No lab rotations yet.</p>
        )}
      </div>
    </div>
  );
}
