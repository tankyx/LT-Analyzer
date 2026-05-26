'use client';

import { useState } from 'react';
import Link from 'next/link';
import { API_BASE_URL } from '../../utils/config';
import TurnstileWidget from '../components/TurnstileWidget';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!turnstileToken) return;
    setLoading(true);
    try {
      await fetch(`${API_BASE_URL}/api/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, turnstile_token: turnstileToken }),
      });
    } finally {
      setSent(true);
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900 text-white">
      <div className="max-w-md w-full p-6 bg-gray-800 rounded-md space-y-4">
        <h2 className="text-center text-2xl font-bold">Reset your password</h2>
        {sent ? (
          <>
            <p className="text-sm text-gray-300">
              If that email exists in our system, we sent a reset link. The link is good for 1 hour.
            </p>
            <Link href="/login" className="text-blue-300 underline">Back to sign in</Link>
          </>
        ) : (
          <form className="space-y-3" onSubmit={submit}>
            <input
              type="email"
              required
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="block w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-md placeholder-gray-500"
            />
            <TurnstileWidget onVerify={setTurnstileToken} onExpire={() => setTurnstileToken(null)} />
            <button
              type="submit"
              disabled={loading || !turnstileToken}
              className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 rounded-md disabled:opacity-50"
            >
              {loading ? 'Sending…' : 'Send reset link'}
            </button>
            <p className="text-sm text-gray-400 text-center">
              <Link href="/login" className="text-blue-300 hover:underline">Cancel</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
