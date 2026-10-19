import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, Pencil, Play, Plus, Trash2, UploadCloud } from 'lucide-react';
import { remedialApi, sectionsApi, subjectsApi, teachersApi, constraintsApi } from '../api/client';
import { useDepartment } from '../context/DepartmentContext';
import { DAYS, DAY_LABELS, formatTime } from '../utils/schedule';
import {
  RemedialGroup, RemedialRun, RemedialSectionView, RemedialSettings, Section, Subject, Teacher,
} from '../types';

// Mirrors RemedialSettings in backend/app/schemas/remedial.py (the server
// validates and applies its own defaults too).
const DEFAULT_SETTINGS: RemedialSettings = {
  preferred_max_per_day: 1,
  hard_max_per_day: 2,
  use_free_regular_slots: true,
  teacher_max_remedial_per_day: 2,
  teacher_max_remedial_per_week: 6,
  weight_mid_day_gap: 10,
  weight_non_regular_teacher: 8,
  weight_over_preferred_per_day: 20,
  max_seconds: 60,
};

interface GroupForm {
  id: string;
  name: string;
  subject_id: string;
  section_ids: string[];
  strength: number;
  periods_per_week: number;
  periods_per_session: number;
  teacher_id: string;
  allowed_days: string[];
}

const EMPTY_FORM: GroupForm = {
  id: '', name: '', subject_id: '', section_ids: [], strength: 20, periods_per_week: 2,
  periods_per_session: 1, teacher_id: '', allowed_days: [],
};

const errorText = (err: any, fallback: string) => {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ');
  return fallback;
};

/** Remedial classes for low-attendance students. The admin describes what
 * needs remedial teaching (groups); the generator fits those classes around
 * the published main timetable, which it never changes. */
export function RemedialPlanner() {
  const { departmentId } = useDepartment();
  const [groups, setGroups] = useState<RemedialGroup[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [remedialSlotCount, setRemedialSlotCount] = useState(0);
  const [runs, setRuns] = useState<RemedialRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [view, setView] = useState<RemedialSectionView | null>(null);
  const [settings, setSettings] = useState<RemedialSettings>(DEFAULT_SETTINGS);
  const [form, setForm] = useState<GroupForm | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  const subjectName = useMemo(() => Object.fromEntries(subjects.map((s) => [s.id, s.name])), [subjects]);
  const teacherName = useMemo(() => Object.fromEntries(teachers.map((t) => [t.id, t.name])), [teachers]);
  const sectionName = useMemo(() => Object.fromEntries(sections.map((s) => [s.id, s.name])), [sections]);
  const selectedRun = runs.find((r) => r.id === selectedRunId) || null;

  const loadGroups = () => remedialApi.listGroups().then((r) => setGroups(r.data));
  const loadRuns = () => remedialApi.listRuns().then((r) => {
    setRuns(r.data);
    return r.data as RemedialRun[];
  });

  useEffect(() => {
    Promise.all([subjectsApi.list(), sectionsApi.list(), teachersApi.list(), constraintsApi.listTimeSlots('remedial'), loadGroups(), loadRuns()])
      .then(([subjectsRes, sectionsRes, teachersRes, slotsRes, , runList]) => {
        setSubjects(subjectsRes.data);
        setSections(sectionsRes.data);
        setTeachers(teachersRes.data);
        setRemedialSlotCount(slotsRes.data.length);
        if (runList.length) setSelectedRunId(runList[0].id);
      })
      .catch(() => setError('Could not load remedial data.'));
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load the grid data whenever a completed run is selected.
  useEffect(() => {
    setView(null);
    if (selectedRun?.status === 'completed') {
      remedialApi.getSectionView(selectedRun.id).then((r) => setView(r.data)).catch(() => setError('Could not load the remedial timetable.'));
    }
  }, [selectedRun?.id, selectedRun?.status]);

  const saveGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    setError('');
    const body = {
      ...form,
      id: form.id || `rg_${Date.now().toString(36)}`,
      department_id: departmentId || undefined,
      teacher_id: form.teacher_id || null,
      allowed_days: form.allowed_days.length ? form.allowed_days : null,
    };
    try {
      if (editing) await remedialApi.updateGroup(form.id, body);
      else await remedialApi.createGroup(body);
      setForm(null);
      await loadGroups();
    } catch (err: any) {
      setError(errorText(err, 'Could not save this remedial group.'));
    }
  };

  const editGroup = (g: RemedialGroup) => {
    setEditing(true);
    setForm({
      id: g.id, name: g.name, subject_id: g.subject_id, section_ids: g.section_ids, strength: g.strength,
      periods_per_week: g.periods_per_week, periods_per_session: g.periods_per_session,
      teacher_id: g.teacher_id || '', allowed_days: g.allowed_days || [],
    });
  };

  const removeGroup = async (g: RemedialGroup) => {
    if (!window.confirm(`Delete remedial group "${g.name}"?`)) return;
    try {
      await remedialApi.deleteGroup(g.id);
      await loadGroups();
    } catch (err: any) {
      setError(errorText(err, 'Could not delete this group.'));
    }
  };

  const generate = async () => {
    setBusy(true);
    setError('');
    try {
      const created = await remedialApi.generate({ department_id: departmentId || undefined, settings });
      const runId: number = created.data.id;
      setSelectedRunId(runId);
      await loadRuns();
      // The solve runs in the background; poll until it finishes.
      pollRef.current = window.setInterval(async () => {
        const list = await loadRuns();
        const run = list.find((r) => r.id === runId);
        if (run && (run.status === 'completed' || run.status === 'failed')) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          setBusy(false);
        }
      }, 1500);
    } catch (err: any) {
      setError(errorText(err, 'Could not start remedial generation.'));
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!selectedRun) return;
    try {
      await remedialApi.publish(selectedRun.id);
      await loadRuns();
    } catch (err: any) {
      setError(errorText(err, 'Could not publish this remedial timetable.'));
    }
  };

  const download = async () => {
    if (!selectedRun) return;
    const res = await remedialApi.export(selectedRun.id);
    const url = URL.createObjectURL(res.data);
    const link = document.createElement('a');
    link.href = url;
    link.download = `remedial-timetable-${selectedRun.id}.xlsx`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const setNumber = (key: keyof RemedialSettings) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setSettings({ ...settings, [key]: Number(e.target.value) });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Remedial classes</h1>
        <p className="text-gray-600">
          Extra classes for low-attendance students, fitted around the published main timetable. The main
          timetable is never changed.
        </p>
      </div>

      {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <div className={`rounded-lg border p-3 text-sm ${remedialSlotCount ? 'border-gray-200 bg-gray-50 text-gray-700' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
        {remedialSlotCount
          ? <>{remedialSlotCount} remedial-only period(s) defined (e.g. after hours or Saturday). </>
          : <>No remedial-only periods defined, so only free periods in the main timetable can be used. </>}
        Add or change them under <Link to="/settings" className="font-medium underline">Settings - Class times</Link> (choose "Remedial classes only").
      </div>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">1. Who needs remedial classes</h2>
          <button onClick={() => { setEditing(false); setForm({ ...EMPTY_FORM }); }} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700">
            <Plus size={16} /> Add group
          </button>
        </div>

        {form && (
          <form onSubmit={saveGroup} className="mb-4 grid grid-cols-1 gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4 md:grid-cols-3">
            <label className="text-sm text-gray-700">Group name
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Maths - low attendance" className="mt-1 w-full rounded border px-3 py-2" />
            </label>
            <label className="text-sm text-gray-700">Subject
              <select required value={form.subject_id} onChange={(e) => setForm({ ...form, subject_id: e.target.value })} className="mt-1 w-full rounded border px-3 py-2">
                <option value="">Select subject</option>
                {subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            <label className="text-sm text-gray-700">Teacher (optional)
              <select value={form.teacher_id} onChange={(e) => setForm({ ...form, teacher_id: e.target.value })} className="mt-1 w-full rounded border px-3 py-2">
                <option value="">The subject's regular teacher</option>
                {teachers.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </label>
            <fieldset className="md:col-span-3">
              <legend className="text-sm text-gray-700">Students come from section(s) - pick several to combine them</legend>
              <div className="mt-1 flex flex-wrap gap-2">
                {sections.map((s) => {
                  const on = form.section_ids.includes(s.id);
                  return (
                    <button type="button" key={s.id}
                      onClick={() => setForm({ ...form, section_ids: on ? form.section_ids.filter((id) => id !== s.id) : [...form.section_ids, s.id] })}
                      className={`rounded-full border px-3 py-1 text-sm ${on ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'}`}>
                      {s.name}
                    </button>
                  );
                })}
              </div>
            </fieldset>
            <label className="text-sm text-gray-700">Students in the group
              <input type="number" min={1} required value={form.strength} onChange={(e) => setForm({ ...form, strength: Number(e.target.value) })} className="mt-1 w-full rounded border px-3 py-2" />
            </label>
            <label className="text-sm text-gray-700">Periods per week (weightage)
              <input type="number" min={1} required value={form.periods_per_week} onChange={(e) => setForm({ ...form, periods_per_week: Number(e.target.value) })} className="mt-1 w-full rounded border px-3 py-2" />
            </label>
            <label className="text-sm text-gray-700">Periods per class
              <input type="number" min={1} required value={form.periods_per_session} onChange={(e) => setForm({ ...form, periods_per_session: Number(e.target.value) })} className="mt-1 w-full rounded border px-3 py-2" />
            </label>
            <fieldset className="md:col-span-3">
              <legend className="text-sm text-gray-700">Only on these days (leave empty for any day)</legend>
              <div className="mt-1 flex flex-wrap gap-2">
                {DAYS.map((d) => {
                  const on = form.allowed_days.includes(d);
                  return (
                    <button type="button" key={d}
                      onClick={() => setForm({ ...form, allowed_days: on ? form.allowed_days.filter((x) => x !== d) : [...form.allowed_days, d] })}
                      className={`rounded-full border px-3 py-1 text-sm ${on ? 'border-amber-500 bg-amber-500 text-white' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'}`}>
                      {DAY_LABELS[d]}
                    </button>
                  );
                })}
              </div>
            </fieldset>
            <div className="flex gap-2 md:col-span-3">
              <button type="submit" disabled={!form.section_ids.length} className="rounded-lg bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50">{editing ? 'Update group' : 'Save group'}</button>
              <button type="button" onClick={() => setForm(null)} className="rounded-lg bg-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-400">Cancel</button>
            </div>
          </form>
        )}

        <div className="overflow-x-auto rounded border">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr><th className="px-3 py-2">Group</th><th className="px-3 py-2">Subject</th><th className="px-3 py-2">Sections</th><th className="px-3 py-2">Students</th><th className="px-3 py-2">Periods/week</th><th className="px-3 py-2">Days</th><th className="px-3 py-2">Teacher</th><th /></tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.id} className="border-t">
                  <td className="px-3 py-2 font-medium">{g.name}</td>
                  <td className="px-3 py-2">{subjectName[g.subject_id] || g.subject_id}</td>
                  <td className="px-3 py-2">{g.section_ids.map((id) => sectionName[id] || id).join(', ')}</td>
                  <td className="px-3 py-2">{g.strength}</td>
                  <td className="px-3 py-2">{g.periods_per_week}</td>
                  <td className="px-3 py-2">{g.allowed_days?.length ? g.allowed_days.join(', ') : 'Any'}</td>
                  <td className="px-3 py-2">{g.teacher_id ? teacherName[g.teacher_id] || g.teacher_id : 'Regular teacher'}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => editGroup(g)} className="mr-1 rounded p-1 text-blue-600 hover:bg-blue-100"><Pencil size={16} /></button>
                    <button onClick={() => removeGroup(g)} className="rounded p-1 text-red-600 hover:bg-red-100"><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
              {groups.length === 0 && <tr><td colSpan={8} className="px-3 py-4 text-center text-gray-500">No remedial groups yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-gray-900">2. Rules for this timetable</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <label className="text-sm text-gray-700">Preferred classes per day, per section
            <input type="number" min={1} value={settings.preferred_max_per_day} onChange={setNumber('preferred_max_per_day')} className="mt-1 w-full rounded border px-3 py-2" />
          </label>
          <label className="text-sm text-gray-700">Never more than, per section per day
            <input type="number" min={1} value={settings.hard_max_per_day} onChange={setNumber('hard_max_per_day')} className="mt-1 w-full rounded border px-3 py-2" />
          </label>
          <label className="text-sm text-gray-700">Teacher: most per day
            <input type="number" min={1} value={settings.teacher_max_remedial_per_day} onChange={setNumber('teacher_max_remedial_per_day')} className="mt-1 w-full rounded border px-3 py-2" />
          </label>
          <label className="text-sm text-gray-700">Teacher: most per week
            <input type="number" min={1} value={settings.teacher_max_remedial_per_week} onChange={setNumber('teacher_max_remedial_per_week')} className="mt-1 w-full rounded border px-3 py-2" />
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700 md:col-span-4">
            <input type="checkbox" checked={settings.use_free_regular_slots} onChange={(e) => setSettings({ ...settings, use_free_regular_slots: e.target.checked })} />
            Also use free periods in the main timetable (not only the remedial-only periods)
          </label>
        </div>
        <button onClick={generate} disabled={busy || groups.length === 0} className="mt-4 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50">
          <Play size={16} /> {busy ? 'Generating...' : 'Generate remedial timetable'}
        </button>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold text-gray-900">3. Result</h2>
          {runs.length > 0 && (
            <select value={selectedRunId ?? ''} onChange={(e) => setSelectedRunId(Number(e.target.value))} className="rounded border px-2 py-1 text-sm">
              {runs.map((r) => <option key={r.id} value={r.id}>Run #{r.id} - {r.status}{r.is_published ? ' (published)' : ''}</option>)}
            </select>
          )}
          {selectedRun?.status === 'completed' && (
            <>
              <button onClick={publish} disabled={selectedRun.is_published} className="flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"><UploadCloud size={15} /> {selectedRun.is_published ? 'Published' : 'Publish'}</button>
              <button onClick={download} className="flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"><Download size={15} /> Excel</button>
            </>
          )}
        </div>

        {!selectedRun && <p className="text-sm text-gray-500">Generate a remedial timetable to see it here.</p>}
        {selectedRun && (selectedRun.status === 'pending' || selectedRun.status === 'solving') && <p className="text-sm text-gray-500">Working on it...</p>}
        {selectedRun?.status === 'failed' && (
          <pre className="whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{selectedRun.explanation}</pre>
        )}
        {selectedRun?.solver_output?.warnings?.map((w) => <p key={w} className="mb-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">{w}</p>)}
        {selectedRun?.status === 'completed' && view && (
          <div className="space-y-6">
            {view.sections.map((s) => <SectionRemedialGrid key={s.section_id} section={s} view={view} subjectName={(id) => (id && subjectName[id]) || ''} />)}
          </div>
        )}
      </section>
    </div>
  );
}

/** One section's week: main classes greyed out, remedial classes highlighted. */
function SectionRemedialGrid({ section, view, subjectName }: {
  section: RemedialSectionView['sections'][number];
  view: RemedialSectionView;
  subjectName: (id: string | null) => string;
}) {
  const days = DAYS.filter((d) => view.slots.some((s) => s.day === d));
  const periods = [...new Set(view.slots.map((s) => s.period_index))].sort((a, b) => a - b);
  const slotAt = (day: string, period: number) => view.slots.find((s) => s.day === day && s.period_index === period);
  return (
    <div>
      <h3 className="mb-2 font-semibold text-gray-900">{section.name}</h3>
      <div className="overflow-x-auto rounded border">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50">
            <tr><th className="px-2 py-1 text-left">Period</th>{days.map((d) => <th key={d} className="px-2 py-1 text-left">{DAY_LABELS[d]}</th>)}</tr>
          </thead>
          <tbody>
            {periods.map((p) => (
              <tr key={p} className="border-t align-top">
                <td className="whitespace-nowrap px-2 py-1 text-gray-500">{p}</td>
                {days.map((d) => {
                  const slot = slotAt(d, p);
                  if (!slot) return <td key={d} className="bg-gray-100" />;
                  const main = section.main.filter((m) => m.day === d && m.period === p);
                  const remedial = section.remedial.filter((r) => r.day === d && r.period === p);
                  return (
                    <td key={d} className={`px-2 py-1 ${slot.slot_kind === 'remedial' ? 'bg-amber-50/60' : ''}`}>
                      <div className="text-[10px] text-gray-400">{formatTime(slot.start_time)}</div>
                      {main.map((m, i) => <div key={i} className="rounded bg-gray-200 px-1 py-0.5 text-gray-600">{subjectName(m.subject_id)}</div>)}
                      {remedial.map((r, i) => (
                        <div key={i} className="rounded bg-amber-300 px-1 py-0.5 font-medium text-amber-950">
                          Remedial: {subjectName(r.subject_id)}
                        </div>
                      ))}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
