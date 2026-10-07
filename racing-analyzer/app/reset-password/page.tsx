'use client';

import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { API_BASE_URL } from '../../utils/config';

function ResetPasswordInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password.length < 12) {
      setError('Password must be at least 12 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ token, new_password: password }),
      });
      if (resp.ok) {
        router.push('/login?reset=ok');
        return;
      }
      const data = await resp.json().catch(() => ({}));
      if (data.error === 'expired_token') setError('This reset link has expired. Request a new one.');
      else if (data.error === 'invalid_token') setError('This reset link is invalid.');
      else if (data.error === 'weak_password') setError('Password must be at least 12 characters.');
      else setError('Could not reset password. Try requesting a new link.');
    } catch {
      setError('Network error. Try again in a moment.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-canvas text-ink">
      <div className="max-w-md w-full p-6 bg-surface rounded-md space-y-4">
        <h2 className="text-center text-2xl font-bold">Set a new password</h2>
        <form className="space-y-3" onSubmit={submit}>
          <input
            type="password"
            required
            placeholder="New password (min 12 chars)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="block w-full px-3 py-2 bg-canvas border border-line rounded-md placeholder:text-muted"
          />
          <input
            type="password"
            required
            placeholder="Confirm new password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="block w-full px-3 py-2 bg-canvas border border-line rounded-md placeholder:text-muted"
          />
          {error && (
            <div className="rounded-md bg-alarm/15 p-3 text-sm text-alarm">{error}</div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-4 bg-info hover:bg-info rounded-md disabled:opacity-50"
          >
            {loading ? 'Saving…' : 'Save new password'}
          </button>
          <p className="text-sm text-muted text-center">
            <Link href="/forgot-password" className="text-info hover:underline">
              Need a new reset link?
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-canvas" />}>
      <ResetPasswordInner />
    </Suspense>
  );
}
