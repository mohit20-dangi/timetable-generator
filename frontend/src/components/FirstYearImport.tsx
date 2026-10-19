import { useCallback, useEffect, useMemo, useState } from 'react';
import { formatTime } from '../utils/schedule';
import { AlertCircle, AlertTriangle, CheckCircle, FileText, Loader2, Trash2, Upload } from 'lucide-react';
import { firstYearImportApi } from '../api/client';
import { useDepartment } from '../context/DepartmentContext';
import { FirstYearManualEntry } from './FirstYearManualEntry';
import {
  FirstYearApplyRow, FirstYearLock, FirstYearPreview, FirstYearPreviewRow,
} from '../types';

// What the admin decided for one proposed lock. `picks` answers the
// ambiguous / half-read codes: hit code -> chosen teacher id ('' = not ours).
interface RowChoice {
  checked: boolean;
  lockRoom: boolean;
  picks: Record<string, string>;
}

const errorText = (err: any, fallback: string) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

/** Teacher ids this row would lock: every confident match plus whatever the
 * admin picked for the uncertain ones. */
function lockedTeacherIds(row: FirstYearPreviewRow, choice: RowChoice): string[] {
  const ids = new Set<string>();
  row.teachers.forEach((hit) => {
    if (hit.status === 'matched' && hit.teacher_id) ids.add(hit.teacher_id);
    else if (choice.picks[hit.code]) ids.add(choice.picks[hit.code]);
  });
  return [...ids];
}

export function FirstYearImport() {
  const { departmentId } = useDepartment();
  const [file, setFile] = useState<File | null>(null);
  const [isReading, setIsReading] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [preview, setPreview] = useState<FirstYearPreview | null>(null);
  const [choices, setChoices] = useState<Record<string, RowChoice>>({});
  const [locks, setLocks] = useState<FirstYearLock[]>([]);

  const loadLocks = useCallback(() => {
    if (!departmentId) return;
    firstYearImportApi.list(departmentId).then((r) => setLocks(r.data)).catch(() => setLocks([]));
  }, [departmentId]);

  useEffect(() => { loadLocks(); }, [loadLocks]);

  const handleRead = async () => {
    if (!file || !departmentId) return;
    setIsReading(true);
    setError('');
    setMessage('');
    setPreview(null);
    try {
      const response = await firstYearImportApi.preview(file, departmentId);
      const data: FirstYearPreview = response.data;
      setPreview(data);
      const initial: Record<string, RowChoice> = {};
      data.rows.forEach((row) => {
        const hasMatch = row.teachers.some((t) => t.status === 'matched');
        initial[row.id] = { checked: hasMatch || !!row.room_id, lockRoom: !!row.room_id, picks: {} };
      });
      setChoices(initial);
    } catch (err: any) {
      setError(errorText(err, 'Could not read the PDF.'));
    } finally {
      setIsReading(false);
    }
  };

  const applyRows = useMemo<FirstYearApplyRow[]>(() => {
    if (!preview) return [];
    return preview.rows.flatMap((row) => {
      const choice = choices[row.id];
      if (!choice?.checked) return [];
      const teacher_ids = lockedTeacherIds(row, choice);
      const room_id = choice.lockRoom ? row.room_id : null;
      if (teacher_ids.length === 0 && !room_id) return [];
      return [{
        periods: row.periods, teacher_ids, room_id,
        reason: `1st yr ${row.section} ${row.subject}${row.room_text ? ` · ${row.room_text}` : ''}`,
        tile: {
          section: row.section, subject: row.subject, batches: row.batches, faculty: row.faculty,
          room_text: row.room_text, start: row.start, end: row.end,
        },
      }];
    });
  }, [preview, choices]);

  const handleApply = async () => {
    if (!departmentId) return;
    setIsApplying(true);
    setError('');
    try {
      const response = await firstYearImportApi.apply(departmentId, applyRows);
      setMessage(
        `Saved ${response.data.teacher_locks} teacher and ${response.data.room_locks} room time-slot locks. ` +
        'Every timetable you generate from now on avoids them.');
      setPreview(null);
      setFile(null);
      loadLocks();
    } catch (err: any) {
      setError(errorText(err, 'Could not save the locks.'));
    } finally {
      setIsApplying(false);
    }
  };

  const handleClear = async () => {
    if (!departmentId || !window.confirm('Remove all first-year locks? Generated timetables will no longer avoid them.')) return;
    await firstYearImportApi.clear(departmentId);
    setMessage('First-year locks removed.');
    loadLocks();
  };

  const handleRemoveOne = async (lock: FirstYearLock) => {
    if (!departmentId) return;
    try {
      await firstYearImportApi.removeOne(departmentId, lock.id);
      loadLocks();
    } catch (err: any) {
      setError(errorText(err, 'Could not remove that lock.'));
    }
  };

  const update = (id: string, patch: Partial<RowChoice>) =>
    setChoices((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  const lockCounts = useMemo(() => ({
    teacher: locks.filter((l) => l.resource_type === 'teacher').length,
    room: locks.filter((l) => l.resource_type === 'room').length,
  }), [locks]);
  const pagesWithWarnings = preview?.pages.filter((p) => p.warnings.length) ?? [];
  const needsDecision = preview?.rows.filter((r) => choices[r.id]?.checked &&
    r.teachers.some((t) => t.status !== 'matched' && !choices[r.id].picks[t.code])).length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">First-year timetable locks</h2>
        <p className="text-sm text-gray-600 mt-1">
          The first-year timetable is made centrally. Upload its PDF (all sections) and the classes taught by
          your teachers, or held in your rooms, become hard locks that years 2-4 are never scheduled over.
          Teachers are matched by the initials saved in <em>Setup → Teachers</em>.
        </p>
      </div>

      <div className="rounded-lg border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="text-sm">
            <span className="font-medium text-gray-900">Current locks: </span>
            {locks.length === 0
              ? <span className="text-gray-600">none yet</span>
              : <span className="text-gray-700">{lockCounts.teacher} teacher slots, {lockCounts.room} room slots</span>}
          </div>
          {locks.length > 0 && (
            <button onClick={handleClear} className="inline-flex items-center gap-1 text-sm text-red-600 hover:text-red-800">
              <Trash2 size={14} /> Clear all locks
            </button>
          )}
        </div>
        {locks.length > 0 && (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-gray-700">Show and remove individual locks</summary>
            <ul className="mt-2 max-h-72 overflow-y-auto divide-y divide-gray-100">
              {locks.map((l) => (
                <li key={l.id} className="py-1 flex items-center gap-3">
                  <span className="w-14 text-xs uppercase text-gray-400">{l.resource_type}</span>
                  <span className="flex-1">
                    <strong>{l.resource_name}</strong> · {l.day} P{l.period}
                    {l.reason && <span className="text-gray-500"> · {l.reason}</span>}
                  </span>
                  <button
                    onClick={() => handleRemoveOne(l)} aria-label={`Remove lock for ${l.resource_name} ${l.day} period ${l.period}`}
                    className="text-gray-400 hover:text-red-600"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {departmentId && (
        <FirstYearManualEntry
          departmentId={departmentId}
          onSaved={(summary) => { setMessage(summary); setError(''); loadLocks(); }}
        />
      )}

      <div className="space-y-3">
        <label className="flex items-center gap-3 border-2 border-dashed border-gray-300 rounded-lg p-4 cursor-pointer hover:border-blue-400">
          <FileText className="text-gray-400" size={22} />
          <span className="text-sm text-gray-700 flex-1">
            {file ? file.name : 'Choose the first-year timetable PDF (scanned is fine)'}
          </span>
          <input
            type="file" accept="application/pdf,.pdf" className="hidden"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); setMessage(''); setError(''); }}
          />
        </label>
        <button
          onClick={handleRead} disabled={!file || !departmentId || isReading}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {isReading ? <Loader2 className="animate-spin" size={16} /> : <Upload size={16} />}
          {isReading ? 'Reading the PDF… this can take a few minutes' : 'Read PDF'}
        </button>
      </div>

      {error && (
        <div className="flex gap-2 p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-800">
          <AlertCircle size={18} className="shrink-0" /> <span>{error}</span>
        </div>
      )}
      {message && (
        <div className="flex gap-2 p-3 rounded-md bg-green-50 border border-green-200 text-sm text-green-800">
          <CheckCircle size={18} className="shrink-0" /> <span>{message}</span>
        </div>
      )}

      {preview && (
        <div className="space-y-5">
          <div className="text-sm text-gray-700">
            Read <strong>{preview.pages.length}</strong> page{preview.pages.length === 1 ? '' : 's'}
            {' '}({preview.pages.map((p) => `${p.section}: ${p.cells} classes`).join(' · ')}).
            Found <strong>{preview.rows.length}</strong> classes that involve your teachers or rooms.
            Check them against the PDF before saving.
          </div>

          {(pagesWithWarnings.length > 0 || preview.warnings.length > 0) && (
            <div className="p-3 rounded-md bg-amber-50 border border-amber-200 text-sm text-amber-900">
              <div className="flex items-center gap-2 font-medium"><AlertTriangle size={16} /> Check these by hand</div>
              <ul className="list-disc pl-5 mt-1 space-y-0.5">
                {preview.warnings.map((w) => <li key={w}>{w}</li>)}
              </ul>
            </div>
          )}

          {preview.unreadable.length > 0 && (
            <details className="p-3 rounded-md bg-amber-50 border border-amber-200 text-sm text-amber-900" open>
              <summary className="cursor-pointer font-medium">
                {preview.unreadable.length} class{preview.unreadable.length === 1 ? '' : 'es'} with faculty text the OCR could not read
              </summary>
              <p className="mt-1">
                These may or may not be your teachers. Look at each one on the PDF; if it is one of yours, add the lock
                by hand in the scheduling rules.
              </p>
              <ul className="list-disc pl-5 mt-1 space-y-0.5">
                {preview.unreadable.map((u, i) => (
                  <li key={i}>Page {u.page} ({u.section}) · {u.day} {formatTime(u.start)}–{formatTime(u.end)} · {u.subject} · read as “{u.text}”</li>
                ))}
              </ul>
            </details>
          )}

          <div className="overflow-x-auto border border-gray-200 rounded-lg">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="p-2 w-8">
                    <input
                      type="checkbox"
                      aria-label="Select all classes"
                      checked={preview.rows.length > 0 && preview.rows.every((r) => choices[r.id]?.checked)}
                      onChange={(e) => setChoices((prev) => Object.fromEntries(
                        Object.entries(prev).map(([id, c]) => [id, { ...c, checked: e.target.checked }]),
                      ))}
                    />
                  </th>
                  <th className="p-2">Page</th>
                  <th className="p-2">When</th>
                  <th className="p-2">Subject</th>
                  <th className="p-2">Our teachers</th>
                  <th className="p-2">Room</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => {
                  const choice = choices[row.id];
                  if (!choice) return null;
                  return (
                    <tr key={row.id} className={`border-t border-gray-100 align-top ${choice.checked ? '' : 'opacity-50'}`}>
                      <td className="p-2">
                        <input type="checkbox" checked={choice.checked} onChange={(e) => update(row.id, { checked: e.target.checked })} />
                      </td>
                      <td className="p-2 whitespace-nowrap">{row.page} · {row.section}</td>
                      <td className="p-2 whitespace-nowrap">{row.day} {formatTime(row.start)}–{formatTime(row.end)}</td>
                      <td className="p-2">
                        {row.subject}
                        <div className="text-xs text-gray-500 max-w-xs">{row.cell_text}</div>
                      </td>
                      <td className="p-2 space-y-1">
                        {row.teachers.length === 0 && <span className="text-gray-400">—</span>}
                        {row.teachers.map((hit) => hit.status === 'matched' ? (
                          <div key={hit.code} className="text-green-700">{hit.teacher_name} <span className="text-gray-400">({hit.code})</span></div>
                        ) : (
                          <div key={hit.code}>
                            <select
                              value={choice.picks[hit.code] ?? ''}
                              onChange={(e) => update(row.id, { picks: { ...choice.picks, [hit.code]: e.target.value } })}
                              className="border border-amber-300 bg-amber-50 rounded px-1 py-0.5 text-xs"
                            >
                              <option value="">{hit.status === 'unread' ? `“${hit.code}” unclear – not ours` : `“${hit.code}” – which teacher?`}</option>
                              {hit.candidates.map((c) => <option key={c.teacher_id} value={c.teacher_id}>{c.name} ({c.initials})</option>)}
                            </select>
                          </div>
                        ))}
                      </td>
                      <td className="p-2 whitespace-nowrap">
                        {row.room_id ? (
                          <label className="inline-flex items-center gap-1">
                            <input type="checkbox" checked={choice.lockRoom} onChange={(e) => update(row.id, { lockRoom: e.target.checked })} />
                            lock {row.room_name}
                          </label>
                        ) : <span className="text-gray-400">{row.room_text || '—'}</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {preview.unmatched_codes.length > 0 && (
            <details className="text-sm text-gray-700">
              <summary className="cursor-pointer font-medium">
                {preview.unmatched_codes.length} faculty codes on the PDF are not in your department (ignored)
              </summary>
              <p className="mt-1 text-gray-500">
                If one of these is actually yours, set that teacher’s initials to the code in Setup → Teachers and read the PDF again.
              </p>
              <ul className="mt-1 grid grid-cols-2 md:grid-cols-3 gap-x-4">
                {preview.unmatched_codes.map((c) => (
                  <li key={c.code}><strong>{c.code}</strong> {c.name ? `· ${c.name}` : ''} <span className="text-gray-400">×{c.count}</span></li>
                ))}
              </ul>
            </details>
          )}

          <div className="flex items-center gap-4 flex-wrap">
            <button
              onClick={handleApply} disabled={isApplying || applyRows.length === 0}
              className="inline-flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md text-sm hover:bg-green-700 disabled:opacity-50"
            >
              {isApplying && <Loader2 className="animate-spin" size={16} />}
              Save {applyRows.length} class{applyRows.length === 1 ? '' : 'es'} as locks
            </button>
            <span className="text-xs text-gray-500">
              Saving replaces the first-year locks already in place.
              {needsDecision > 0 && ` ${needsDecision} ticked class${needsDecision === 1 ? ' has' : 'es have'} a teacher still to choose; it will only lock the teachers that are settled.`}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
