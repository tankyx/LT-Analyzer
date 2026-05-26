'use client';

import { useState } from 'react';
import Link from 'next/link';
import { API_BASE_URL, INVITE_REQUIRED } from '../../utils/config';
import TurnstileWidget from '../components/TurnstileWidget';

export default function RegisterPage() {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [acceptTerms, setAcceptTerms] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  const score = passwordScore(password);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 12) {
      setError('Password must be at least 12 characters.');
      return;
    }
    if (!acceptTerms) {
      setError('You must accept the terms and privacy policy.');
      return;
    }
    if (!turnstileToken) {
      setError('Please complete the captcha.');
      return;
    }
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          username,
          email,
          password,
          invite_code: inviteCode,
          accept_terms: true,
          turnstile_token: turnstileToken,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data.success) {
        setSubmitted(true);
        return;
      }
      if (resp.status === 429) {
        setError('Too many attempts. Try again later.');
      } else if (data.error === 'weak_password') {
        setError('Password must be at least 12 characters.');
      } else if (data.error === 'invalid_username') {
        setError('Username must be 3–32 characters, letters/numbers/_-. only, and not a reserved name.');
      } else if (data.error === 'invalid_email') {
        setError('That email address does not look valid.');
      } else if (data.error === 'terms_not_accepted') {
        setError('You must accept the terms.');
      } else if (data.error === 'captcha_failed') {
        setError('Captcha failed. Reload and try again.');
      } else {
        setError('Registration failed. Check your inputs and try again.');
      }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900 text-white">
        <div className="max-w-md p-6 bg-gray-800 rounded-md text-center space-y-4">
          <h2 className="text-2xl font-bold">Check your inbox</h2>
          <p className="text-sm text-gray-300">
            We sent a verification link to <strong>{email}</strong>. Click the link to activate your account.
          </p>
          <p className="text-xs text-gray-400">It can take a minute to arrive. Don&apos;t see it? Check your spam folder.</p>
          <Link href="/login" className="text-blue-300 underline">Back to sign in</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900 py-12">
      <div className="max-w-md w-full space-y-4 px-4">
        <h2 className="text-center text-3xl font-extrabold text-white">Create an account</h2>
        <form className="space-y-3" onSubmit={submit}>
          <input
            type="text"
            required
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="block w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white placeholder-gray-500"
          />
          <input
            type="email"
            required
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="block w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white placeholder-gray-500"
          />
          <input
            type="password"
            required
            placeholder="Password (min 12 characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="block w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white placeholder-gray-500"
          />
          {password && (
            <div className="h-1 w-full bg-gray-700 rounded overflow-hidden">
              <div
                className={`h-1 ${strengthColor(score)}`}
                style={{ width: `${(score / 4) * 100}%` }}
              />
            </div>
          )}
          <input
            type="password"
            required
            placeholder="Confirm password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="block w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white placeholder-gray-500"
          />
          {INVITE_REQUIRED && (
            <input
              type="text"
              required
              placeholder="Invite code"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              className="block w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white placeholder-gray-500"
            />
          )}

          <label className="flex items-start space-x-2 text-sm text-gray-300">
            <input
              type="checkbox"
              checked={acceptTerms}
              onChange={(e) => setAcceptTerms(e.target.checked)}
              className="mt-1"
            />
            <span>
              I accept the{' '}
              <Link href="/terms" className="text-blue-300 underline">terms</Link> and{' '}
              <Link href="/privacy" className="text-blue-300 underline">privacy policy</Link>.
            </span>
          </label>

          <TurnstileWidget onVerify={setTurnstileToken} onExpire={() => setTurnstileToken(null)} />

          {error && (
            <div className="rounded-md bg-red-900 p-3 text-sm text-red-200">{error}</div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 text-white rounded-md disabled:opacity-50"
          >
            {loading ? 'Creating account...' : 'Create account'}
          </button>

          <p className="text-center text-sm text-gray-400">
            Already have an account?{' '}
            <Link href="/login" className="text-blue-300 hover:underline">Sign in</Link>
          </p>
        </form>
      </div>
    </div>
  );
}

function passwordScore(pw: string): number {
  let s = 0;
  if (pw.length >= 12) s++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
  if (/[0-9]/.test(pw)) s++;
  if (/[^a-zA-Z0-9]/.test(pw)) s++;
  return s;
}

function strengthColor(score: number): string {
  if (score <= 1) return 'bg-red-500';
  if (score === 2) return 'bg-yellow-500';
  if (score === 3) return 'bg-blue-500';
  return 'bg-green-500';
}
