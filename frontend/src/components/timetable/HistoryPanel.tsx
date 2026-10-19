import { History, X } from 'lucide-react';
import { EditHistoryItem } from '../../types';

interface Props {
  items: EditHistoryItem[];
  onClose: () => void;
}

const when = (iso: string | null) => {
  if (!iso) return '';
  // SQLite returns UTC without a zone marker.
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
};

const LABEL: Record<string, string> = { timetable_edit: 'Edit', timetable_undo: 'Undo', timetable_redo: 'Redo' };

export function HistoryPanel({ items, onClose }: Props) {
  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-sm overflow-y-auto border-l border-gray-200 bg-white p-5 shadow-xl">
      <div className="mb-4 flex items-start justify-between">
        <h3 className="flex items-center gap-2 text-lg font-bold text-gray-900"><History size={18} /> Change log</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close"><X size={20} /></button>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">No manual changes have been made to this draft yet.</p>
      ) : (
        <ol className="space-y-2">
          {items.map((item) => (
            <li key={item.id} className={`rounded-lg border p-2.5 text-sm ${item.undone ? 'border-gray-200 bg-gray-50 text-gray-400 line-through' : 'border-gray-200'}`}>
              <div className="flex justify-between text-xs text-gray-500">
                <span className="font-medium">{LABEL[item.action] || item.action}</span>
                <span>{when(item.created_at)}</span>
              </div>
              <div className="mt-0.5 text-gray-800">{item.reason || '(no description)'}</div>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}
