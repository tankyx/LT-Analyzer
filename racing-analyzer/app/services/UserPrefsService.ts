/**
 * Phase 2: per-user, per-track preferences. Replaces the localStorage-only
 * stint planner config / monitored-teams / pit-config that used to live in
 * `utils/persistence.ts`. Server is the source of truth; localStorage is a
 * read-through cache to avoid a "flash of defaults" on page load.
 */

import { API_BASE_URL } from '../../utils/config';

export interface UserTrackPrefs {
  track_id: number;
  my_team: string | null;
  monitored_teams: string[];
  pit_stop_time: number;
  required_pit_stops: number;
  default_lap_time: number;
  stint_planner_config: Record<string, unknown>;
  stint_planner_presets: Array<Record<string, unknown>>;
  driver_names: string[];
  current_driver_index: number;
  updated_at: string | null;
}

const DEFAULTS: Omit<UserTrackPrefs, 'track_id'> = {
  my_team: null,
  monitored_teams: [],
  pit_stop_time: 158,
  required_pit_stops: 7,
  default_lap_time: 90,
  stint_planner_config: {},
  stint_planner_presets: [],
  driver_names: [],
  current_driver_index: 0,
  updated_at: null,
};

export function defaultPrefs(trackId: number): UserTrackPrefs {
  return { track_id: trackId, ...DEFAULTS };
}

function cacheKey(trackId: number): string {
  return `lt_analyzer_prefs_track_${trackId}`;
}

export function readCache(trackId: number): UserTrackPrefs | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(cacheKey(trackId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return { ...defaultPrefs(trackId), ...parsed };
  } catch {
    return null;
  }
}

export function writeCache(prefs: UserTrackPrefs): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(cacheKey(prefs.track_id), JSON.stringify(prefs));
  } catch {
    // localStorage may be full or disabled — silently ignore.
  }
}

export function clearCache(trackId: number): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(cacheKey(trackId));
  } catch {
    /* noop */
  }
}

async function csrfHeaders(): Promise<Record<string, string>> {
  // The CSRF token endpoint is anonymous (GET); we always have a token in
  // session (issued on first request after page load). Fetch fresh each call —
  // cheap and avoids stale-token races after server-side rotation on login.
  const resp = await fetch(`${API_BASE_URL}/api/auth/csrf`, { credentials: 'include' });
  if (!resp.ok) return {};
  const data = await resp.json().catch(() => ({}));
  return data?.csrfToken ? { 'X-CSRF-Token': data.csrfToken } : {};
}

export async function getPrefs(trackId: number): Promise<UserTrackPrefs> {
  const resp = await fetch(`${API_BASE_URL}/api/me/prefs/${trackId}`, {
    credentials: 'include',
  });
  if (resp.status === 401) {
    throw new Error('unauthorized');
  }
  if (!resp.ok) {
    throw new Error(`prefs_fetch_failed_${resp.status}`);
  }
  const body = await resp.json();
  const prefs: UserTrackPrefs = { ...defaultPrefs(trackId), ...(body.prefs || {}) };
  writeCache(prefs);
  return prefs;
}

export async function updatePrefs(
  trackId: number,
  patch: Partial<Omit<UserTrackPrefs, 'track_id' | 'updated_at'>>,
): Promise<UserTrackPrefs> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(await csrfHeaders()),
  };
  const resp = await fetch(`${API_BASE_URL}/api/me/prefs/${trackId}`, {
    method: 'PUT',
    credentials: 'include',
    headers,
    body: JSON.stringify(patch),
  });
  if (resp.status === 401) {
    throw new Error('unauthorized');
  }
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody?.error || `prefs_update_failed_${resp.status}`);
  }
  const body = await resp.json();
  const prefs: UserTrackPrefs = { ...defaultPrefs(trackId), ...(body.prefs || {}) };
  writeCache(prefs);
  return prefs;
}

export async function resetPrefs(trackId: number): Promise<UserTrackPrefs> {
  const headers: Record<string, string> = { ...(await csrfHeaders()) };
  const resp = await fetch(`${API_BASE_URL}/api/me/prefs/${trackId}`, {
    method: 'DELETE',
    credentials: 'include',
    headers,
  });
  if (!resp.ok) {
    throw new Error(`prefs_reset_failed_${resp.status}`);
  }
  const body = await resp.json();
  const prefs: UserTrackPrefs = { ...defaultPrefs(trackId), ...(body.prefs || {}) };
  writeCache(prefs);
  return prefs;
}

/**
 * Debounced PUT helper. Coalesces rapid-fire edits (e.g. typing in a number
 * input) into one server round-trip. Returns an object with `schedule()` to
 * queue a patch and `flush()` to force-send any pending patch immediately.
 */
export function makePrefsDebouncer(trackId: number, delayMs = 500) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: Partial<UserTrackPrefs> = {};

  const send = async () => {
    if (Object.keys(pending).length === 0) return;
    const patch = pending;
    pending = {};
    try {
      await updatePrefs(trackId, patch);
    } catch (e) {
      console.warn('updatePrefs failed:', e);
    }
  };

  return {
    schedule(patch: Partial<UserTrackPrefs>) {
      pending = { ...pending, ...patch };
      if (timer) clearTimeout(timer);
      timer = setTimeout(send, delayMs);
    },
    async flush() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      await send();
    },
  };
}
