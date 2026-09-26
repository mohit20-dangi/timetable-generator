import { useState, useRef, useEffect } from 'react';
import { HelpCircle } from 'lucide-react';

/** Replaces a paragraph of grey helper text under a field with a single
 * "What does this mean?" popover (Phase 3.10 visual pass copy rule). */
export function HelpPopover({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClickAway = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickAway);
    return () => document.removeEventListener('mousedown', onClickAway);
  }, [open]);

  return (
    <span className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-blue-600"
      >
        <HelpCircle size={13} /> What does this mean?
      </button>
      {open && (
        <div className="absolute left-0 z-20 mt-1 w-64 rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-600 shadow-lg">
          {children}
        </div>
      )}
    </span>
  );
}
