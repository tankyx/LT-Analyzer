jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://api.test',
  WS_BASE_URL: 'ws://api.test',
  TURNSTILE_SITE_KEY: '',
  INVITE_REQUIRED: true,
}));

import {
  getPrefs,
  updatePrefs,
  resetPrefs,
  defaultPrefs,
  makePrefsDebouncer,
  readCache,
  writeCache,
  clearCache,
} from '@/app/services/UserPrefsService';

describe('UserPrefsService.getPrefs', () => {
  beforeEach(() => {
    (global.fetch as unknown) = jest.fn();
  });

  test('returns parsed prefs on 200', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        prefs: { track_id: 1, my_team: 'ALICE', monitored_teams: ['7'], pit_stop_time: 142 },
      }),
    });
    const prefs = await getPrefs(1);
    expect(prefs.my_team).toBe('ALICE');
    expect(prefs.monitored_teams).toEqual(['7']);
    expect(prefs.pit_stop_time).toBe(142);
    // Defaults fill in untouched fields
    expect(prefs.required_pit_stops).toBe(7);
  });

  test('throws unauthorized on 401', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({}),
    });
    await expect(getPrefs(1)).rejects.toThrow('unauthorized');
  });

  test('writes cache on success', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ prefs: { track_id: 9, my_team: 'CACHED' } }),
    });
    clearCache(9);
    await getPrefs(9);
    const cached = readCache(9);
    expect(cached?.my_team).toBe('CACHED');
  });
});

describe('UserPrefsService.updatePrefs', () => {
  beforeEach(() => {
    (global.fetch as unknown) = jest.fn();
  });

  test('PUT body includes patch fields; CSRF header injected', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.endsWith('/api/auth/csrf')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ csrfToken: 'tok' }) });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ prefs: { track_id: 1, my_team: 'P' } }),
      });
    });
    await updatePrefs(1, { my_team: 'P' });
    const putCall = (global.fetch as jest.Mock).mock.calls.find(([u, init]) => init?.method === 'PUT');
    expect(putCall).toBeTruthy();
    expect(putCall[1].headers['X-CSRF-Token']).toBe('tok');
    expect(JSON.parse(putCall[1].body)).toEqual({ my_team: 'P' });
  });

  test('throws on validation error', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.endsWith('/api/auth/csrf')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ csrfToken: 't' }) });
      }
      return Promise.resolve({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ error: 'invalid_pit_stop_time' }),
      });
    });
    await expect(updatePrefs(1, { pit_stop_time: -5 })).rejects.toThrow('invalid_pit_stop_time');
  });
});

describe('UserPrefsService.resetPrefs', () => {
  test('issues DELETE with CSRF and returns defaults', async () => {
    (global.fetch as unknown) = jest.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/auth/csrf')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ csrfToken: 't' }) });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ prefs: { track_id: 1 } }),
      });
    });
    const prefs = await resetPrefs(1);
    expect(prefs.my_team).toBeNull();
    expect(prefs.pit_stop_time).toBe(158);
    const deleteCall = (global.fetch as jest.Mock).mock.calls.find(([u, init]) => init?.method === 'DELETE');
    expect(deleteCall[1].headers['X-CSRF-Token']).toBe('t');
  });
});

describe('makePrefsDebouncer', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    (global.fetch as unknown) = jest.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/auth/csrf')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ csrfToken: 't' }) });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ prefs: { track_id: 1, my_team: 'OK' } }),
      });
    });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('rapid schedules collapse into one PUT', async () => {
    const deb = makePrefsDebouncer(1, 500);
    deb.schedule({ my_team: 'A' });
    deb.schedule({ my_team: 'B' });
    deb.schedule({ monitored_teams: ['7'] });
    expect((global.fetch as jest.Mock).mock.calls.filter(([_, init]) => init?.method === 'PUT')).toHaveLength(0);
    // advanceTimersByTimeAsync flushes the timer's chained microtasks
    // (csrfHeaders await fetch.json + updatePrefs await fetch.json).
    await jest.advanceTimersByTimeAsync(600);
    const putCalls = (global.fetch as jest.Mock).mock.calls.filter(([_, init]) => init?.method === 'PUT');
    expect(putCalls).toHaveLength(1);
    const body = JSON.parse(putCalls[0][1].body);
    expect(body.my_team).toBe('B');
    expect(body.monitored_teams).toEqual(['7']);
  });

  test('flush() sends immediately', async () => {
    const deb = makePrefsDebouncer(1, 500);
    deb.schedule({ my_team: 'X' });
    await deb.flush();
    // flush() returns once send() completes, but send() awaits internal fetches.
    await jest.advanceTimersByTimeAsync(0);
    const putCalls = (global.fetch as jest.Mock).mock.calls.filter(([_, init]) => init?.method === 'PUT');
    expect(putCalls).toHaveLength(1);
  });
});

describe('defaultPrefs', () => {
  test('returns expected shape', () => {
    const d = defaultPrefs(42);
    expect(d.track_id).toBe(42);
    expect(d.pit_stop_time).toBe(158);
    expect(d.required_pit_stops).toBe(7);
    expect(d.monitored_teams).toEqual([]);
  });
});

describe('cache helpers', () => {
  test('writeCache then readCache round-trip', () => {
    const prefs = { ...defaultPrefs(5), my_team: 'CCC' };
    writeCache(prefs);
    const back = readCache(5);
    expect(back?.my_team).toBe('CCC');
  });
  test('clearCache removes entry', () => {
    writeCache({ ...defaultPrefs(6), my_team: 'X' });
    clearCache(6);
    expect(readCache(6)).toBeNull();
  });
});
