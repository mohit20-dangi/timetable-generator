import { TimeInput } from './TimeInput';
import { useEffect, useMemo, useState } from 'react';
import { constraintsApi, customFilterApi, roomsApi, sectionsApi, subjectsApi, subjectTypesApi, teachersApi, yearsApi } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { isAdmin } from '../auth/roles';
import { AcademicYear, FilterCell, FilterSpec, Room, Section, SavedFilter, Subject, Teacher } from '../types';
import { sectionLabel, yearMap } from '../utils/sectionLabel';
import { DAYS, DAY_LABELS, DEFAULT_SLOTS, ScheduleSlot, timeLabel } from '../utils/schedule';
import { AlertCircle, Bookmark, Send, Sparkles, X } from 'lucide-react';

interface Props {
  // Admin/HOD in the run viewer pass the run; faculty (My Timetable) omit it
  // and the filter runs over the published timetables instead.
  runId?: number;
}

const EMPTY_SPEC: FilterSpec = {
  mode: 'classes', days: [], time_from: null, time_to: null,
  teacher_ids: [], section_ids: [], subject_ids: [], room_ids: [],
  room_types: [], subject_types: [], min_room_capacity: null,
};

const ME = '$me';

type Option = { value: string; label: string };

function MultiPick({ label, options, value, onChange }: {
  label: string; options: Option[]; value: string[]; onChange: (next: string[]) => void;
}) {
  const labelOf = (v: string) => options.find((o) => o.value === v)?.label || v;
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <select
        value=""
        onChange={(e) => e.target.value && !value.includes(e.target.value) && onChange([...value, e.target.value])}
        className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
      >
        <option value="">Add…</option>
        {options.filter((o) => !value.includes(o.value)).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {value.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {value.map((v) => (
            <span key={v} className="inline-flex items-center gap-1 rounded-full bg-purple-100 px-2 py-0.5 text-xs text-purple-800">
              {labelOf(v)}
              <button type="button" onClick={() => onChange(value.filter((x) => x !== v))} aria-label={`Remove ${labelOf(v)}`}>
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Teacher-facing "custom filter" tab. The LLM (POST /custom-filters/parse)
 * only ever turns a sentence into a FilterSpec; the grid always comes from
 * the deterministic POST /custom-filters/evaluate. Saved filters are stored
 * specs, so re-running one costs no model call - the point of asking to
 * save a new filter is that the LLM is needed less and less over time.
 */
export function CustomFilterView({ runId }: Props) {
  const { user } = useAuth();
  const [sections, setSections] = useState<Section[]>([]);
  const [years, setYears] = useState<Record<string, AcademicYear>>({});
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [typeColors, setTypeColors] = useState<Record<string, string>>({});
  const [slots, setSlots] = useState<ScheduleSlot[]>(DEFAULT_SLOTS);
  const [saved, setSaved] = useState<SavedFilter[]>([]);

  const [query, setQuery] = useState('');
  const [spec, setSpec] = useState<FilterSpec>(EMPTY_SPEC);
  const [cells, setCells] = useState<FilterCell[] | null>(null);
  const [notes, setNotes] = useState<{ explanation: string; unsupported: string[]; dropped: string[] } | null>(null);
  const [unsavedAI, setUnsavedAI] = useState<{ title: string; query: string } | null>(null);
  const [saveName, setSaveName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSaved = () => customFilterApi.listSaved().then((r) => setSaved(r.data)).catch(() => undefined);

  useEffect(() => {
    sectionsApi.list().then((r) => setSections(r.data));
    yearsApi.list().then((r) => setYears(yearMap(r.data)));
    teachersApi.list().then((r) => setTeachers(r.data));
    roomsApi.list().then((r) => setRooms(r.data));
    subjectsApi.list().then((r) => setSubjects(r.data));
    subjectTypesApi.list().then((r) => {
      const map: Record<string, string> = {};
      r.data.forEach((t: { id: string; colour_hex: string }) => { map[t.id] = t.colour_hex; });
      setTypeColors(map);
    });
    constraintsApi.listTimeSlots().then((r) => { if (r.data.length) setSlots(r.data); }).catch(() => undefined);
    loadSaved();
  }, []);

  const sectionName = (id: string | null) => sections.find((s) => s.id === id)?.name || id || '';
  const subjectById = useMemo(() => new Map(subjects.map((s) => [s.id, s])), [subjects]);
  const teacherName = (id: string) => teachers.find((t) => t.id === id)?.name || id;
  const roomName = (id: string) => rooms.find((r) => r.id === id)?.name || id;

  const evaluate = async (next: FilterSpec) => {
    setBusy(true);
    setError(null);
    try {
      const res = await customFilterApi.evaluate(next, runId);
      setCells(res.data.cells);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not apply this filter.');
    } finally {
      setBusy(false);
    }
  };

  const editSpec = (patch: Partial<FilterSpec>) => {
    const next = { ...spec, ...patch };
    setSpec(next);
    evaluate(next);
  };

  const askAI = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await customFilterApi.parse(query, runId);
      const { spec: parsedSpec, title, explanation, unsupported, dropped_ids } = res.data;
      setSpec(parsedSpec);
      setNotes({ explanation, unsupported, dropped: dropped_ids });
      setUnsavedAI({ title, query });
      setSaveName(title);
      const evalRes = await customFilterApi.evaluate(parsedSpec, runId);
      setCells(evalRes.data.cells);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'The AI assistant is unavailable right now.');
    } finally {
      setBusy(false);
    }
  };

  const applySaved = (filter: SavedFilter) => {
    setSpec(filter.spec);
    setNotes(null);
    setUnsavedAI(null);
    evaluate(filter.spec);
  };

  const saveCurrent = async () => {
    if (!unsavedAI || !saveName.trim()) return;
    try {
      await customFilterApi.save({ name: saveName.trim(), original_query: unsavedAI.query, spec });
      setUnsavedAI(null);
      await loadSaved();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not save this filter.');
    }
  };

  const deleteSaved = async (id: string) => {
    try {
      await customFilterApi.deleteSaved(id);
      await loadSaved();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not delete this filter.');
    }
  };

  const teacherOptions: Option[] = [
    ...(user?.teacher_id ? [{ value: ME, label: 'Me' }] : []),
    ...teachers.map((t) => ({ value: t.id, label: t.name })),
  ];
  const roomTypes = [...new Set(rooms.map((r) => r.type))];
  const subjectTypes = [...new Set(subjects.map((s) => s.type))];
  const periods = [...new Set(slots.map((s) => s.period_index))].sort((a, b) => a - b);
  const cellMap = new Map((cells || []).map((c) => [`${c.day}-${c.period}`, c]));
  const colourStyle = (subjectId: string): React.CSSProperties => {
    const hex = typeColors[subjectById.get(subjectId)?.type || ''] || 'E5E7EB';
    return { backgroundColor: `#${hex}`, borderColor: `#${hex}` };
  };

  return (
    <div className="space-y-4">
      {saved.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">Saved filters</p>
          <div className="flex flex-wrap gap-2">
            {saved.map((f) => (
              <span key={f.id} className="inline-flex items-center rounded-full border border-purple-200 bg-white text-sm">
                <button
                  type="button" onClick={() => applySaved(f)} title={f.original_query || f.description || f.name}
                  className="px-3 py-1 text-purple-900 hover:bg-purple-50 rounded-l-full"
                >
                  {f.name}
                </button>
                {(isAdmin(user?.role) || f.created_by === user?.id) && (
                  <button
                    type="button" onClick={() => deleteSaved(f.id)} aria-label={`Delete ${f.name}`}
                    className="px-2 py-1 text-gray-400 hover:text-red-600 rounded-r-full"
                  >
                    <X size={14} />
                  </button>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-lg border border-purple-200 bg-purple-50 p-4">
        <h3 className="flex items-center gap-2 font-semibold text-purple-900"><Sparkles size={20} /> Describe the view you need</h3>
        <p className="mt-1 text-sm text-purple-800">
          e.g. "When am I and Section A free on Thursday afternoon with a seminar room available?" or
          "All lab sessions in the morning". It builds a filter you can tweak below and save for next time.
        </p>
        <div className="mt-3 flex gap-2">
          <input
            type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && askAI()}
            placeholder="What do you want to see?"
            className="flex-1 rounded-lg border border-purple-300 px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
          <button
            onClick={askAI} disabled={busy || !query.trim()}
            className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {busy ? <div className="h-4 w-4 animate-spin rounded-full border-b-2 border-white" /> : <Send size={16} />}
            Build filter
          </button>
        </div>
        {error && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <AlertCircle size={18} className="mt-0.5" /> {error}
          </div>
        )}
        {notes && (
          <div className="mt-3 space-y-1 text-sm">
            {notes.explanation && <p className="text-gray-700">{notes.explanation}</p>}
            {[...notes.unsupported.map((u) => `Not supported: ${u}`), ...notes.dropped.map((d) => `Ignored unknown value - ${d}`)].map((t) => (
              <p key={t} className="text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">{t}</p>
            ))}
          </div>
        )}
      </div>

      {unsavedAI && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm">
          <Bookmark size={16} className="text-green-700" />
          <span className="text-green-900">Save this filter so you can reuse it without asking the AI again?</span>
          <input
            value={saveName} onChange={(e) => setSaveName(e.target.value)}
            className="rounded-lg border border-green-300 px-2 py-1 text-sm" aria-label="Filter name"
          />
          <button onClick={saveCurrent} disabled={!saveName.trim()} className="rounded-lg bg-green-600 px-3 py-1 text-white hover:bg-green-700 disabled:opacity-50">Save</button>
          <button onClick={() => setUnsavedAI(null)} className="rounded-lg border border-gray-300 px-3 py-1 text-gray-700 hover:bg-white">Not now</button>
        </div>
      )}

      <details open className="rounded-lg border border-gray-200 bg-white p-3">
        <summary className="cursor-pointer text-sm font-medium text-gray-700">Filter settings</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Show</label>
            <select
              value={spec.mode} onChange={(e) => editSpec({ mode: e.target.value as FilterSpec['mode'] })}
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
            >
              <option value="classes">Scheduled classes</option>
              <option value="free_slots">Free slots (everyone listed is free)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">From</label>
            <TimeInput value={spec.time_from || ''} onChange={(v) => editSpec({ time_from: v || null })} className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">To</label>
            <TimeInput value={spec.time_to || ''} onChange={(v) => editSpec({ time_to: v || null })} className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm" />
          </div>
          <div className="md:col-span-3">
            <label className="block text-xs font-medium text-gray-600 mb-1">Days (none selected = all)</label>
            <div className="flex flex-wrap gap-1">
              {DAYS.map((d) => {
                const on = spec.days.includes(d);
                return (
                  <button
                    key={d} type="button"
                    onClick={() => editSpec({ days: on ? spec.days.filter((x) => x !== d) : [...spec.days, d] })}
                    className={`rounded-full px-3 py-1 text-xs ${on ? 'bg-purple-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
                  >
                    {DAY_LABELS[d]}
                  </button>
                );
              })}
            </div>
          </div>
          <MultiPick label="Teachers" options={teacherOptions} value={spec.teacher_ids} onChange={(v) => editSpec({ teacher_ids: v })} />
          <MultiPick label="Sections" options={sections.map((s) => ({ value: s.id, label: sectionLabel(s, years) }))} value={spec.section_ids} onChange={(v) => editSpec({ section_ids: v })} />
          <MultiPick label="Subjects" options={subjects.map((s) => ({ value: s.id, label: s.name }))} value={spec.subject_ids} onChange={(v) => editSpec({ subject_ids: v })} />
          <MultiPick label="Rooms" options={rooms.map((r) => ({ value: r.id, label: r.name }))} value={spec.room_ids} onChange={(v) => editSpec({ room_ids: v })} />
          <MultiPick label="Room types" options={roomTypes.map((t) => ({ value: t, label: t }))} value={spec.room_types} onChange={(v) => editSpec({ room_types: v })} />
          <MultiPick label="Subject types" options={subjectTypes.map((t) => ({ value: t, label: t }))} value={spec.subject_types} onChange={(v) => editSpec({ subject_types: v })} />
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Minimum room capacity</label>
            <input
              type="number" min={0} value={spec.min_room_capacity ?? ''}
              onChange={(e) => editSpec({ min_room_capacity: e.target.value ? parseInt(e.target.value, 10) : null })}
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
        </div>
        <button type="button" onClick={() => { setSpec(EMPTY_SPEC); setCells(null); setNotes(null); setUnsavedAI(null); }} className="mt-3 text-xs text-gray-500 underline">
          Reset
        </button>
      </details>

      {cells !== null && (
        <>
          <p className="text-sm text-gray-600">
            {cells.length === 0
              ? (spec.mode === 'free_slots' ? 'No slot matches - nobody listed is free together (with a free room, if requested).' : 'No classes match this filter.')
              : spec.mode === 'free_slots' ? `${cells.length} free slot${cells.length === 1 ? '' : 's'} found.` : `${cells.length} time slot${cells.length === 1 ? '' : 's'} with matching classes.`}
          </p>
          <div className="bg-white rounded-lg border border-gray-200 overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr className="bg-gray-100">
                  <th className="px-4 py-2 text-left font-medium text-gray-700">Time</th>
                  {DAYS.map((d) => <th key={d} className="px-4 py-2 text-center font-medium text-gray-700">{DAY_LABELS[d]}</th>)}
                </tr>
              </thead>
              <tbody>
                {periods.map((p) => (
                  <tr key={p} className="border-b border-gray-200">
                    <td className="px-4 py-2 font-medium text-gray-600 whitespace-nowrap">
                      <div>Period {p}</div>
                      <div className="text-xs text-gray-400">{timeLabel(slots.find((s) => s.period_index === p))}</div>
                    </td>
                    {DAYS.map((d) => {
                      const cell = cellMap.get(`${d}-${p}`);
                      return (
                        <td key={d} className="p-1 border border-gray-100 align-top min-w-[110px]">
                          {cell && cell.entries.length > 0 && (
                            <div className="space-y-1">
                              {cell.entries.map((e) => (
                                <div key={e.id} style={colourStyle(e.subject_id)} className="p-2 rounded border text-xs text-gray-800">
                                  <div className="font-medium">{subjectById.get(e.subject_id)?.name || e.subject_id}</div>
                                  <div className="text-gray-600">{sectionName(e.section_id) || (e.batch_id ? `Batch ${e.batch_id}` : '')}</div>
                                  <div className="text-gray-600">{teacherName(e.teacher_id)}</div>
                                  <div className="text-gray-600">{roomName(e.room_id)}</div>
                                </div>
                              ))}
                            </div>
                          )}
                          {cell && cell.entries.length === 0 && (
                            <div className="rounded border border-green-300 bg-green-50 p-2 text-xs text-green-800">
                              <div className="font-medium">Free</div>
                              {cell.free_rooms.length > 0 && (
                                <div className="text-green-700">{cell.free_rooms.map((r) => r.name).join(', ')}</div>
                              )}
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
