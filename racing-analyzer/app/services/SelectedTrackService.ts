/**
 * Phase 2.6: cross-device sync of the user's currently-selected track.
 * The selected track is per-user (not per-track), so it lives on the users
 * row, not in user_track_prefs.
 */

import { API_BASE_URL } from '../../utils/config';

async function csrfHeaders(): Promise<Record<string, string>> {
  const resp = await fetch(`${API_BASE_URL}/api/auth/csrf`, { credentials: 'include' });
  if (!resp.ok) return {};
  const data = await resp.json().catch(() => ({}));
  return data?.csrfToken ? { 'X-CSRF-Token': data.csrfToken } : {};
}

export async function getSelectedTrack(): Promise<number | null> {
  const resp = await fetch(`${API_BASE_URL}/api/me/selected-track`, {
    credentials: 'include',
  });
  if (!resp.ok) return null;
  const data = await resp.json().catch(() => ({}));
  return typeof data?.track_id === 'number' ? data.track_id : null;
}

export async function putSelectedTrack(trackId: number): Promise<void> {
  const headers = { 'Content-Type': 'application/json', ...(await csrfHeaders()) };
  await fetch(`${API_BASE_URL}/api/me/selected-track`, {
    method: 'PUT',
    credentials: 'include',
    headers,
    body: JSON.stringify({ track_id: trackId }),
  });
}
