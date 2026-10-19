interface Props {
  /** 24-hour "HH:MM" (what the API stores), or '' when unset. */
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** 12-hour time picker. Browsers render <input type="time"> using the OS locale, so it can't be forced to 12-hour. */
export function TimeInput({ value, onChange, disabled, className = '' }: Props) {
  const match = /^(\d{1,2}):(\d{2})/.exec(value || '');
  const h24 = match ? Number(match[1]) : null;
  const minute = match ? match[2] : '00';
  const ampm = h24 !== null && h24 >= 12 ? 'PM' : 'AM';
  const hour12 = h24 === null ? '' : String(h24 % 12 || 12);

  const emit = (h: string, m: string, p: string) => {
    if (!h) return onChange('');
    onChange(`${pad((Number(h) % 12) + (p === 'PM' ? 12 : 0))}:${m}`);
  };

  const select = 'bg-transparent focus:outline-none disabled:text-gray-400';
  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      <select aria-label="Hour" disabled={disabled} value={hour12} onChange={(e) => emit(e.target.value, minute, ampm)} className={select}>
        <option value="">--</option>
        {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={String(i + 1)}>{i + 1}</option>)}
      </select>
      :
      <select aria-label="Minute" disabled={disabled} value={minute} onChange={(e) => emit(hour12 || '12', e.target.value, ampm)} className={select}>
        {Array.from({ length: 60 }, (_, i) => <option key={i} value={pad(i)}>{pad(i)}</option>)}
      </select>
      <select aria-label="AM or PM" disabled={disabled} value={ampm} onChange={(e) => emit(hour12 || '12', minute, e.target.value)} className={select}>
        <option>AM</option>
        <option>PM</option>
      </select>
    </span>
  );
}
