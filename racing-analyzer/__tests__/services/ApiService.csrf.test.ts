/**
 * Regression tests for the CSRF-protected mutation endpoints in ApiService.
 *
 * The audit flagged five endpoints (updateMonitoring, startSimulation,
 * stopSimulation, updatePitStopConfig, resetRaceData) plus triggerPitAlert
 * as missing both `credentials: 'include'` and the X-CSRF-Token header.
 * Without them the backend's CSRF middleware 403s the call (which is exactly
 * what the user hit when trying to send a pit alert from the dashboard).
 *
 * These tests pin the fix in place — if anyone reverts to raw fetch without
 * the helper, jest fails BEFORE the regression reaches production.
 *
 * Pattern: getCsrfHeaders does a preflight GET /api/auth/csrf so we mock
 * two responses per call — first the csrf token fetch, then the actual POST.
 */

jest.mock('@/utils/config', () => ({ API_BASE_URL: 'http://api.test' }));

import { ApiService } from '@/app/services/ApiService';

type FetchMock = jest.Mock & { mock: { calls: any[][] } };

function mockCsrfThen<T>(body: T) {
  (global.fetch as FetchMock)
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrfToken: 'csrf-test-token' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => body });
}

function findCallByUrl(suffix: string) {
  return (global.fetch as FetchMock).mock.calls.find(
    c => String(c[0]).endsWith(suffix),
  );
}

beforeEach(() => {
  (global.fetch as unknown) = jest.fn();
});

describe('ApiService CSRF-protected mutations', () => {
  test.each([
    {
      name: 'updateMonitoring',
      run: () => ApiService.updateMonitoring({ myTeam: 'A', monitoredTeams: ['B', 'C'] }),
      urlSuffix: '/api/update-monitoring',
      body: { myTeam: 'A', monitoredTeams: ['B', 'C'] },
    },
    {
      name: 'startSimulation',
      run: () => ApiService.startSimulation(true, 'http://t', 'wss://w', 99),
      urlSuffix: '/api/start-simulation',
      body: { simulation: true, timingUrl: 'http://t', websocketUrl: 'wss://w', trackId: 99 },
    },
    {
      name: 'stopSimulation',
      run: () => ApiService.stopSimulation(),
      urlSuffix: '/api/stop-simulation',
      body: undefined,
    },
    {
      name: 'updatePitStopConfig',
      run: () => ApiService.updatePitStopConfig({ pitStopTime: 158, requiredPitStops: 7 }),
      urlSuffix: '/api/update-pit-config',
      body: { pitStopTime: 158, requiredPitStops: 7 },
    },
    {
      name: 'resetRaceData',
      run: () => ApiService.resetRaceData(),
      urlSuffix: '/api/reset-race-data',
      body: undefined,
    },
    {
      name: 'triggerPitAlert',
      run: () => ApiService.triggerPitAlert({ track_id: 1, team_name: 'X', alert_message: 'GO PIT' }),
      urlSuffix: '/api/trigger-pit-alert',
      body: { track_id: 1, team_name: 'X', alert_message: 'GO PIT' },
    },
  ])('$name sends X-CSRF-Token + credentials:"include"', async ({ run, urlSuffix, body }) => {
    mockCsrfThen({ ok: true });
    await run();
    const call = findCallByUrl(urlSuffix);
    expect(call).toBeDefined();
    expect(call![1].method).toBe('POST');
    expect(call![1].credentials).toBe('include');
    expect(call![1].headers['X-CSRF-Token']).toBe('csrf-test-token');
    if (body !== undefined) {
      expect(JSON.parse(call![1].body)).toMatchObject(body);
    } else {
      // Endpoints without a JSON body must NOT accidentally send one
      // (the audit caught endpoints that used to send empty {} which the
      // backend can mis-parse).
      expect(call![1].body).toBeUndefined();
    }
  });

  test('a CSRF preflight failure does not throw — request still attempts', async () => {
    // getCsrfHeaders falls back to {} on preflight failure (matches the
    // helper's implementation), so the request goes out without the header.
    // The backend will 403 it, but we shouldn't crash client-side BEFORE
    // sending — the error reaches the user via response.ok=false.
    (global.fetch as FetchMock)
      .mockResolvedValueOnce({ ok: false })                                   // csrf preflight fails
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) }); // request still attempted
    await ApiService.updateMonitoring({ myTeam: 'A', monitoredTeams: [] });
    const call = findCallByUrl('/api/update-monitoring');
    expect(call).toBeDefined();
    expect(call![1].headers['X-CSRF-Token']).toBeUndefined();   // header absent, no crash
    expect(call![1].credentials).toBe('include');               // cookies still flow
  });
});
