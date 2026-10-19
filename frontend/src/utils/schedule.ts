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
  /** remedial periods are used only by remedial classes, never the main timetable. */
  slot_kind?: 'regular' | 'remedial';
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

export function toMinutes(value: string): number {
  const [h, m] = normaliseTime(value).split(':').map(Number);
  return h * 60 + m;
}

export function toClock(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

export interface DraftPeriod {
  key: string;
  start_time: string;
  end_time: string;
  slot_kind: 'regular' | 'remedial';
}

export type DraftSchedule = Record<string, DraftPeriod[]>;

export interface PatternBreak { afterPeriod: number; minutes: number }

/** `count` back-to-back periods from `startTime`, with a gap after the listed periods. */
export function buildPattern(startTime: string, periodMinutes: number, count: number, breaks: PatternBreak[]): { start_time: string; end_time: string }[] {
  let cursor = toMinutes(startTime);
  const out: { start_time: string; end_time: string }[] = [];
  for (let i = 1; i <= count; i++) {
    out.push({ start_time: toClock(cursor), end_time: toClock(cursor + periodMinutes) });
    cursor += periodMinutes + breaks.filter((b) => b.afterPeriod === i).reduce((sum, b) => sum + b.minutes, 0);
  }
  return out;
}

const byStart = (a: DraftPeriod, b: DraftPeriod) => toMinutes(a.start_time) - toMinutes(b.start_time);

/** Regular and remedial periods are counted separately for display only; the server stores one number space per day. */
export function displayLabels(periods: DraftPeriod[]): Map<string, string> {
  const labels = new Map<string, string>();
  (['regular', 'remedial'] as const).forEach((kind) => {
    periods.filter((p) => p.slot_kind === kind).sort(byStart).forEach((p, i) => labels.set(p.key, kind === 'regular' ? `Period ${i + 1}` : `Remedial ${i + 1}`));
  });
  return labels;
}

/** The same rules the server enforces, so Save can be blocked before the request. */
export function scheduleProblems(draft: DraftSchedule): { day: string; message: string }[] {
  const problems: { day: string; message: string }[] = [];
  DAYS.forEach((day) => {
    const rows = [...(draft[day] || [])].sort(byStart);
    rows.forEach((p) => {
      if (toMinutes(p.end_time) <= toMinutes(p.start_time)) problems.push({ day, message: `${formatTime(p.start_time)} - ${formatTime(p.end_time)} ends before it starts` });
    });
    rows.slice(1).forEach((p, i) => {
      if (toMinutes(p.start_time) < toMinutes(rows[i].end_time)) problems.push({ day, message: `${formatTime(rows[i].start_time)} - ${formatTime(rows[i].end_time)} overlaps ${formatTime(p.start_time)} - ${formatTime(p.end_time)}` });
    });
  });
  return problems;
}
