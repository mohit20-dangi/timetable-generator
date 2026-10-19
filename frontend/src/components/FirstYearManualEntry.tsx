import { useEffect, useMemo, useState } from 'react';
import { formatTime } from '../utils/schedule';
import { AlertCircle, Loader2, Plus } from 'lucide-react';
import { constraintsApi, firstYearImportApi, roomsApi, teachersApi } from '../api/client';
import { Room, Teacher, TimeSlot } from '../types';

const DAY_ORDER = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const hhmm = formatTime;

interface Props {
  departmentId: string;
  /** Called after a lock is saved so the parent can refresh its list. */
  onSaved: (summary: string) => void;
}

/** Hand-enter first-year locks: pick a teacher or room, tick the slots it is
 * busy. For classes the OCR missed or misread, or when there is no PDF. This
 * ADDS locks - it never replaces the ones already saved. */
export function FirstYearManualEntry({ departmentId, onSaved }: Props) {
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [slots, setSlots] = useState<TimeSlot[]>([]);
  const [kind, setKind] = useState<'teacher' | 'room'>('teacher');
  const [resourceId, setResourceId] = useState('');
  const [subject, setSubject] = useState('');
  const [section, setSection] = useState('');
  const [batches, setBatches] = useState('');
  const [faculty, setFaculty] = useState('');
  const [roomText, setRoomText] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set()); // "Mon|4"
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([teachersApi.list(), roomsApi.list(), constraintsApi.listTimeSlots()]).then(([t, r, s]) => {
      setTeachers((t.data as Teacher[]).filter((x) => x.department_id === departmentId));
      setRooms((r.data as Room[]).filter((x: any) => !x.department_id || x.department_id === departmentId));
      setSlots(s.data);
    }).catch(() => setError('Could not load teachers, rooms and time slots.'));
  }, [departmentId]);

  const days = useMemo(() => DAY_ORDER.filter((d) => slots.some((s) => s.day === d)), [slots]);
  const periods = useMemo(() => {
    const byIndex = new Map<number, TimeSlot>();
    slots.forEach((s) => { if (!byIndex.has(s.period_index)) byIndex.set(s.period_index, s); });
    return [...byIndex.values()].sort((a, b) => a.period_index - b.period_index);
  }, [slots]);
  const exists = (day: string, period: number) => slots.some((s) => s.day === day && s.period_index === period);

  const toggle = (day: string, period: number) =>
    setPicked((prev) => {
      const next = new Set(prev);
      const key = `${day}|${period}`;
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });

  const options = kind === 'teacher'
    ? teachers.map((t) => ({ id: t.id, label: `${t.name}${t.initials ? ` (${t.initials})` : ''}` }))
    : rooms.map((r) => ({ id: r.id, label: r.name }));

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const response = await firstYearImportApi.addManual({
        department_id: departmentId, resource_type: kind, resource_id: resourceId,
        reason: ['1st yr', section.trim(), subject.trim(), roomText.trim()].filter(Boolean).join(' · '),
        subject: subject.trim(), section: section.trim(), faculty_text: faculty.trim(), room_text: roomText.trim(),
        batches: batches.split(',').map((b) => b.trim()).filter(Boolean),
        periods: [...picked].map((key) => {
          const [day, period] = key.split('|');
          return { day, period: Number(period) };
        }),
      });
      const added = response.data.teacher_locks + response.data.room_locks;
      const who = options.find((o) => o.id === resourceId)?.label ?? resourceId;
      onSaved(added === 0 ? `${who} was already locked for those slots.` : `Locked ${who} for ${added} slot${added === 1 ? '' : 's'}.`);
      setPicked(new Set());
      setSubject(''); setSection(''); setBatches(''); setFaculty(''); setRoomText('');
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not save the lock.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <details className="rounded-lg border border-gray-200 p-4">
      <summary className="cursor-pointer text-sm font-medium text-gray-900">Add a lock manually</summary>
      <div className="mt-3 space-y-3 text-sm">
        <p className="text-gray-600">
          For a class the PDF reading missed, or if you have no PDF. Tick the slots the teacher or room is busy with a
          first-year class (consecutive periods on a day become one tile). This adds to the existing locks; it does not
          replace them.
        </p>

        <div className="flex gap-3 flex-wrap items-center">
          <select
            value={kind}
            onChange={(e) => { setKind(e.target.value as 'teacher' | 'room'); setResourceId(''); }}
            className="border border-gray-300 rounded px-2 py-1"
          >
            <option value="teacher">Teacher</option>
            <option value="room">Room</option>
          </select>
          <select value={resourceId} onChange={(e) => setResourceId(e.target.value)} className="border border-gray-300 rounded px-2 py-1 min-w-[14rem]">
            <option value="">{kind === 'teacher' ? 'Choose a teacher…' : 'Choose a room…'}</option>
            {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {([
            ['Subject', subject, setSubject, 'e.g. CO34_OS'],
            ['Section', section, setSection, 'e.g. I-C'],
            ['Batch', batches, setBatches, 'e.g. C1, C2'],
            ['Faculty on it', faculty, setFaculty, 'e.g. KAM, RKD'],
            ['Room', roomText, setRoomText, 'e.g. LT102'],
          ] as const).map(([label, value, setter, hint]) => (
            <label key={label} className="text-xs text-gray-600">
              {label}
              <input
                value={value} onChange={(e) => setter(e.target.value)} maxLength={80} placeholder={hint}
                className="mt-0.5 w-full border border-gray-300 rounded px-2 py-1 text-sm text-gray-900"
              />
            </label>
          ))}
        </div>
        <p className="text-xs text-gray-500">
          These fill the class tile shown in that teacher’s (or room’s) timetable. All optional.
        </p>

        {slots.length === 0 ? (
          <p className="text-amber-700">No time slots are configured yet, so there is nothing to tick.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="text-xs border-collapse">
              <thead>
                <tr>
                  <th className="p-1"></th>
                  {days.map((d) => <th key={d} className="p-1 font-medium text-gray-600">{d}</th>)}
                </tr>
              </thead>
              <tbody>
                {periods.map((p) => (
                  <tr key={p.period_index}>
                    <td className="p-1 pr-2 text-gray-500 whitespace-nowrap">P{p.period_index} {hhmm(p.start_time)}–{hhmm(p.end_time)}</td>
                    {days.map((d) => (
                      <td key={d} className="p-1 text-center">
                        {exists(d, p.period_index) ? (
                          <button
                            type="button" onClick={() => toggle(d, p.period_index)}
                            aria-pressed={picked.has(`${d}|${p.period_index}`)}
                            aria-label={`${d} period ${p.period_index}`}
                            className={`w-9 h-7 rounded border ${picked.has(`${d}|${p.period_index}`)
                              ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-gray-300 hover:border-blue-400'}`}
                          >
                            {picked.has(`${d}|${p.period_index}`) ? '✓' : ''}
                          </button>
                        ) : <span className="text-gray-300">–</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {error && (
          <div className="flex gap-2 p-2 rounded-md bg-red-50 border border-red-200 text-red-800">
            <AlertCircle size={16} className="shrink-0 mt-0.5" /> <span>{error}</span>
          </div>
        )}
        <button
          onClick={save} disabled={saving || !resourceId || picked.size === 0}
          className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? <Loader2 className="animate-spin" size={14} /> : <Plus size={14} />}
          Add {picked.size} slot{picked.size === 1 ? '' : 's'}
        </button>
      </div>
    </details>
  );
}
