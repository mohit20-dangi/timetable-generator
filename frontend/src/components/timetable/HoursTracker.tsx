import { AlertTriangle, Plus } from 'lucide-react';
import { Subject, TimetableEntry } from '../../types';

interface Props {
  sectionId: string;
  subjectIds: string[];
  subjects: Record<string, Subject>;
  /** Entries of this section's timetable (section-level and its batches). */
  entries: TimetableEntry[];
  onAdd: (subjectId: string) => void;
  canAdd: boolean;
}

/**
 * Planned vs scheduled periods per subject for one section. A subject that
 * is short (e.g. after a class was deleted) shows up here with a one-click
 * way to put it back on the grid.
 */
export function HoursTracker({ sectionId, subjectIds, subjects, entries, onAdd, canAdd }: Props) {
  const rows = subjectIds
    .map((id) => subjects[id])
    .filter((s): s is Subject => !!s && s.delivery_mode === 'IN_PERSON' && s.weekly_hours > 0)
    .map((s) => {
      const mine = entries.filter((e) => e.subject_id === s.id);
      let scheduled: number;
      if (s.type === 'lab') {
        // Every batch needs the full hours; the section is only as complete as its thinnest batch.
        const perBatch = new Map<string, number>();
        mine.forEach((e) => perBatch.set(e.batch_id || '', (perBatch.get(e.batch_id || '') || 0) + 1));
        scheduled = perBatch.size ? Math.min(...perBatch.values()) : 0;
      } else {
        scheduled = mine.filter((e) => e.section_id === sectionId).length;
      }
      return { subject: s, scheduled, planned: s.weekly_hours };
    })
    .filter((r) => r.scheduled !== r.planned);

  if (rows.length === 0) return null;
  return (
    <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
      <p className="mb-2 flex items-center gap-2 text-sm font-medium text-amber-900">
        <AlertTriangle size={16} /> Periods planned vs scheduled for this section
      </p>
      <div className="flex flex-wrap gap-2">
        {rows.map(({ subject, scheduled, planned }) => (
          <span key={subject.id} className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-white px-2.5 py-1 text-xs text-amber-900">
            {subject.name}: {scheduled}/{planned}
            {canAdd && scheduled < planned && (
              <button onClick={() => onAdd(subject.id)} className="rounded-full bg-amber-500 p-0.5 text-white hover:bg-amber-600" title="Add a class for this subject">
                <Plus size={12} />
              </button>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}
