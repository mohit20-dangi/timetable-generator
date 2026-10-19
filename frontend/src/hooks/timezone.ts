/** Timestamps are stored and serialised as real UTC instants - this renders
 * them in the college's timezone instead of whatever timezone the viewer's
 * browser happens to be in. */
export const TIMEZONE = 'Asia/Kolkata';

export function formatInTimezone(iso: string, timezone: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timezone, day: 'numeric', month: 'short', year: 'numeric',
      hour: 'numeric', minute: '2-digit',
    }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleString();
  }
}
