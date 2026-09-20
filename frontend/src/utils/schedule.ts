export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;

export const DAY_LABELS: Record<string, string> = {
  Mon: 'Monday',
  Tue: 'Tuesday',
  Wed: 'Wednesday',
  Thu: 'Thursday',
  Fri: 'Friday',
  Sat: 'Saturday',
  Sun: 'Sunday',
};

export interface ScheduleSlot {
  id: string;
  day: string;
  period_index: number;
  start_time: string;
  end_time: string;
}

export const DEFAULT_SLOTS: ScheduleSlot[] = DAYS.flatMap((day) =>
  Array.from({ length: 8 }, (_, index) => {
    const start = 9 * 60 + index * 50;
    const end = start + 50;
    const clock = (minutes: number) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
    return {
      id: `${day}_${index + 1}`,
      day,
      period_index: index + 1,
      start_time: clock(start),
      end_time: clock(end),
    };
  }),
);

export function normaliseTime(value: string | null | undefined): string {
  return (value || '').slice(0, 5);
}

export function formatTime(value: string | null | undefined): string {
  const [hours, minutes] = normaliseTime(value).split(':').map(Number);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return value || '';
  const suffix = hours >= 12 ? 'PM' : 'AM';
  const displayHour = hours % 12 || 12;
  return `${displayHour}:${String(minutes).padStart(2, '0')} ${suffix}`;
}

export function timeLabel(slot?: ScheduleSlot): string {
  return slot ? `${formatTime(slot.start_time)} - ${formatTime(slot.end_time)}` : '';
}

export function orderedSlots(slots: ScheduleSlot[]): ScheduleSlot[] {
  const order = new Map<string, number>(DAYS.map((day, index) => [day, index]));
  return [...slots].sort((a, b) => (order.get(a.day) ?? 99) - (order.get(b.day) ?? 99) || a.period_index - b.period_index);
}
