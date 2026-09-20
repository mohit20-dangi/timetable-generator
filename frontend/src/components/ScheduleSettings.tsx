import { useEffect, useMemo, useState } from 'react';
import { constraintsApi } from '../api/client';
import { DAYS, DAY_LABELS, DEFAULT_SLOTS, ScheduleSlot, timeLabel } from '../utils/schedule';

export function ScheduleSettings() {
  const [slots, setSlots] = useState<ScheduleSlot[]>([]);
  const [day, setDay] = useState('Mon');
  const [startTime, setStartTime] = useState('09:00');
  const [endTime, setEndTime] = useState('09:50');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const displaySlots = useMemo(() => slots.length ? slots : DEFAULT_SLOTS, [slots]);
  const nextPeriod = Math.max(0, ...slots.filter((slot) => slot.day === day).map((slot) => slot.period_index)) + 1;

  useEffect(() => {
    constraintsApi.listTimeSlots().then((response) => setSlots(response.data)).catch(() => setError('Could not load the schedule.'));
  }, []);

  const addSlot = async () => {
    setError('');
    setMessage('');
    if (startTime >= endTime) {
      setError('End time must be after start time.');
      return;
    }
    try {
      const response = await constraintsApi.createTimeSlot({
        id: `${day}_${nextPeriod}_${startTime.replace(':', '')}`,
        day,
        period_index: nextPeriod,
        start_time: startTime,
        end_time: endTime,
      });
      setSlots((current) => [...current, response.data]);
      setMessage(`${DAY_LABELS[day]} period ${nextPeriod} added.`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not add this time slot.');
    }
  };

  const removeSlot = async (slot: ScheduleSlot) => {
    try {
      await constraintsApi.deleteTimeSlot(slot.id);
      setSlots((current) => current.filter((item) => item.id !== slot.id));
      setMessage('Time slot removed.');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not remove this time slot.');
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-lg font-semibold text-gray-900">Class times</h3>
        <p className="text-sm text-gray-600">Customize the daily periods. New timetables and exports will use these time ranges. If you do not customize anything, the default 8 periods from 9:00 AM are used.</p>
      </div>
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && <div className="rounded-lg bg-green-50 p-3 text-sm text-green-700">{message}</div>}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <label className="text-sm text-gray-700">Day<select value={day} onChange={(e) => setDay(e.target.value)} className="mt-1 w-full rounded border px-3 py-2">{DAYS.map((item) => <option key={item} value={item}>{DAY_LABELS[item]}</option>)}</select></label>
        <label className="text-sm text-gray-700">Start time<input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} className="mt-1 w-full rounded border px-3 py-2" /></label>
        <label className="text-sm text-gray-700">End time<input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} className="mt-1 w-full rounded border px-3 py-2" /></label>
        <button type="button" onClick={addSlot} className="self-end rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700">Add period</button>
      </div>
      <div className="overflow-x-auto rounded border">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50"><tr><th className="px-3 py-2 text-left">Day</th><th className="px-3 py-2 text-left">Period</th><th className="px-3 py-2 text-left">Time</th><th className="px-3 py-2" /></tr></thead>
          <tbody>{displaySlots.map((slot) => <tr key={slot.id} className="border-t"><td className="px-3 py-2">{DAY_LABELS[slot.day] || slot.day}</td><td className="px-3 py-2">{slot.period_index}</td><td className="px-3 py-2">{timeLabel(slot)}</td><td className="px-3 py-2 text-right">{slots.length > 0 && <button type="button" onClick={() => removeSlot(slot)} className="text-red-600 hover:underline">Remove</button>}</td></tr>)}</tbody>
        </table>
      </div>
      {slots.length > 0 && <p className="text-xs text-gray-500">You are using a custom schedule. Add every period you want available on each day before generating.</p>}
    </div>
  );
}
