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
    <div className="min-h-screen flex items-center justify-center bg-gray-900">
      <div className="max-w-md w-full space-y-6">
        <h2 className="mt-6 text-center text-3xl font-extrabold text-white">
          LT-Analyzer Login
        </h2>

        {justReset && (
          <div className="rounded-md bg-green-900 p-3 text-sm text-green-200">
            Password updated. You can log in below.
          </div>
        )}

        <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
          <div className="rounded-md shadow-sm -space-y-px">
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              required
              className="appearance-none rounded-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-t-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              className="appearance-none rounded-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-b-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <TurnstileWidget onVerify={setTurnstileToken} onExpire={() => setTurnstileToken(null)} />

          {error && (
            <div className="rounded-md bg-red-900 p-3">
              <p className="text-sm text-red-200">{error}</p>
              {unverifiedEmail && (
                <div className="mt-2 text-sm">
                  <button
                    type="button"
                    onClick={resend}
                    className="text-blue-300 underline"
                  >
                    Resend verification email
                  </button>
                  {resendStatus && <p className="mt-1 text-xs text-red-100">{resendStatus}</p>}
                </div>
              )}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
          >
            {loading ? 'Logging in...' : 'Sign in'}
          </button>

          <div className="flex justify-between text-sm text-gray-400">
            <Link href="/forgot-password" className="hover:text-blue-300">Forgot password?</Link>
            <Link href="/register" className="hover:text-blue-300">Create account</Link>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-900" />}>
      <LoginInner />
    </Suspense>
  );
}
