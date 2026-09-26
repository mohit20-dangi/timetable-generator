import { useEffect, useState } from 'react';
import { constraintsApi, timetableApi } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { DAYS, DAY_LABELS, DEFAULT_SLOTS, ScheduleSlot, timeLabel } from '../utils/schedule';
import { CalendarPlus } from 'lucide-react';

interface Entry {
  id: number;
  day: string;
  period: number;
  subject_id: string;
  teacher_id: string;
  room_id: string;
  section_id: string | null;
  batch_id: string | null;
}

export function MyTimetable() {
  const { user } = useAuth();
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slots, setSlots] = useState<ScheduleSlot[]>(DEFAULT_SLOTS);
  const [calendarError, setCalendarError] = useState('');

  const handleAddToCalendar = async () => {
    setCalendarError('');
    try {
      const response = await timetableApi.myCalendar();
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'my-timetable.ics';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch {
      setCalendarError('Could not download your calendar file.');
    }
  };

  useEffect(() => {
    timetableApi
      .myTimetable()
      .then((res) => setEntries(res.data))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load your timetable.'));
    constraintsApi.listTimeSlots().then((res) => {
      if (res.data.length) setSlots(res.data);
    }).catch(() => undefined);
  }, []);

  if (error) return <div className="text-sm text-red-600">{error}</div>;
  if (entries === null) return <div className="text-sm text-gray-500">Loading...</div>;

  if (entries.length === 0) {
    return (
      <div className="text-sm text-gray-500">
        No published timetable yet. Once the department admin generates a
        timetable, your {user?.role === 'FACULTY' ? 'teaching schedule' : 'class schedule'} will appear here.
      </div>
    );
  }

  const periodNumbers = [...new Set(slots.map((slot) => slot.period_index))].sort((a, b) => a - b);
  const grid: Record<string, Record<number, Entry[]>> = {};
  for (const day of DAYS) grid[day] = {};
  for (const e of entries) {
    if (grid[e.day]) grid[e.day][e.period] = [...(grid[e.day][e.period] || []), e];
  }

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-lg font-bold text-gray-900 mb-1">My Timetable</h1>
          <p className="text-sm text-gray-500">
            {user?.role === 'FACULTY' ? 'Your teaching schedule.' : 'Your class schedule.'}
          </p>
        </div>
        <button
          onClick={handleAddToCalendar}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors text-sm"
        >
          <CalendarPlus size={18} />
          Add to my calendar
        </button>
      </div>
      {calendarError && <p className="mb-4 text-sm text-red-600">{calendarError}</p>}

      <div className="overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead>
            <tr className="bg-gray-50">
              <th className="border border-gray-200 px-3 py-2 text-left">Day</th>
              {periodNumbers.map((p) => (
                <th key={p} className="border border-gray-200 px-3 py-2">
                  <div>Period {p}</div>
                  <div className="text-xs font-normal">{timeLabel(slots.find((slot) => slot.period_index === p))}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DAYS.map((day) => (
              <tr key={day}>
                <td className="border border-gray-200 px-3 py-2 font-medium bg-gray-50">{DAY_LABELS[day]}</td>
                {periodNumbers.map((p) => {
                  const cellEntries = grid[day][p] || [];
                  return (
                    <td key={p} className="border border-gray-200 px-3 py-2 text-center">
                      {cellEntries.length ? (
                        <div className="space-y-1">
                          {cellEntries.map((e) => (
                            <div key={e.id}>
                              <div className="font-medium">{e.subject_id}</div>
                              {e.batch_id && <div className="text-xs text-gray-500">Batch {e.batch_id}</div>}
                              <div className="text-xs text-gray-500">{e.room_id}</div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
