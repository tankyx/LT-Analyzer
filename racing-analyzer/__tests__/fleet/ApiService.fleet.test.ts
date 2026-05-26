jest.mock('@/utils/config', () => ({ API_BASE_URL: 'http://api.test' }));

import { ApiService } from '@/app/services/ApiService';

describe('ApiService fleet methods', () => {
  beforeEach(() => {
    (global.fetch as unknown) = jest.fn();
  });

  test('getFleetState hits the right URL with credentials', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true, json: async () => ({ karts: [], session_id: 5 }),
    });
    const res = await ApiService.getFleetState(3, 5);
    expect(global.fetch).toHaveBeenCalledWith(
      'http://api.test/api/track/3/fleet/state?session_id=5',
      { credentials: 'include' },
    );
    expect(res.session_id).toBe(5);
  });

  test('recordAssignment sends body + CSRF header', async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ csrfToken: 'tok' }) })   // csrf
      .mockResolvedValueOnce({ ok: true, json: async () => ({ assignment: { id: 1 } }) }); // post

    await ApiService.recordAssignment(2, 9, 'TeamX', 7, 1);

    const call = (global.fetch as jest.Mock).mock.calls
      .find(c => String(c[0]).endsWith('/api/track/2/fleet/assignments'));
    expect(call).toBeDefined();
    expect(call[1].method).toBe('POST');
    expect(call[1].credentials).toBe('include');
    expect(call[1].headers['X-CSRF-Token']).toBe('tok');
    expect(JSON.parse(call[1].body)).toMatchObject({
      session_id: 9, team_name: 'TeamX', fleet_kart_id: 7, stint_index: 1,
    });
  });

  test('createFleetKart posts label with CSRF', async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ csrfToken: 'tok' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ kart: { id: 1, label: 'K1' } }) });
    await ApiService.createFleetKart(4, 'K1');
    const call = (global.fetch as jest.Mock).mock.calls
      .find(c => String(c[0]).endsWith('/api/track/4/fleet/karts'));
    expect(call[1].method).toBe('POST');
    expect(call[1].headers['X-CSRF-Token']).toBe('tok');
    expect(JSON.parse(call[1].body)).toMatchObject({ label: 'K1' });
  });

  test('a non-ok response throws errorData.error', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false, json: async () => ({ error: 'boom' }),
    });
    await expect(ApiService.getFleetState(1)).rejects.toThrow('boom');
  });
});
