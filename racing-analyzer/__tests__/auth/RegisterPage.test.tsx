import { render, screen, fireEvent, waitFor } from '@testing-library/react';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://api.test',
  TURNSTILE_SITE_KEY: '',  // dev short-circuit, widget auto-verifies
  INVITE_REQUIRED: true,
}));

import RegisterPage from '@/app/register/page';

describe('RegisterPage', () => {
  beforeEach(() => {
    (global.fetch as unknown) = jest.fn();
  });

  const fillForm = () => {
    fireEvent.change(screen.getByPlaceholderText('Username'), { target: { value: 'newuser' } });
    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'new@example.com' } });
    fireEvent.change(screen.getByPlaceholderText(/Password \(min 12/), { target: { value: 'longpassword12' } });
    fireEvent.change(screen.getByPlaceholderText('Confirm password'), { target: { value: 'longpassword12' } });
    fireEvent.change(screen.getByPlaceholderText('Invite code'), { target: { value: 'abc123' } });
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);
  };

  test('mismatched passwords show error and do not submit', async () => {
    render(<RegisterPage />);
    fillForm();
    fireEvent.change(screen.getByPlaceholderText('Confirm password'), { target: { value: 'different-12' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(screen.getByText(/Passwords do not match/)).toBeInTheDocument());
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('terms must be accepted', async () => {
    render(<RegisterPage />);
    fillForm();
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);  // uncheck
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(screen.getByText(/must accept the terms/i)).toBeInTheDocument());
  });

  test('shows success screen on 200 response', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true }),
    });
    render(<RegisterPage />);
    fillForm();
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(screen.getByText(/Check your inbox/i)).toBeInTheDocument());
  });

  test('shows generic error on 400 response', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ error: 'registration_failed' }),
    });
    render(<RegisterPage />);
    fillForm();
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(screen.getByText(/Registration failed/i)).toBeInTheDocument());
  });

  test('shows rate-limit error on 429', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      status: 429,
      json: () => Promise.resolve({ error: 'rate_limited' }),
    });
    render(<RegisterPage />);
    fillForm();
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(screen.getByText(/Too many attempts/i)).toBeInTheDocument());
  });

  test('sends expected payload to /api/auth/register', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true }),
    });
    render(<RegisterPage />);
    fillForm();
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain('/api/auth/register');
    const body = JSON.parse(init.body);
    expect(body.username).toBe('newuser');
    expect(body.email).toBe('new@example.com');
    expect(body.password).toBe('longpassword12');
    expect(body.invite_code).toBe('abc123');
    expect(body.accept_terms).toBe(true);
    expect(typeof body.turnstile_token).toBe('string');
  });
});
