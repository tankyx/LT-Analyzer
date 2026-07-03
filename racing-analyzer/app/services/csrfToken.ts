import { API_BASE_URL } from '../../utils/config';

/**
 * Module-scoped CSRF token cache shared by ApiService and UserPrefsService.
 *
 * The token only rotates on login, so fetching /api/auth/csrf before every
 * mutation doubled the request count for nothing. AuthContext calls
 * invalidateCsrfToken() on login/logout; the TTL is a safety net beyond that.
 */
let cachedToken: string | null = null;
let fetchedAt = 0;
const TOKEN_TTL_MS = 10 * 60 * 1000;

export async function getCsrfHeaders(): Promise<Record<string, string>> {
  const now = Date.now();
  if (cachedToken && now - fetchedAt < TOKEN_TTL_MS) {
    return { 'X-CSRF-Token': cachedToken };
  }
  try {
    const resp = await fetch(`${API_BASE_URL}/api/auth/csrf`, { credentials: 'include' });
    if (!resp.ok) return {};
    const data = await resp.json().catch(() => ({}));
    if (data?.csrfToken) {
      cachedToken = data.csrfToken;
      fetchedAt = now;
      return { 'X-CSRF-Token': data.csrfToken };
    }
  } catch {
    // fall through — caller sends the request without the header and the
    // server rejects it with a clear csrf_failed error
  }
  return {};
}

export function invalidateCsrfToken(): void {
  cachedToken = null;
  fetchedAt = 0;
}
