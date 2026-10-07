import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

const push = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const apiFetch = jest.fn();
let authState: { user: { id: number; username: string; email: string; role: string } | null; loading: boolean };
jest.mock('@/app/contexts/AuthContext', () => ({
  useAuth: () => ({ ...authState, apiFetch }),
}));

import DevicesPage from '@/app/devices/page';
import { formatSeen } from '@/app/devices/formatSeen';

const json = (body: unknown, status = 200) =>
  Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

describe('formatSeen', () => {
  test('null reads never, garbage passes through', () => {
    expect(formatSeen(null)).toBe('never');
    expect(formatSeen('not a date')).toBe('not a date');
  });
});

describe('DevicesPage', () => {
  beforeEach(() => {
    push.mockReset();
    apiFetch.mockReset();
    authState = { user: { id: 1, username: 'alice', email: 'a@x', role: 'user' }, loading: false };
  });

  test('redirects to login when signed out', () => {
    authState = { user: null, loading: false };
    render(<DevicesPage />);
    expect(push).toHaveBeenCalledWith('/login');
  });

  test('lists tokens and shows the plaintext once after creating one', async () => {
    const tokens = [
      { id: 7, label: 'datalogger-p4', created_at: '2026-09-18T10:00:00Z', expires_at: '2026-12-17T10:00:00Z',
        last_seen_at: null, revoked: false, online: true },
      { id: 2, label: 'lost-board', created_at: '2026-08-01T10:00:00Z', expires_at: '2026-10-30T10:00:00Z',
        last_seen_at: '2026-08-02T10:00:00Z', revoked: true, revoked_at: '2026-08-03T10:00:00Z', online: false },
    ];
    apiFetch.mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/api/device/tokens' && init?.method === 'POST') {
        return json({ id: 8, label: 'new-board', token: 'SECRET-TOKEN-VALUE', expires_at: '2026-12-17T10:00:00Z' }, 201);
      }
      if (path === '/api/device/tokens') return json({ tokens });
      return json({}, 404);
    });

    render(<DevicesPage />);
    expect(await screen.findByText('datalogger-p4')).toBeInTheDocument();
    expect(screen.getByLabelText('online')).toBeInTheDocument();
    expect(screen.getByText('lost-board')).toBeInTheDocument();
    expect(screen.getByText('Revoked (1)')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Device label'), { target: { value: 'new-board' } });
    fireEvent.click(screen.getByText('Create token'));
    expect(await screen.findByText('SECRET-TOKEN-VALUE')).toBeInTheDocument();
    const call = apiFetch.mock.calls.find((c) => c[1]?.method === 'POST');
    expect(JSON.parse(call![1].body)).toEqual({ label: 'new-board' });
  });

  test('pairing shows the code, then reports paired once the board redeems it', async () => {
    jest.useFakeTimers();
    let status = 'pending';
    const tokens: unknown[] = [];
    apiFetch.mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/api/device/pairing-codes' && init?.method === 'POST') {
        return json({ id: 3, label: 'kart-12', code: 'ABCD-EFGH',
                      expires_at: new Date(Date.now() + 600_000).toISOString(), expires_in: 600, status: 'pending' }, 201);
      }
      if (path === '/api/device/pairing-codes/3') return json({ id: 3, label: 'kart-12', status, token_id: status === 'paired' ? 9 : null });
      if (path === '/api/device/tokens') return json({ tokens });
      return json({}, 404);
    });
    try {
      render(<DevicesPage />);
      fireEvent.change(await screen.findByLabelText('Board name'), { target: { value: 'kart-12' } });
      fireEvent.click(screen.getByText('Get pairing code'));
      expect(await screen.findByTestId('pairing-code')).toHaveTextContent('ABCD-EFGH');
      expect(screen.getByText(/Waiting for the board/)).toBeInTheDocument();
      const call = apiFetch.mock.calls.find((c) => c[0] === '/api/device/pairing-codes' && c[1]?.method === 'POST');
      expect(JSON.parse(call![1].body)).toEqual({ label: 'kart-12' });

      status = 'paired';
      tokens.push({ id: 9, label: 'kart-12', created_at: '2026-09-18T10:00:00Z', expires_at: '2026-12-17T10:00:00Z',
                    last_seen_at: null, revoked: false, online: false });
      await act(async () => { jest.advanceTimersByTime(3100); });
      expect(await screen.findByRole('status')).toHaveTextContent(/is paired/);
      expect(await screen.findByText('Paired boards (1)')).toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  test('revoke asks first, then posts to the revoke route', async () => {
    const tokens = [
      { id: 7, label: 'datalogger-p4', created_at: '2026-09-18T10:00:00Z', expires_at: '2026-12-17T10:00:00Z',
        last_seen_at: null, revoked: false, online: false },
    ];
    apiFetch.mockImplementation((path: string) => {
      if (path === '/api/device/tokens/7/revoke') return json({ ok: true });
      return json({ tokens });
    });
    window.confirm = jest.fn(() => true);
    render(<DevicesPage />);
    fireEvent.click(await screen.findByLabelText('Revoke datalogger-p4'));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith('/api/device/tokens/7/revoke', expect.objectContaining({ method: 'POST' })),
    );
  });
});
