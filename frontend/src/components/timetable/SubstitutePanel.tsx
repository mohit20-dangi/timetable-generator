import { useEffect, useMemo, useState } from 'react';
import { UserX, X } from 'lucide-react';
import { timetableEditorApi } from '../../api/client';
import { useTimetableEditor } from '../../hooks/useTimetableEditor';
import { EditConflict, EditOperation, ResourceOption, Teacher, TimetableEntry } from '../../types';
import { DAYS, DAY_LABELS } from '../../utils/schedule';
import { ConflictList } from './EntryEditorPanel';

type Editor = ReturnType<typeof useTimetableEditor>;

interface Props {
  runId: number;
  entries: TimetableEntry[];
  teachers: Record<string, Teacher>;
  initialTeacherId?: string;
  subjectName: (id: string) => string;
  audienceLabel: (entry: TimetableEntry) => string;
  editor: Editor;
  onClose: () => void;
  onNotice: (message: string, kind: 'ok' | 'error') => void;
}

const groupOf = (e: TimetableEntry) => e.session_group || `row:${e.id}`;

/**
 * "Teacher X can't make it": lists X's classes (for one day or all week) and
 * offers, for each, only replacement teachers who are qualified AND free at
 * that time. Applied as one atomic edit.
 *
 * Note the scheduling rule "one teacher per subject per class": by default a
 * replacement takes over every session of that subject for that class. Pick
 * "just this session" only if the subject has a single session - otherwise
 * the conflict check will (correctly) refuse it.
 */
export function SubstitutePanel({ runId, entries, teachers, initialTeacherId, subjectName, audienceLabel, editor, onClose, onNotice }: Props) {
  const teacherIds = useMemo(() => [...new Set(entries.map((e) => e.teacher_id))].filter((id) => teachers[id]), [entries, teachers]);
  const [absent, setAbsent] = useState(initialTeacherId && teacherIds.includes(initialTeacherId) ? initialTeacherId : teacherIds[0] || '');
  const [day, setDay] = useState('all');
  const [wholeSubject, setWholeSubject] = useState(true);
  const [options, setOptions] = useState<Record<string, ResourceOption[]>>({});
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [conflicts, setConflicts] = useState<EditConflict[]>([]);

  const blocks = useMemo(() => {
    const seen = new Map<string, TimetableEntry>();
    entries
      .filter((e) => e.teacher_id === absent && (day === 'all' || e.day === day))
      .forEach((e) => {
        const g = groupOf(e);
        const cur = seen.get(g);
        if (!cur || e.period < cur.period) seen.set(g, e);
      });
    return [...seen.values()].sort((a, b) => DAYS.indexOf(a.day as any) - DAYS.indexOf(b.day as any) || a.period - b.period);
  }, [entries, absent, day]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setConflicts([]);
    Promise.all(blocks.map((b) =>
      timetableEditorApi.options(runId, groupOf(b), wholeSubject ? 'all_sessions' : 'session')
        .then((res) => [groupOf(b), (res.data.teachers as ResourceOption[]).filter((t) => t.id !== absent)] as const)
        .catch(() => [groupOf(b), [] as ResourceOption[]] as const),
    )).then((pairs) => {
      if (cancelled) return;
      const opts: Record<string, ResourceOption[]> = {};
      const pick: Record<string, string> = {};
      pairs.forEach(([g, list]) => {
        opts[g] = list;
        pick[g] = list.find((t) => t.free)?.id || '';
      });
      setOptions(opts);
      setChoice(pick);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [runId, blocks, wholeSubject, absent]);

  const chosen = blocks.filter((b) => choice[groupOf(b)]);

  const apply = async () => {
    // With "every session", two blocks of the same subject+class must agree on one replacement.
    const done = new Set<string>();
    const ops: EditOperation[] = [];
    chosen.forEach((b) => {
      const key = wholeSubject ? `${b.subject_id}|${b.batch_id || b.section_id}` : groupOf(b);
      if (done.has(key)) return;
      done.add(key);
      ops.push({ type: 'change_teacher', session_group: groupOf(b), teacher_id: choice[groupOf(b)], scope: wholeSubject ? 'all_sessions' : 'session' });
    });
    if (!ops.length) return;
    const out = await editor.apply(ops, `Substitute for ${teachers[absent]?.name || absent}`);
    if (out.ok) { onNotice(`${ops.length} class${ops.length === 1 ? '' : 'es'} reassigned.`, 'ok'); onClose(); }
    else if (out.violations.length) setConflicts(out.violations);
    else onNotice(out.error || 'Nothing was changed.', 'error');
  };

  const field = 'w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm';
  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-gray-200 bg-white p-5 shadow-xl">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-lg font-bold text-gray-900"><UserX size={18} /> Substitute teacher</h3>
          <p className="text-sm text-gray-500">Only qualified teachers who are free at that time are offered.</p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close"><X size={20} /></button>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="block text-xs font-medium text-gray-600">Teacher who is away
          <select value={absent} onChange={(e) => setAbsent(e.target.value)} className={field}>
            {teacherIds.map((id) => <option key={id} value={id}>{teachers[id].name}</option>)}
          </select>
        </label>
        <label className="block text-xs font-medium text-gray-600">Day
          <select value={day} onChange={(e) => setDay(e.target.value)} className={field}>
            <option value="all">Whole week</option>
            {DAYS.filter((d) => entries.some((e) => e.day === d)).map((d) => <option key={d} value={d}>{DAY_LABELS[d]}</option>)}
          </select>
        </label>
      </div>
      <label className="mt-2 flex items-center gap-2 text-xs text-gray-600">
        <input type="checkbox" checked={wholeSubject} onChange={(e) => setWholeSubject(e.target.checked)} />
        Replacement takes every session of that subject for the class (recommended)
      </label>

      <div className="mt-4 space-y-2">
        {loading && <p className="text-xs text-blue-700">Checking who is free...</p>}
        {!loading && blocks.length === 0 && <p className="text-sm text-gray-500">{teachers[absent]?.name || 'This teacher'} has no classes {day === 'all' ? 'in this timetable' : 'that day'}.</p>}
        {blocks.map((b) => {
          const g = groupOf(b);
          const list = options[g] || [];
          return (
            <div key={g} className="rounded-lg border border-gray-200 p-2.5">
              <div className="text-sm font-medium text-gray-900">{subjectName(b.subject_id)} <span className="font-normal text-gray-500">· {audienceLabel(b)}</span></div>
              <div className="mb-1.5 text-xs text-gray-500">{DAY_LABELS[b.day] || b.day}, period {b.period}</div>
              <select value={choice[g] || ''} onChange={(e) => setChoice({ ...choice, [g]: e.target.value })} className={field}>
                <option value="">Leave as is</option>
                {list.map((t) => <option key={t.id} value={t.id} disabled={!t.free}>{t.free ? t.name : `${t.name} - busy`}</option>)}
              </select>
              {!loading && !list.some((t) => t.free) && <p className="mt-1 text-xs text-red-700">No qualified teacher is free for this class.</p>}
            </div>
          );
        })}
      </div>

      <ConflictList conflicts={conflicts} />
      <button onClick={apply} disabled={editor.busy || chosen.length === 0}
        className="mt-4 w-full rounded-lg bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
        Reassign {chosen.length} class{chosen.length === 1 ? '' : 'es'}
      </button>
    </aside>
  );
}
