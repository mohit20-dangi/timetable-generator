import { Lock, Trash2, Unlock, X } from 'lucide-react';
import { Room, Teacher } from '../../types';

interface Props {
  count: number;
  teachers: Teacher[];
  rooms: Room[];
  busy: boolean;
  onLock: () => void;
  onUnlock: () => void;
  onDelete: () => void;
  onChangeTeacher: (teacherId: string) => void;
  onChangeRoom: (roomId: string) => void;
  onClear: () => void;
}

/**
 * Acts on every class selected with Shift+click as ONE atomic edit: either
 * all of them are accepted by the conflict check, or none are applied.
 */
export function BulkBar({ count, teachers, rooms, busy, onLock, onUnlock, onDelete, onChangeTeacher, onChangeRoom, onClear }: Props) {
  const btn = 'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm disabled:opacity-50';
  return (
    <div className="sticky top-2 z-30 mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 p-3 shadow-sm">
      <span className="text-sm font-medium text-blue-900">{count} class{count === 1 ? '' : 'es'} selected</span>
      <button disabled={busy} onClick={onLock} className={`${btn} border-gray-300 bg-white hover:bg-gray-50`}><Lock size={14} /> Lock</button>
      <button disabled={busy} onClick={onUnlock} className={`${btn} border-gray-300 bg-white hover:bg-gray-50`}><Unlock size={14} /> Unlock</button>
      <select disabled={busy} value="" onChange={(e) => e.target.value && onChangeTeacher(e.target.value)}
        className="rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-sm">
        <option value="">Give to teacher…</option>
        {teachers.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
      <select disabled={busy} value="" onChange={(e) => e.target.value && onChangeRoom(e.target.value)}
        className="rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-sm">
        <option value="">Move to room…</option>
        {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
      </select>
      <button disabled={busy} onClick={onDelete} className={`${btn} border-red-300 bg-white text-red-700 hover:bg-red-50`}><Trash2 size={14} /> Delete</button>
      <button onClick={onClear} className="ml-auto flex items-center gap-1 text-sm text-blue-800 hover:underline"><X size={14} /> Clear selection</button>
      <span className="w-full text-xs text-blue-800">Shift+click classes to add or remove them. All changes succeed together or none are applied.</span>
    </div>
  );
}
