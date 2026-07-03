jest.mock('@/utils/config', () => ({ API_BASE_URL: 'http://api.test' }));

import { getCsrfHeaders, invalidateCsrfToken } from '@/app/services/csrfToken';

beforeEach(() => {
  (global.fetch as unknown) = jest.fn();
  invalidateCsrfToken();
});

describe('csrfToken cache', () => {
  test('fetches once and serves from cache afterwards', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ csrfToken: 'tok-a' }),
    });
    expect(await getCsrfHeaders()).toEqual({ 'X-CSRF-Token': 'tok-a' });
    expect(await getCsrfHeaders()).toEqual({ 'X-CSRF-Token': 'tok-a' });
    expect((global.fetch as jest.Mock).mock.calls).toHaveLength(1);
  });

  test('invalidate forces a refetch', async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ csrfToken: 'tok-1' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ csrfToken: 'tok-2' }) });
    expect(await getCsrfHeaders()).toEqual({ 'X-CSRF-Token': 'tok-1' });
    invalidateCsrfToken();
    expect(await getCsrfHeaders()).toEqual({ 'X-CSRF-Token': 'tok-2' });
  });

  test('failed preflight returns empty headers and is not cached', async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ csrfToken: 'tok-later' }) });
    expect(await getCsrfHeaders()).toEqual({});
    expect(await getCsrfHeaders()).toEqual({ 'X-CSRF-Token': 'tok-later' });
  });

  test('network error returns empty headers instead of throwing', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('offline'));
    expect(await getCsrfHeaders()).toEqual({});
  });
});
