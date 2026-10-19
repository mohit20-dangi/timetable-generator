import { CheckSquare, Square } from 'lucide-react';

interface Props {
  onSelectAll: () => void;
  onClear: () => void;
  disabled?: boolean;
}

const base =
  'inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md border transition-colors disabled:opacity-50';

export default function SelectAllButtons({ onSelectAll, onClear, disabled }: Props) {
  return (
    <div className="inline-flex items-center gap-2">
      <button type="button" onClick={onSelectAll} disabled={disabled} className={`${base} border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100`}>
        <CheckSquare size={13} /> Select all
      </button>
      <button type="button" onClick={onClear} disabled={disabled} className={`${base} border-gray-300 bg-white text-gray-600 hover:bg-gray-50`}>
        <Square size={13} /> Clear all
      </button>
    </div>
  );
}
