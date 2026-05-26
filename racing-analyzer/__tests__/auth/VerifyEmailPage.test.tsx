import { render, screen, waitFor } from '@testing-library/react';

let mockToken: string | null = 'verify-tok';

jest.mock('next/navigation', () => ({
  useSearchParams: () => ({ get: (k: string) => (k === 'token' ? mockToken : null) }),
}));

jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://api.test',
  TURNSTILE_SITE_KEY: '',
  INVITE_REQUIRED: true,
}));

import VerifyEmailPage from '@/app/verify-email/page';

beforeEach(() => {
  (global.fetch as unknown) = jest.fn();
  mockToken = 'verify-tok';
});

describe('VerifyEmailPage', () => {
  test('shows success state on 200', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: () => Promise.resolve({ success: true }) });
    render(<VerifyEmailPage />);
    await waitFor(() => expect(screen.getByText(/Email verified/i)).toBeInTheDocument());
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain('/api/auth/verify-email');
    expect(JSON.parse(init.body).token).toBe('verify-tok');
  });

  test('shows resend form on expired token', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ error: 'expired_token' }),
    });
    render(<VerifyEmailPage />);
    await waitFor(() => expect(screen.getByText(/Link expired/i)).toBeInTheDocument());
  });

  test('shows resend form on invalid token', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ error: 'invalid_token' }),
    });
    render(<VerifyEmailPage />);
    await waitFor(() => expect(screen.getByText(/Link is invalid/i)).toBeInTheDocument());
  });

  test('with no token, shows invalid state immediately', async () => {
    mockToken = null;
    render(<VerifyEmailPage />);
    await waitFor(() => expect(screen.getByText(/Link is invalid/i)).toBeInTheDocument());
  });
});
