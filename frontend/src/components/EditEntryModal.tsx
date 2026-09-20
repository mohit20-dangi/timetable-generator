import { useEffect, useState } from 'react';
import { X, AlertTriangle, CheckCircle } from 'lucide-react';
import { constraintsApi, timetableApi } from '../api/client';
import { TimetableEntry } from '../types';
import { useNavigate } from 'react-router-dom';
import { DAYS, DAY_LABELS, DEFAULT_SLOTS, ScheduleSlot, timeLabel } from '../utils/schedule';

interface Props {
  runId: number;
  entry: TimetableEntry;
  subjectName: string;
  onClose: () => void;
}

export function EditEntryModal({ runId, entry, subjectName, onClose }: Props) {
  const [newDay, setNewDay] = useState(entry.day);
  const [newPeriod, setNewPeriod] = useState(entry.period);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [slots, setSlots] = useState<ScheduleSlot[]>(DEFAULT_SLOTS);
  const navigate = useNavigate();

  useEffect(() => {
    constraintsApi.listTimeSlots().then((response) => {
      if (response.data.length) setSlots(response.data);
    }).catch(() => undefined);
  }, []);

  const periodsForDay = slots.filter((slot) => slot.day === newDay).sort((a, b) => a.period_index - b.period_index);

  const submit = async (autoResolve: boolean, forceDay?: string, forcePeriod?: number) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await timetableApi.editEntry(runId, {
        target: {
          day: entry.day,
          period: entry.period,
          subject_id: entry.subject_id,
          section_id: entry.section_id,
          batch_id: entry.batch_id,
        },
        new_day: forceDay ?? newDay,
        new_period: forcePeriod ?? newPeriod,
        auto_resolve: autoResolve,
      });
      setResult(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Something went wrong.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl max-w-md w-full p-6">
        <div className="flex justify-between items-start mb-4">
          <div>
            <h3 className="text-lg font-bold text-gray-900">Move Class</h3>
            <p className="text-sm text-gray-500">
              {subjectName} · currently {DAY_LABELS[entry.day] || entry.day}, {timeLabel(slots.find((slot) => slot.day === entry.day && slot.period_index === entry.period)) || `Period ${entry.period}`}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={20} />
          </button>
        </div>

        {!result && (
          <>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">New day</label>
                <select
                  value={newDay}
                  onChange={(e) => setNewDay(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                >
                  {DAYS.map((d) => (
                    <option key={d} value={d}>{DAY_LABELS[d]}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">New period</label>
                <select
                  value={newPeriod}
                  onChange={(e) => setNewPeriod(parseInt(e.target.value))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                >
                  {periodsForDay.map((slot) => (
                    <option key={slot.period_index} value={slot.period_index}>{timeLabel(slot)}</option>
                  ))}
                </select>
              </div>
            </div>

            {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

            <button
              onClick={() => submit(false)}
              disabled={submitting}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 rounded-lg text-sm"
            >
              {submitting ? 'Checking...' : 'Move class'}
            </button>
            <p className="text-xs text-gray-400 mt-2">
              This creates a new draft version - the currently published timetable won't change until you publish the draft.
            </p>
          </>
        )}

        {result && result.status === 'conflict' && (
          <div>
            <div className="flex items-center gap-2 text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3 mb-3">
              <AlertTriangle size={18} />
              <span className="text-sm font-medium">This slot conflicts with the existing timetable</span>
            </div>
            <ul className="text-sm text-gray-700 space-y-1 mb-4">
              {result.conflicts.map((c: any, i: number) => (
                <li key={i} className="flex gap-2">
                  <span className="text-red-500">•</span> {c.message}
                </li>
              ))}
            </ul>

            {result.suggested_slots.length > 0 ? (
              <>
                <p className="text-sm font-medium text-gray-700 mb-2">Suggested free alternatives:</p>
                <div className="flex flex-wrap gap-2 mb-4">
                  {result.suggested_slots.map((s: any, i: number) => (
                    <button
                      key={i}
                      onClick={() => submit(false, s.day, s.period)}
                      className="px-3 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 text-sm rounded-lg border border-blue-200"
                    >
                      {s.day}, Period {s.period}
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-gray-500 mb-4">No free alternative slot was found automatically.</p>
            )}

            <div className="flex gap-2">
              <button onClick={() => setResult(null)} className="flex-1 px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">
                Try a different slot
              </button>
              <button onClick={onClose} className="flex-1 px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">
                Cancel
              </button>
            </div>
          </div>
        )}

        {result && result.status === 'applied' && (
          <div>
            <div className="flex items-center gap-2 text-green-700 bg-green-50 border border-green-200 rounded-lg p-3 mb-4">
              <CheckCircle size={18} />
              <span className="text-sm font-medium">Draft created: {result.new_run.change_summary}</span>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              This is run #{result.new_run.id}, unpublished. Review it, then publish it to make it live.
            </p>
            <button
              onClick={() => navigate(`/runs/${result.new_run.id}`)}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded-lg text-sm"
            >
              View draft run #{result.new_run.id}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
