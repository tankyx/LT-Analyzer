import { render, act, waitFor } from '@testing-library/react';
import React from 'react';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://api.test',
}));

import { AuthProvider, useAuth } from '@/app/contexts/AuthContext';

function Capture({ onReady }: { onReady: (v: ReturnType<typeof useAuth>) => void }) {
  const ctx = useAuth();
  React.useEffect(() => { onReady(ctx); }, [ctx, onReady]);
  return null;
}

describe('AuthContext', () => {
  beforeEach(() => {
    (global.fetch as unknown) = jest.fn();
  });

  const seedFetch = (csrf: string, authed = false) => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.endsWith('/api/auth/csrf')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ csrfToken: csrf }) });
      }
      if (url.endsWith('/api/auth/check')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ authenticated: authed, user: authed ? { id: 1, username: 'u', email: 'e@x', role: 'user' } : null }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  };

  test('fetches CSRF on mount and exposes it', async () => {
    seedFetch('csrf-tok');
    const captured: ReturnType<typeof useAuth>[] = [];
    render(<AuthProvider><Capture onReady={(v) => captured.push(v)} /></AuthProvider>);
    await waitFor(() => expect(captured.some((c) => c.csrfToken === 'csrf-tok')).toBe(true));
  });

  test('apiFetch adds X-CSRF-Token on POST but not GET', async () => {
    seedFetch('the-token');
    let ctx: ReturnType<typeof useAuth> | null = null;
    render(<AuthProvider><Capture onReady={(v) => { ctx = v; }} /></AuthProvider>);
    await waitFor(() => expect(ctx?.csrfToken).toBe('the-token'));

    (global.fetch as jest.Mock).mockClear();
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });

    await act(async () => {
      await ctx!.apiFetch('/api/auth/logout', { method: 'POST' });
    });
    const postCall = (global.fetch as jest.Mock).mock.calls.find((c) => c[0].includes('/api/auth/logout'));
    expect(postCall).toBeTruthy();
    const headers = postCall[1].headers as Headers;
    expect(headers.get('X-CSRF-Token')).toBe('the-token');

    (global.fetch as jest.Mock).mockClear();
    await act(async () => {
      await ctx!.apiFetch('/api/race-data', { method: 'GET' });
    });
    const getCall = (global.fetch as jest.Mock).mock.calls.find((c) => c[0].includes('/api/race-data'));
    expect(getCall).toBeTruthy();
    const getHeaders = getCall[1].headers as Headers;
    expect(getHeaders.get('X-CSRF-Token')).toBeNull();
  });

  test('login returns email_not_verified result', async () => {
    seedFetch('t');
    let ctx: ReturnType<typeof useAuth> | null = null;
    render(<AuthProvider><Capture onReady={(v) => { ctx = v; }} /></AuthProvider>);
    await waitFor(() => expect(ctx?.csrfToken).toBe('t'));

    (global.fetch as jest.Mock).mockImplementationOnce(() =>
      Promise.resolve({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ error: 'email_not_verified', email: 'a@b' }),
      }),
    );

    let result: Awaited<ReturnType<typeof ctx.login>> | null = null;
    await act(async () => {
      result = await ctx!.login('a', 'a-very-long-password', 't');
    });
    expect(result).toEqual({ ok: false, code: 'email_not_verified', email: 'a@b' });
  });

  test('login returns ok on success', async () => {
    seedFetch('t');
    let ctx: ReturnType<typeof useAuth> | null = null;
    render(<AuthProvider><Capture onReady={(v) => { ctx = v; }} /></AuthProvider>);
    await waitFor(() => expect(ctx?.csrfToken).toBe('t'));

    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.endsWith('/api/auth/login')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ success: true, user: { id: 1, username: 'u', email: 'e@x', role: 'user' } }),
        });
      }
      if (url.endsWith('/api/auth/csrf')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ csrfToken: 't2' }) });
      }
      if (url.endsWith('/api/auth/check')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ authenticated: true, user: { id: 1, username: 'u', email: 'e@x', role: 'user' } }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    let result: Awaited<ReturnType<typeof ctx.login>> | null = null;
    await act(async () => {
      result = await ctx!.login('u', 'a-very-long-password', 't');
    });
    expect(result?.ok).toBe(true);
  });
});
