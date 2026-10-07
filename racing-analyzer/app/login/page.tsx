'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '../contexts/AuthContext';
import { API_BASE_URL } from '../../utils/config';
import TurnstileWidget from '../components/TurnstileWidget';

function LoginInner() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);
  const [resendStatus, setResendStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const search = useSearchParams();
  const { login } = useAuth();
  const justReset = search.get('reset') === 'ok';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setUnverifiedEmail(null);
    setResendStatus(null);
    if (!turnstileToken) {
      setError('Please complete the captcha.');
      return;
    }
    setLoading(true);

    try {
      const result = await login(username, password, turnstileToken);
      if (result.ok) {
        router.push('/dashboard');
        return;
      }
      if (result.code === 'email_not_verified') {
        setUnverifiedEmail(result.email);
        setError('You need to verify your email before logging in.');
      } else if (result.code === 'rate_limited') {
        setError(result.message || 'Too many failed attempts. Try again later.');
      } else if (result.code === 'captcha_failed') {
        setError('Captcha failed. Please reload and try again.');
      } else {
        setError('Login failed. Check your credentials.');
      }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const resend = async () => {
    if (!unverifiedEmail || !turnstileToken) return;
    setResendStatus('Sending…');
    try {
      const resp = await fetch(`${API_BASE_URL}/api/auth/resend-verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: unverifiedEmail, turnstile_token: turnstileToken }),
      });
      setResendStatus(resp.ok ? 'If the email exists, a fresh link was sent.' : 'Could not send right now.');
    } catch {
      setResendStatus('Network error.');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center canvas text-ink p-4">
      <div className="w-full max-w-sm flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-[9px] accent-gradient text-accent-ink font-cond font-bold text-lg flex items-center justify-center">
            LT
          </div>
          <div className="flex flex-col">
            <span className="font-cond font-bold text-2xl tracking-wide leading-none">LT-ANALYZER</span>
            <span className="text-xs text-muted mt-1">Live timing analysis</span>
          </div>
        </div>

        <div className="rounded-2xl border border-line bg-surface p-5 md:p-6 flex flex-col gap-4">
          <h1 className="text-lg font-semibold">Sign in</h1>

          {justReset && (
            <div className="rounded-lg border border-live/50 bg-live/10 px-3 py-2 text-sm">
              Password updated. You can log in below.
            </div>
          )}

          <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-semibold text-muted">Username</span>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                required
                className="h-11 px-3 rounded-lg border border-line bg-canvas text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50"
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-semibold text-muted">Password</span>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                className="h-11 px-3 rounded-lg border border-line bg-canvas text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>

            <TurnstileWidget onVerify={setTurnstileToken} onExpire={() => setTurnstileToken(null)} />

            {error && (
              <div className="rounded-lg border border-alarm/50 bg-alarm/10 px-3 py-2">
                <p className="text-sm">{error}</p>
                {unverifiedEmail && (
                  <div className="mt-2 text-sm">
                    <button
                      type="button"
                      onClick={resend}
                      className="text-info underline"
                    >
                      Resend verification email
                    </button>
                    {resendStatus && <p className="mt-1 text-xs text-muted">{resendStatus}</p>}
                  </div>
                )}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="h-11 rounded-lg accent-gradient text-accent-ink font-bold text-sm hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:opacity-50"
            >
              {loading ? 'Logging in…' : 'Sign in'}
            </button>

            <div className="flex justify-between text-sm text-muted">
              <Link href="/forgot-password" className="hover:text-ink">Forgot password?</Link>
              <Link href="/register" className="hover:text-ink">Create account</Link>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen canvas" />}>
      <LoginInner />
    </Suspense>
  );
}
