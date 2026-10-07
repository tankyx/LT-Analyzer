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
      <div className="min-h-screen flex items-center justify-center bg-canvas text-ink">
        <div className="max-w-md p-6 bg-surface rounded-md text-center space-y-4">
          <h2 className="text-2xl font-bold">Check your inbox</h2>
          <p className="text-sm text-ink">
            We sent a verification link to <strong>{email}</strong>. Click the link to activate your account.
          </p>
          <p className="text-xs text-muted">It can take a minute to arrive. Don&apos;t see it? Check your spam folder.</p>
          <Link href="/login" className="text-info underline">Back to sign in</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-canvas py-12">
      <div className="max-w-md w-full space-y-4 px-4">
        <h2 className="text-center text-3xl font-extrabold text-ink">Create an account</h2>
        <form className="space-y-3" onSubmit={submit}>
          <input
            type="text"
            required
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="block w-full px-3 py-2 bg-surface border border-line rounded-md text-ink placeholder:text-muted"
          />
          <input
            type="email"
            required
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="block w-full px-3 py-2 bg-surface border border-line rounded-md text-ink placeholder:text-muted"
          />
          <input
            type="password"
            required
            placeholder="Password (min 12 characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="block w-full px-3 py-2 bg-surface border border-line rounded-md text-ink placeholder:text-muted"
          />
          {password && (
            <div className="h-1 w-full bg-surface-2 rounded overflow-hidden">
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
            className="block w-full px-3 py-2 bg-surface border border-line rounded-md text-ink placeholder:text-muted"
          />
          {INVITE_REQUIRED && (
            <input
              type="text"
              required
              placeholder="Invite code"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              className="block w-full px-3 py-2 bg-surface border border-line rounded-md text-ink placeholder:text-muted"
            />
          )}

          <label className="flex items-start space-x-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={acceptTerms}
              onChange={(e) => setAcceptTerms(e.target.checked)}
              className="mt-1"
            />
            <span>
              I accept the{' '}
              <Link href="/terms" className="text-info underline">terms</Link> and{' '}
              <Link href="/privacy" className="text-info underline">privacy policy</Link>.
            </span>
          </label>

          <TurnstileWidget onVerify={setTurnstileToken} onExpire={() => setTurnstileToken(null)} />

          {error && (
            <div className="rounded-md bg-alarm/15 p-3 text-sm text-alarm">{error}</div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-4 bg-info hover:bg-info text-white rounded-md disabled:opacity-50"
          >
            {loading ? 'Creating account...' : 'Create account'}
          </button>

          <p className="text-center text-sm text-muted">
            Already have an account?{' '}
            <Link href="/login" className="text-info hover:underline">Sign in</Link>
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
  if (score <= 1) return 'bg-alarm';
  if (score === 2) return 'bg-accent';
  if (score === 3) return 'bg-info';
  return 'bg-live';
}
