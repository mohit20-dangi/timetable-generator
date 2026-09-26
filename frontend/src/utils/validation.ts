import { DAY_LABELS, ScheduleSlot, formatTime } from './schedule';

export interface TimeWindow {
  day: string;
  start: string;
  end: string;
}

export interface ValidationMessage {
  severity: 'error' | 'warning';
  message: string;
}

const to24h = (value: string) => value; // inputs are already HH:MM (type="time")

/** Phase 3.6 validation rules, shared by teacher availability, teacher
 * preferred times, and room availability - the same three checks apply to
 * all of them, so they live in one place instead of three copies. */
export function validateWindows(windows: TimeWindow[], scheduleSlots: ScheduleSlot[]): ValidationMessage[] {
  const messages: ValidationMessage[] = [];

  windows.forEach((window, index) => {
    if (to24h(window.start) >= to24h(window.end)) {
      messages.push({
        severity: 'error',
        message: `${DAY_LABELS[window.day] || window.day}: end time must be after start time. For 4 PM, enter 16:00.`,
      });
      return;
    }

    // Overlap against every other window on the same day.
    windows.forEach((other, otherIndex) => {
      if (otherIndex <= index || other.day !== window.day) return;
      const overlaps = to24h(window.start) < to24h(other.end) && to24h(other.start) < to24h(window.end);
      if (overlaps) {
        messages.push({
          severity: 'error',
          message: `This overlaps ${formatTime(other.start)}-${formatTime(other.end)} on ${DAY_LABELS[window.day] || window.day}. Merge them into one window.`,
        });
      }
    });

    const daySlots = scheduleSlots.filter((slot) => slot.day === window.day);
    const coversAPeriod = daySlots.some(
      (slot) => to24h(window.start) < slot.end_time.slice(0, 5) && slot.start_time.slice(0, 5) < to24h(window.end)
    );
    if (daySlots.length > 0 && !coversAPeriod) {
      messages.push({ severity: 'warning', message: `No classes are scheduled in this window on ${DAY_LABELS[window.day] || window.day}.` });
    }
  });

  return messages;
}

/** Preferred windows should sit inside availability - not an error (a
 * teacher's preferences and hard availability are set independently and
 * the common case is preferred ⊆ available), just a nudge. */
export function validatePreferredWithinAvailability(preferred: TimeWindow[], availability: TimeWindow[], teacherLabel: string): ValidationMessage[] {
  return preferred
    .filter((pref) => {
      const dayWindows = availability.filter((a) => a.day === pref.day);
      if (dayWindows.length === 0) return true;
      return !dayWindows.some((a) => a.start <= pref.start && pref.end <= a.end);
    })
    .map((pref) => ({
      severity: 'warning',
      message: `${teacherLabel} prefers ${formatTime(pref.start)}-${formatTime(pref.end)} ${DAY_LABELS[pref.day] || pref.day} but isn't available then.`,
    }));
}

function periodsPerDay(scheduleSlots: ScheduleSlot[]): Map<string, number> {
  const counts = new Map<string, number>();
  scheduleSlots.forEach((slot) => counts.set(slot.day, (counts.get(slot.day) || 0) + 1));
  return counts;
}

/** The longest run of back-to-back periods offered on any single day -
 * the real ceiling for "max continuous classes", not an arbitrary cap. */
function longestContinuousRun(scheduleSlots: ScheduleSlot[]): number {
  const byDay = new Map<string, number[]>();
  scheduleSlots.forEach((slot) => {
    const list = byDay.get(slot.day) || [];
    list.push(slot.period_index);
    byDay.set(slot.day, list);
  });
  let longest = 0;
  for (const periods of byDay.values()) {
    const sorted = [...periods].sort((a, b) => a - b);
    let run = 1;
    for (let i = 1; i < sorted.length; i++) {
      run = sorted[i] === sorted[i - 1] + 1 ? run + 1 : 1;
      longest = Math.max(longest, run);
    }
    longest = Math.max(longest, sorted.length ? 1 : 0);
  }
  return longest;
}

export function validateWorkloadCaps(
  caps: { maxDailyClasses?: number; maxWeeklyHours?: number; maxContinuousClasses?: number },
  scheduleSlots: ScheduleSlot[],
): ValidationMessage[] {
  const messages: ValidationMessage[] = [];
  const perDay = periodsPerDay(scheduleSlots);
  const maxPeriodsInADay = Math.max(0, ...perDay.values());
  const teachingDays = perDay.size;

  if (caps.maxDailyClasses != null && maxPeriodsInADay > 0 && caps.maxDailyClasses > maxPeriodsInADay) {
    messages.push({ severity: 'warning', message: `Max ${maxPeriodsInADay} - this schedule has ${maxPeriodsInADay} periods a day.` });
  }
  if (caps.maxWeeklyHours != null && teachingDays > 0) {
    const ceiling = maxPeriodsInADay * teachingDays;
    if (ceiling > 0 && caps.maxWeeklyHours > ceiling) {
      messages.push({ severity: 'warning', message: `Max ${ceiling} - this schedule offers ${maxPeriodsInADay} periods/day across ${teachingDays} day(s).` });
    }
  }
  if (caps.maxContinuousClasses != null && scheduleSlots.length > 0) {
    const longest = longestContinuousRun(scheduleSlots);
    if (longest > 0 && caps.maxContinuousClasses > longest) {
      messages.push({ severity: 'warning', message: `Max ${longest} - the longest back-to-back run in this schedule is ${longest} period(s).` });
    }
  }
  return messages;
}
