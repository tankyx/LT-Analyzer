import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockPush = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({ get: (k: string) => (k === 'token' ? 'reset-tok' : null) }),
}));

jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://api.test',
  TURNSTILE_SITE_KEY: '',
  INVITE_REQUIRED: true,
}));

import ForgotPasswordPage from '@/app/forgot-password/page';
import ResetPasswordPage from '@/app/reset-password/page';

beforeEach(() => {
  (global.fetch as unknown) = jest.fn();
  mockPush.mockClear();
});

describe('ForgotPasswordPage', () => {
  test('shows generic success message regardless of email existence', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: () => Promise.resolve({ success: true }) });
    render(<ForgotPasswordPage />);
    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'ghost@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));
    await waitFor(() => expect(screen.getByText(/If that email exists/i)).toBeInTheDocument());
  });
});

describe('ResetPasswordPage', () => {
  test('rejects weak password client-side without calling API', async () => {
    render(<ResetPasswordPage />);
    fireEvent.change(screen.getByPlaceholderText(/New password/), { target: { value: 'short' } });
    fireEvent.change(screen.getByPlaceholderText(/Confirm new password/), { target: { value: 'short' } });
    fireEvent.click(screen.getByRole('button', { name: /Save new password/i }));
    await waitFor(() => expect(screen.getByText(/at least 12 characters/i)).toBeInTheDocument());
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('rejects mismatched passwords', async () => {
    render(<ResetPasswordPage />);
    fireEvent.change(screen.getByPlaceholderText(/New password/), { target: { value: 'long-strong-pass' } });
    fireEvent.change(screen.getByPlaceholderText(/Confirm new password/), { target: { value: 'different-pass-1' } });
    fireEvent.click(screen.getByRole('button', { name: /Save new password/i }));
    await waitFor(() => expect(screen.getByText(/do not match/i)).toBeInTheDocument());
  });

  test('redirects to /login?reset=ok on success', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: () => Promise.resolve({ success: true }) });
    render(<ResetPasswordPage />);
    fireEvent.change(screen.getByPlaceholderText(/New password/), { target: { value: 'good-password-12' } });
    fireEvent.change(screen.getByPlaceholderText(/Confirm new password/), { target: { value: 'good-password-12' } });
    fireEvent.click(screen.getByRole('button', { name: /Save new password/i }));
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/login?reset=ok'));
  });

  test('shows expired token error', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ error: 'expired_token' }),
    });
    render(<ResetPasswordPage />);
    fireEvent.change(screen.getByPlaceholderText(/New password/), { target: { value: 'good-password-12' } });
    fireEvent.change(screen.getByPlaceholderText(/Confirm new password/), { target: { value: 'good-password-12' } });
    fireEvent.click(screen.getByRole('button', { name: /Save new password/i }));
    await waitFor(() => expect(screen.getByText(/expired/i)).toBeInTheDocument());
  });
});
