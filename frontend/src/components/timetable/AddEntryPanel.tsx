import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, X } from 'lucide-react';
import { subjectsApi } from '../../api/client';
import { useTimetableEditor } from '../../hooks/useTimetableEditor';
import { AcademicYear, EditConflict, EditOperation, Room, Section, Subject, Teacher } from '../../types';
import { sectionLabel } from '../../utils/sectionLabel';
import { DAYS, DAY_LABELS, ScheduleSlot, timeLabel } from '../../utils/schedule';
import { ConflictList } from './EntryEditorPanel';

type Editor = ReturnType<typeof useTimetableEditor>;

export interface AddDraft {
  day: string;
  period: number;
  sectionId?: string;
  subjectId?: string;
}

interface Props {
  initial: AddDraft;
  sections: Section[];
  years: Record<string, AcademicYear>;
  subjects: Record<string, Subject>;
  /** section id -> subject ids assigned to it */
  sectionSubjects: Record<string, string[]>;
  /** section id -> lab batch ids */
  batchesBySection: Record<string, string[]>;
  teachers: Teacher[];
  rooms: Room[];
  slots: ScheduleSlot[];
  editor: Editor;
  onClose: () => void;
  onNotice: (message: string, kind: 'ok' | 'error') => void;
}

export function AddEntryPanel({ initial, sections, years, subjects, sectionSubjects, batchesBySection, teachers, rooms, slots, editor, onClose, onNotice }: Props) {
  const [sectionId, setSectionId] = useState(initial.sectionId || sections[0]?.id || '');
  const subjectChoices = useMemo(
    () => (sectionSubjects[sectionId] || []).map((id) => subjects[id]).filter(Boolean),
    [sectionSubjects, sectionId, subjects],
  );
  const [subjectId, setSubjectId] = useState(initial.subjectId || '');
  const [batchId, setBatchId] = useState('');
  const [teacherId, setTeacherId] = useState('');
  const [roomId, setRoomId] = useState('');
  const [day, setDay] = useState(initial.day);
  const [period, setPeriod] = useState(initial.period);
  const [duration, setDuration] = useState(1);
  const [qualified, setQualified] = useState<string[] | null>(null);
  const [check, setCheck] = useState<{ ok: boolean; violations: EditConflict[] } | null>(null);
  const [conflicts, setConflicts] = useState<EditConflict[]>([]);

  const subject = subjects[subjectId];
  const batches = batchesBySection[sectionId] || [];
  const needsBatch = subject?.type === 'lab' && batches.length > 0;

  // A new subject resets what depended on it.
  useEffect(() => {
    if (!subjectChoices.some((s) => s.id === subjectId)) setSubjectId(subjectChoices[0]?.id || '');
  }, [subjectChoices]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!subject) return;
    setDuration(Math.max(1, subject.periods_per_session || 1));
    setBatchId(needsBatch ? batches[0] : '');
    setQualified(null);
    subjectsApi.getTeachers(subject.id).then((res) => {
      const ids: string[] = res.data;
      setQualified(ids);
      setTeacherId((cur) => (ids.includes(cur) ? cur : ids[0] || ''));
    }).catch(() => setQualified([]));
    const suitable = rooms.filter((r) => !subject.requires_room_type || r.type === subject.requires_room_type);
    setRoomId((cur) => (suitable.some((r) => r.id === cur) ? cur : suitable[0]?.id || ''));
  }, [subjectId]); // eslint-disable-line react-hooks/exhaustive-deps

  const teacherOptions = teachers.filter((t) => qualified === null || qualified.includes(t.id));
  const roomOptions = rooms.filter((r) => !subject?.requires_room_type || r.type === subject.requires_room_type);
  const periodsForDay = slots.filter((s) => s.day === day).sort((a, b) => a.period_index - b.period_index);

  const operation = (): EditOperation | null => {
    if (!subjectId || !teacherId || !roomId || (needsBatch && !batchId)) return null;
    return {
      type: 'add', subject_id: subjectId, teacher_id: teacherId, room_id: roomId, day, period, duration,
      ...(needsBatch ? { batch_id: batchId } : { section_id: sectionId }),
    };
  };

  useEffect(() => {
    const op = operation();
    if (!op) { setCheck(null); return; }
    setConflicts([]);
    const timer = setTimeout(async () => setCheck(await editor.check([op])), 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionId, subjectId, batchId, teacherId, roomId, day, period, duration]);

  const add = async () => {
    const op = operation();
    if (!op) return;
    const out = await editor.apply([op]);
    if (out.ok) { onNotice('Class added.', 'ok'); onClose(); }
    else if (out.violations.length) setConflicts(out.violations);
    else onNotice(out.error || 'The class could not be added.', 'error');
  };

  const field = 'w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm';
  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-sm overflow-y-auto border-l border-gray-200 bg-white p-5 shadow-xl">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="text-lg font-bold text-gray-900">Add a class</h3>
          <p className="text-sm text-gray-500">Checked against every scheduling rule before it is added.</p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close"><X size={20} /></button>
      </div>
      <div className="space-y-3">
        <label className="block text-xs font-medium text-gray-600">Section
          <select value={sectionId} onChange={(e) => setSectionId(e.target.value)} className={field}>
            {sections.map((s) => <option key={s.id} value={s.id}>{sectionLabel(s, years)}</option>)}
          </select>
        </label>
        <label className="block text-xs font-medium text-gray-600">Subject
          <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)} className={field}>
            {subjectChoices.length === 0 && <option value="">No subjects assigned to this section</option>}
            {subjectChoices.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        {needsBatch && (
          <label className="block text-xs font-medium text-gray-600">Lab batch
            <select value={batchId} onChange={(e) => setBatchId(e.target.value)} className={field}>
              {batches.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
        )}
        <label className="block text-xs font-medium text-gray-600">Teacher {qualified && qualified.length === 0 && <span className="text-red-600">- nobody is qualified for this subject</span>}
          <select value={teacherId} onChange={(e) => setTeacherId(e.target.value)} className={field}>
            {teacherOptions.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
        <label className="block text-xs font-medium text-gray-600">Room
          <select value={roomId} onChange={(e) => setRoomId(e.target.value)} className={field}>
            {roomOptions.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.capacity})</option>)}
          </select>
        </label>
        <div className="grid grid-cols-3 gap-2">
          <label className="col-span-1 block text-xs font-medium text-gray-600">Day
            <select value={day} onChange={(e) => { setDay(e.target.value); const first = slots.filter((s) => s.day === e.target.value).sort((a, b) => a.period_index - b.period_index)[0]; if (first) setPeriod(first.period_index); }} className={field}>
              {DAYS.filter((d) => slots.some((s) => s.day === d)).map((d) => <option key={d} value={d}>{DAY_LABELS[d]}</option>)}
            </select>
          </label>
          <label className="col-span-1 block text-xs font-medium text-gray-600">Starts
            <select value={period} onChange={(e) => setPeriod(parseInt(e.target.value, 10))} className={field}>
              {periodsForDay.map((s) => <option key={s.period_index} value={s.period_index}>{timeLabel(s)}</option>)}
            </select>
          </label>
          <label className="col-span-1 block text-xs font-medium text-gray-600">Periods
            <select value={duration} onChange={(e) => setDuration(parseInt(e.target.value, 10))} className={field}>
              {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>

        {check && (check.ok
          ? <p className="flex items-center gap-1.5 text-xs text-green-700"><CheckCircle2 size={14} /> No conflicts.</p>
          : <ConflictList conflicts={check.violations} />)}
        <ConflictList conflicts={conflicts} />
        <button onClick={add} disabled={editor.busy || !check?.ok}
          className="w-full rounded-lg bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          Add class
        </button>
      </div>
    </aside>
  );
}
