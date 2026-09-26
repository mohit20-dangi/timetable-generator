import { useEffect, useState } from 'react';
import { institutionsApi } from '../api/client';

/** Phase 4.4: timestamps are stored and serialised as real UTC instants -
 * this is what renders them in the institution's own timezone (default
 * Asia/Kolkata) instead of whatever timezone the admin's browser happens
 * to be in. */
export function useInstitutionTimezone(): string {
  const [timezone, setTimezone] = useState('Asia/Kolkata');
  useEffect(() => {
    institutionsApi.list().then((res) => {
      if (res.data[0]?.timezone) setTimezone(res.data[0].timezone);
    }).catch(() => {});
  }, []);
  return timezone;
}

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
