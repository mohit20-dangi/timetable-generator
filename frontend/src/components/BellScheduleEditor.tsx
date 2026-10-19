import { useEffect, useMemo, useState } from 'react';
import { Copy, Plus, Sparkles, Trash2 } from 'lucide-react';
import { constraintsApi } from '../api/client';
import { useDepartment } from '../context/DepartmentContext';
import { TimeInput } from './TimeInput';
import SelectAllButtons from './SelectAllButtons';
import {
  DAYS, DAY_LABELS, DEFAULT_SLOTS, DraftPeriod, DraftSchedule, PatternBreak, ScheduleSlot,
  buildPattern, displayLabels, formatTime, normaliseTime, scheduleProblems, toClock, toMinutes,
} from '../utils/schedule';

let keyCounter = 0;
const newKey = () => `p${++keyCounter}`;

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function toDraft(slots: ScheduleSlot[]): DraftSchedule {
  const draft: DraftSchedule = {};
  slots.forEach((s) => {
    (draft[s.day] ||= []).push({
      key: newKey(), start_time: normaliseTime(s.start_time), end_time: normaliseTime(s.end_time), slot_kind: s.slot_kind || 'regular',
    });
  });
  return draft;
}

const sorted = (periods: DraftPeriod[]) => [...periods].sort((a, b) => toMinutes(a.start_time) - toMinutes(b.start_time));

/** Order-independent fingerprint, for "unsaved changes" tracking. */
const fingerprint = (draft: DraftSchedule) =>
  JSON.stringify(DAYS.map((d) => sorted(draft[d] || []).map((p) => [p.start_time, p.end_time, p.slot_kind])));

export function BellScheduleEditor() {
  const { departmentId } = useDepartment();
  const [draft, setDraft] = useState<DraftSchedule>({});
  const [baseline, setBaseline] = useState('');
  const [usingDefaults, setUsingDefaults] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [selected, setSelected] = useState<{ day: string; key: string } | null>(null);

  const [genOpen, setGenOpen] = useState(false);
  const [genStart, setGenStart] = useState('09:00');
  const [genLength, setGenLength] = useState(50);
  const [genCount, setGenCount] = useState(8);
  const [genBreaks, setGenBreaks] = useState<PatternBreak[]>([]);
  const [genDays, setGenDays] = useState<string[]>(WEEKDAYS);

  const applyLoaded = (slots: ScheduleSlot[]) => {
    const empty = slots.length === 0;
    const next = toDraft(empty ? DEFAULT_SLOTS : slots);
    setDraft(next);
    // An empty baseline means "nothing saved yet", so the defaults count as unsaved changes.
    setBaseline(empty ? '' : fingerprint(next));
    setUsingDefaults(empty);
    setSelected(null);
    return empty;
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setMessage('');
    constraintsApi.listTimeSlots('all')
      .then((response) => {
        if (!cancelled) setGenOpen(applyLoaded(response.data));
      })
      .catch(() => !cancelled && setError('Could not load the schedule.'))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [departmentId]);

  const problems = useMemo(() => scheduleProblems(draft), [draft]);
  const dirty = fingerprint(draft) !== baseline;
  const activeDays = DAYS.filter((d) => (draft[d] || []).length > 0);
  const rowCount = Math.max(0, ...activeDays.map((d) => draft[d].length));
  const selectedPeriod = selected ? (draft[selected.day] || []).find((p) => p.key === selected.key) : undefined;

  const setDay = (day: string, periods: DraftPeriod[]) => {
    setDraft((current) => ({ ...current, [day]: periods }));
    setMessage('');
  };
  const patchPeriod = (day: string, key: string, patch: Partial<DraftPeriod>) =>
    setDay(day, draft[day].map((p) => (p.key === key ? { ...p, ...patch } : p)));

  const generate = () => {
    if (genDays.length === 0) return setError('Tick at least one day.');
    if (genLength < 5 || genCount < 1) return setError('Period length and count must be positive.');
    const pattern = buildPattern(genStart, genLength, genCount, genBreaks);
    if (toMinutes(pattern[pattern.length - 1].end_time) > 24 * 60) return setError('That pattern runs past midnight.');
    setError('');
    setDraft((current) => {
      const next = { ...current };
      genDays.forEach((day) => {
        const remedial = (current[day] || []).filter((p) => p.slot_kind === 'remedial');
        next[day] = [...pattern.map((p) => ({ key: newKey(), ...p, slot_kind: 'regular' as const })), ...remedial];
      });
      return next;
    });
    setUsingDefaults(false);
    setSelected(null);
    setMessage(`Generated ${genCount} periods for ${genDays.length} day${genDays.length > 1 ? 's' : ''}. Review them, then save.`);
  };

  const addPeriod = (day: string) => {
    const periods = sorted(draft[day] || []);
    const last = periods[periods.length - 1];
    const length = last ? toMinutes(last.end_time) - toMinutes(last.start_time) : 50;
    const start = last ? toMinutes(last.end_time) : 9 * 60;
    const period: DraftPeriod = {
      key: newKey(), start_time: toClock(Math.min(start, 23 * 60)), end_time: toClock(Math.min(start + length, 24 * 60 - 1)), slot_kind: 'regular',
    };
    setDay(day, [...periods, period]);
    setSelected({ day, key: period.key });
  };

  const copyDay = (from: string, to: string) => {
    if (!to) return;
    setDay(to, (draft[from] || []).map((p) => ({ ...p, key: newKey() })));
    setMessage(`Copied ${DAY_LABELS[from]} to ${DAY_LABELS[to]}.`);
  };

  const applyToAllDays = () => {
    if (!selected || !selectedPeriod) return;
    const ordinal = sorted(draft[selected.day]).findIndex((p) => p.key === selected.key);
    setDraft((current) => {
      const next = { ...current };
      activeDays.forEach((day) => {
        const periods = sorted(current[day]);
        const target = periods[ordinal];
        if (target) {
          next[day] = periods.map((p) => (p.key === target.key
            ? { ...p, start_time: selectedPeriod.start_time, end_time: selectedPeriod.end_time, slot_kind: selectedPeriod.slot_kind }
            : p));
        }
      });
      return next;
    });
  };

  const save = async () => {
    setError('');
    setMessage('');
    setSaving(true);
    try {
      const periods = DAYS.flatMap((day) => (draft[day] || []).map((p) => ({
        day, start_time: p.start_time, end_time: p.end_time, slot_kind: p.slot_kind,
      })));
      const response = await constraintsApi.replaceTimeSlots({ department_id: departmentId || undefined, periods });
      applyLoaded(response.data);
      setMessage('Bell schedule saved.');
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not save the schedule.');
    } finally {
      setSaving(false);
    }
  };

  const discard = () => {
    setLoading(true);
    setMessage('');
    constraintsApi.listTimeSlots('all')
      .then((response) => applyLoaded(response.data))
      .catch(() => setError('Could not reload the schedule.'))
      .finally(() => setLoading(false));
  };

  if (loading) return <p className="text-sm text-gray-500">Loading schedule…</p>;

  const inputCls = 'mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm';
  const missingDays = DAYS.filter((d) => !activeDays.includes(d));

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-lg font-semibold text-gray-900">Class times</h3>
        <p className="text-sm text-gray-600">
          Set the daily periods once, then adjust any period. <strong>Remedial</strong> periods (after hours, or a free day like Saturday) are used only by remedial classes, never the main timetable. Timetables and exports use this schedule.
        </p>
      </div>

      {usingDefaults && (
        <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-800">You're using the default 8-period schedule. Edit and save to customise it.</div>
      )}
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && <div className="rounded-lg bg-green-50 p-3 text-sm text-green-700">{message}</div>}

      <div className="rounded-lg border border-gray-200">
        <button type="button" onClick={() => setGenOpen(!genOpen)} className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-gray-900">
          <Sparkles size={16} className="text-blue-600" /> Generate schedule
          <span className="ml-auto text-xs font-normal text-gray-500">{genOpen ? 'Hide' : 'Set start, length, count and breaks for many days at once'}</span>
        </button>
        {genOpen && (
          <div className="space-y-4 border-t border-gray-200 p-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <label className="text-sm text-gray-700">First period starts<TimeInput value={genStart} onChange={setGenStart} className={inputCls} /></label>
              <label className="text-sm text-gray-700">Period length (minutes)
                <input type="number" min={5} value={genLength} onChange={(e) => setGenLength(Number(e.target.value))} className={inputCls} />
              </label>
              <label className="text-sm text-gray-700">Number of periods
                <input type="number" min={1} max={20} value={genCount} onChange={(e) => setGenCount(Number(e.target.value))} className={inputCls} />
              </label>
            </div>
            <div className="space-y-2">
              <div className="text-sm text-gray-700">Breaks (lunch, tea)</div>
              {genBreaks.map((b, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 text-sm text-gray-700">
                  After period
                  <input type="number" min={1} max={genCount} value={b.afterPeriod}
                    onChange={(e) => setGenBreaks(genBreaks.map((x, j) => (j === i ? { ...x, afterPeriod: Number(e.target.value) } : x)))}
                    className="w-16 rounded border border-gray-300 px-2 py-1" />
                  for
                  <input type="number" min={1} value={b.minutes}
                    onChange={(e) => setGenBreaks(genBreaks.map((x, j) => (j === i ? { ...x, minutes: Number(e.target.value) } : x)))}
                    className="w-16 rounded border border-gray-300 px-2 py-1" />
                  minutes
                  <button type="button" aria-label="Remove break" onClick={() => setGenBreaks(genBreaks.filter((_, j) => j !== i))} className="text-red-600"><Trash2 size={14} /></button>
                </div>
              ))}
              {genBreaks.length < 2 && (
                <button type="button" onClick={() => setGenBreaks([...genBreaks, { afterPeriod: Math.max(1, Math.floor(genCount / 2)), minutes: 60 }])}
                  className="inline-flex items-center gap-1 text-sm text-blue-700 hover:underline"><Plus size={14} /> Add break</button>
              )}
            </div>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-3 text-sm text-gray-700">
                Apply to days <SelectAllButtons onSelectAll={() => setGenDays([...DAYS])} onClear={() => setGenDays([])} />
              </div>
              <div className="flex flex-wrap gap-2">
                {DAYS.map((d) => (
                  <button key={d} type="button" onClick={() => setGenDays(genDays.includes(d) ? genDays.filter((x) => x !== d) : [...genDays, d])}
                    className={`rounded-full border px-3 py-1 text-sm ${genDays.includes(d) ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}`}>{d}</button>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" onClick={generate} className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">Generate</button>
              <span className="text-xs text-gray-500">Replaces the regular periods on the ticked days; remedial periods are kept. Nothing is saved until you press Save.</span>
            </div>
          </div>
        )}
      </div>

      {activeDays.length === 0 ? (
        <p className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">No periods yet. Use Generate schedule above, or add a day below.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                {activeDays.map((day) => (
                  <th key={day} className="min-w-[10rem] px-3 py-2 text-left align-top font-medium text-gray-900">
                    <div className="flex items-center justify-between gap-2">
                      {DAY_LABELS[day]}
                      <button type="button" aria-label={`Clear ${DAY_LABELS[day]}`} title="Clear day"
                        onClick={() => { setDay(day, []); setSelected(null); }} className="text-gray-400 hover:text-red-600"><Trash2 size={14} /></button>
                    </div>
                    <label className="mt-1 flex items-center gap-1 text-xs font-normal text-gray-500"><Copy size={12} />
                      <select value="" onChange={(e) => copyDay(day, e.target.value)} className="bg-transparent text-xs">
                        <option value="">Copy to…</option>
                        {DAYS.filter((d) => d !== day).map((d) => <option key={d} value={d}>{DAY_LABELS[d]}</option>)}
                      </select>
                    </label>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: rowCount }, (_, row) => (
                <tr key={row} className="border-t border-gray-100">
                  {activeDays.map((day) => {
                    const period = sorted(draft[day])[row];
                    if (!period) return <td key={day} />;
                    const label = displayLabels(draft[day]).get(period.key);
                    const active = selected?.day === day && selected.key === period.key;
                    const tone = active
                      ? 'border-blue-600 bg-blue-50'
                      : period.slot_kind === 'remedial' ? 'border-amber-200 bg-amber-50 hover:bg-amber-100' : 'border-gray-200 hover:bg-gray-50';
                    return (
                      <td key={day} className="p-1">
                        <button type="button" onClick={() => setSelected(active ? null : { day, key: period.key })} className={`w-full rounded border px-2 py-1.5 text-left ${tone}`}>
                          <div className="text-xs text-gray-500">{label}</div>
                          <div className="text-gray-900">{formatTime(period.start_time)} – {formatTime(period.end_time)}</div>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr className="border-t border-gray-100">
                {activeDays.map((day) => (
                  <td key={day} className="p-1">
                    <button type="button" onClick={() => addPeriod(day)} className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-700 hover:underline"><Plus size={13} /> Add period</button>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {missingDays.length > 0 && (
        <label className="inline-flex items-center gap-2 text-sm text-gray-700">
          Add a day
          <select value="" onChange={(e) => e.target.value && addPeriod(e.target.value)} className="rounded border border-gray-300 px-2 py-1 text-sm">
            <option value="">Choose…</option>
            {missingDays.map((d) => <option key={d} value={d}>{DAY_LABELS[d]}</option>)}
          </select>
        </label>
      )}

      {selected && selectedPeriod && (
        <div className="space-y-3 rounded-lg border border-blue-200 bg-blue-50/40 p-4">
          <div className="text-sm font-medium text-gray-900">Editing {DAY_LABELS[selected.day]} · {displayLabels(draft[selected.day]).get(selectedPeriod.key)}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <label className="text-sm text-gray-700">Start
              <TimeInput value={selectedPeriod.start_time} onChange={(v) => v && patchPeriod(selected.day, selected.key, { start_time: v })} className={`${inputCls} bg-white`} />
            </label>
            <label className="text-sm text-gray-700">End
              <TimeInput value={selectedPeriod.end_time} onChange={(v) => v && patchPeriod(selected.day, selected.key, { end_time: v })} className={`${inputCls} bg-white`} />
            </label>
            <label className="text-sm text-gray-700">Used for
              <select value={selectedPeriod.slot_kind} onChange={(e) => patchPeriod(selected.day, selected.key, { slot_kind: e.target.value as 'regular' | 'remedial' })} className={`${inputCls} bg-white`}>
                <option value="regular">Regular classes</option>
                <option value="remedial">Remedial classes only</option>
              </select>
            </label>
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <button type="button" onClick={applyToAllDays} className="text-blue-700 hover:underline">Apply this time to the same period on every day</button>
            <button type="button" onClick={() => { setDay(selected.day, draft[selected.day].filter((p) => p.key !== selected.key)); setSelected(null); }}
              className="inline-flex items-center gap-1 text-red-600 hover:underline"><Trash2 size={14} /> Delete period</button>
          </div>
        </div>
      )}

      {problems.length > 0 && (
        <ul className="space-y-1 rounded-lg bg-red-50 p-3 text-sm text-red-700">
          {problems.map((p, i) => <li key={i}>{DAY_LABELS[p.day]}: {p.message}</li>)}
        </ul>
      )}

      <div className="sticky bottom-0 -mx-1 flex items-center gap-3 border-t border-gray-200 bg-white px-1 py-3">
        <span className="text-sm text-gray-600">{dirty ? 'You have unsaved changes.' : 'All changes saved.'}</span>
        <div className="ml-auto flex gap-2">
          <button type="button" onClick={discard} disabled={!dirty || saving} className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">Discard</button>
          <button type="button" onClick={save} disabled={!dirty || saving || problems.length > 0 || activeDays.length === 0}
            className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">{saving ? 'Saving…' : 'Save schedule'}</button>
        </div>
      </div>
    </div>
  );
}
