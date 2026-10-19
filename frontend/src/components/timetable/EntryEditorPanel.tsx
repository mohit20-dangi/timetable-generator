import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Lock, Sparkles, Trash2, Unlock, X } from 'lucide-react';
import { timetableApi, timetableEditorApi } from '../../api/client';
import { useTimetableEditor } from '../../hooks/useTimetableEditor';
import { EditConflict, EditOperation, ResourceOption, TimetableEntry } from '../../types';
import { DAYS, DAY_LABELS, ScheduleSlot, timeLabel } from '../../utils/schedule';

type Editor = ReturnType<typeof useTimetableEditor>;

export function ConflictList({ conflicts }: { conflicts: EditConflict[] }) {
  if (!conflicts.length) return null;
  return (
    <ul className="mt-2 space-y-1 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-800">
      {conflicts.map((c, i) => (
        <li key={i} className="flex gap-1.5"><AlertTriangle size={13} className="mt-0.5 shrink-0" />{c.message}</li>
      ))}
    </ul>
  );
}

interface Props {
  runId: number;
  entry: TimetableEntry;
  blockLength: number;
  subjectName: string;
  audience: string;
  slots: ScheduleSlot[];
  editor: Editor;
  /** False on a published timetable: shown read-only until a draft is opened. */
  editable: boolean;
  onClose: () => void;
  onNotice: (message: string, kind: 'ok' | 'error') => void;
}

export function EntryEditorPanel({ runId, entry, blockLength, subjectName, audience, slots, editor, editable, onClose, onNotice }: Props) {
  const group = entry.session_group || `row:${entry.id}`;
  const [day, setDay] = useState(entry.day);
  const [period, setPeriod] = useState(entry.period);
  const [moveCheck, setMoveCheck] = useState<{ ok: boolean; violations: EditConflict[] } | null>(null);
  const [suggestions, setSuggestions] = useState<Array<{ day: string; period: number }>>([]);
  const [teachers, setTeachers] = useState<ResourceOption[]>([]);
  const [rooms, setRooms] = useState<ResourceOption[]>([]);
  const [teacherId, setTeacherId] = useState(entry.teacher_id);
  const [roomId, setRoomId] = useState(entry.room_id);
  const [allSessions, setAllSessions] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [conflicts, setConflicts] = useState<EditConflict[]>([]);
  const [nlText, setNlText] = useState('');
  const [nlBusy, setNlBusy] = useState(false);
  const [nlNote, setNlNote] = useState<string | null>(null);

  const periodsForDay = useMemo(
    () => slots.filter((s) => s.day === day).sort((a, b) => a.period_index - b.period_index),
    [slots, day],
  );
  const moved = day !== entry.day || period !== entry.period;

  useEffect(() => {
    if (!editable) return;
    timetableEditorApi.options(runId, group).then((res) => {
      setTeachers(res.data.teachers);
      setRooms(res.data.rooms);
    }).catch(() => undefined);
    timetableEditorApi.freeSlots(runId, group, 5).then((res) => setSuggestions(res.data)).catch(() => undefined);
  }, [runId, group, editable]);

  // Live dry-run of the chosen slot so the admin sees the clash BEFORE applying.
  useEffect(() => {
    if (!editable || !moved) { setMoveCheck(null); return; }
    const timer = setTimeout(async () => {
      const res = await editor.check([{ type: 'move', session_group: group, day, period }]);
      setMoveCheck(res);
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day, period, moved, group, editable]);

  const submit = async (ops: EditOperation[], success: string) => {
    setConflicts([]);
    const out = await editor.apply(ops);
    if (out.ok) {
      onNotice(success, 'ok');
      onClose();
    } else if (out.violations.length) {
      setConflicts(out.violations);
    } else {
      onNotice(out.error || 'The change could not be applied.', 'error');
    }
  };

  const askAI = async () => {
    if (!nlText.trim()) return;
    setNlBusy(true);
    setNlNote(null);
    try {
      const res = await timetableApi.parseMoveNL(runId, {
        text: nlText, subject_id: entry.subject_id, current_day: entry.day, current_period: entry.period,
      });
      if (res.data.new_day && res.data.new_period) {
        setDay(res.data.new_day);
        setPeriod(res.data.new_period);
      }
      setNlNote(res.data.note || (res.data.new_day ? 'Filled in below - it is checked before you apply.' : "Couldn't pick a slot - choose one below."));
    } catch (err: any) {
      setNlNote(err?.response?.data?.detail || 'AI is unavailable. Pick a day/period below instead.');
    } finally {
      setNlBusy(false);
    }
  };

  const optionLabel = (o: ResourceOption) => (o.free ? o.name : `${o.name} - busy`);
  const selected = (list: ResourceOption[], id: string) => list.find((o) => o.id === id);
  const teacherSel = selected(teachers, teacherId);
  const roomSel = selected(rooms, roomId);

  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-sm overflow-y-auto border-l border-gray-200 bg-white p-5 shadow-xl">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="text-lg font-bold text-gray-900">{subjectName}</h3>
          <p className="text-sm text-gray-500">
            {audience} · {DAY_LABELS[entry.day] || entry.day}, {timeLabel(slots.find((s) => s.day === entry.day && s.period_index === entry.period)) || `Period ${entry.period}`}
            {blockLength > 1 && ` · ${blockLength} periods`}
          </p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close"><X size={20} /></button>
      </div>

      {!editable ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          This timetable is published. Click "Edit timetable" to open an editable draft - the published version stays untouched until you publish the draft.
        </p>
      ) : (
        <div className="space-y-5">
          <ConflictList conflicts={conflicts} />
          {entry.is_locked && (
            <p className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 p-2 text-xs text-gray-700">
              <Lock size={14} /> Locked - unlock it to move, reassign or delete. Regeneration keeps it exactly here.
            </p>
          )}

          <section>
            <h4 className="mb-2 text-sm font-semibold text-gray-800">Move to</h4>
            <div className="grid grid-cols-2 gap-2">
              <select value={day} onChange={(e) => { setDay(e.target.value); const first = slots.filter((s) => s.day === e.target.value).sort((a, b) => a.period_index - b.period_index)[0]; if (first) setPeriod(first.period_index); }}
                disabled={entry.is_locked} className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm">
                {DAYS.filter((d) => slots.some((s) => s.day === d)).map((d) => <option key={d} value={d}>{DAY_LABELS[d]}</option>)}
              </select>
              <select value={period} onChange={(e) => setPeriod(parseInt(e.target.value, 10))} disabled={entry.is_locked}
                className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm">
                {periodsForDay.map((s) => <option key={s.period_index} value={s.period_index}>{timeLabel(s)}</option>)}
              </select>
            </div>
            {moved && moveCheck && (moveCheck.ok
              ? <p className="mt-2 flex items-center gap-1.5 text-xs text-green-700"><CheckCircle2 size={14} /> No conflicts - this slot is free.</p>
              : <ConflictList conflicts={moveCheck.violations} />)}
            {suggestions.length > 0 && !entry.is_locked && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                <span className="text-xs text-gray-500">Free slots:</span>
                {suggestions.map((s) => (
                  <button key={`${s.day}${s.period}`} type="button" onClick={() => { setDay(s.day); setPeriod(s.period); }}
                    className="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100">
                    {s.day} P{s.period}
                  </button>
                ))}
              </div>
            )}
            <button disabled={!moved || editor.busy || (moveCheck !== null && !moveCheck.ok)}
              onClick={() => submit([{ type: 'move', session_group: group, day, period }], 'Class moved.')}
              className="mt-3 w-full rounded-lg bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              Move class
            </button>
          </section>

          <section>
            <h4 className="mb-2 text-sm font-semibold text-gray-800">Teacher</h4>
            <select value={teacherId} onChange={(e) => setTeacherId(e.target.value)} disabled={entry.is_locked}
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm">
              {teachers.length === 0 && <option value={entry.teacher_id}>{entry.teacher_id}</option>}
              {teachers.map((o) => <option key={o.id} value={o.id} disabled={!o.free}>{optionLabel(o)}</option>)}
            </select>
            {teacherSel && !teacherSel.free && <ConflictList conflicts={teacherSel.reasons.map((m) => ({ type: 'BUSY', message: m }))} />}
            <label className="mt-2 flex items-center gap-2 text-xs text-gray-600">
              <input type="checkbox" checked={allSessions} onChange={(e) => setAllSessions(e.target.checked)} />
              Apply to every session of this subject for this class
            </label>
            <button disabled={teacherId === entry.teacher_id || editor.busy}
              onClick={() => submit([{ type: 'change_teacher', session_group: group, teacher_id: teacherId, scope: allSessions ? 'all_sessions' : 'session' }], 'Teacher changed.')}
              className="mt-2 w-full rounded-lg border border-blue-600 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50">
              Change teacher
            </button>
          </section>

          <section>
            <h4 className="mb-2 text-sm font-semibold text-gray-800">Room</h4>
            <select value={roomId} onChange={(e) => setRoomId(e.target.value)} disabled={entry.is_locked}
              className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm">
              {rooms.length === 0 && <option value={entry.room_id}>{entry.room_id}</option>}
              {rooms.map((o) => <option key={o.id} value={o.id} disabled={!o.free}>{optionLabel(o)}</option>)}
            </select>
            {roomSel && !roomSel.free && <ConflictList conflicts={roomSel.reasons.map((m) => ({ type: 'BUSY', message: m }))} />}
            <button disabled={roomId === entry.room_id || editor.busy}
              onClick={() => submit([{ type: 'change_room', session_group: group, room_id: roomId }], 'Room changed.')}
              className="mt-2 w-full rounded-lg border border-blue-600 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50">
              Change room
            </button>
          </section>

          <section className="flex gap-2">
            <button disabled={editor.busy}
              onClick={() => submit([{ type: entry.is_locked ? 'unlock' : 'lock', session_group: group }], entry.is_locked ? 'Class unlocked.' : 'Class locked.')}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-gray-300 py-1.5 text-sm hover:bg-gray-50">
              {entry.is_locked ? <><Unlock size={15} /> Unlock</> : <><Lock size={15} /> Lock in place</>}
            </button>
            {confirmDelete ? (
              <button disabled={editor.busy} onClick={() => submit([{ type: 'delete', session_group: group }], 'Class deleted.')}
                className="flex-1 rounded-lg bg-red-600 py-1.5 text-sm font-medium text-white hover:bg-red-700">Confirm delete</button>
            ) : (
              <button onClick={() => setConfirmDelete(true)}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-red-300 py-1.5 text-sm text-red-700 hover:bg-red-50">
                <Trash2 size={15} /> Delete
              </button>
            )}
          </section>

          <section className="rounded-lg border border-purple-200 bg-purple-50 p-3">
            <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-purple-900">
              <Sparkles size={14} /> Or describe where to move it
            </label>
            <div className="flex gap-2">
              <input value={nlText} onChange={(e) => setNlText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && askAI()}
                placeholder='e.g. "Wednesday afternoon"' className="flex-1 rounded-lg border border-purple-300 px-2 py-1.5 text-sm" />
              <button onClick={askAI} disabled={nlBusy || !nlText.trim()}
                className="rounded-lg bg-purple-600 px-3 py-1.5 text-sm text-white hover:bg-purple-700 disabled:opacity-50">{nlBusy ? '...' : 'Ask'}</button>
            </div>
            {nlNote && <p className="mt-1.5 text-xs text-purple-900">{nlNote}</p>}
          </section>
        </div>
      )}
    </aside>
  );
}
