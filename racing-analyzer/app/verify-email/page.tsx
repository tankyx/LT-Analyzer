'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { API_BASE_URL } from '../../utils/config';
import TurnstileWidget from '../components/TurnstileWidget';

function VerifyEmailInner() {
  const search = useSearchParams();
  const token = search.get('token') || '';
  const [status, setStatus] = useState<'pending' | 'ok' | 'expired' | 'invalid' | 'error'>('pending');

  useEffect(() => {
    if (!token) {
      setStatus('invalid');
      return;
    }
    (async () => {
      try {
        const resp = await fetch(`${API_BASE_URL}/api/auth/verify-email`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ token }),
        });
        if (resp.ok) {
          setStatus('ok');
          return;
        }
        const data = await resp.json().catch(() => ({}));
        if (data.error === 'expired_token') setStatus('expired');
        else if (data.error === 'invalid_token') setStatus('invalid');
        else setStatus('error');
      } catch {
        setStatus('error');
      }
    })();
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900 text-white">
      <div className="max-w-md p-6 bg-gray-800 rounded-md text-center space-y-4">
        {status === 'pending' && <p>Verifying your email…</p>}
        {status === 'ok' && (
          <>
            <h2 className="text-2xl font-bold">Email verified ✓</h2>
            <p className="text-sm text-gray-300">You can now sign in.</p>
            <Link href="/login" className="inline-block px-4 py-2 bg-blue-600 rounded-md">Sign in</Link>
          </>
        )}
        {status === 'expired' && <ResendForm reason="expired" />}
        {status === 'invalid' && <ResendForm reason="invalid" />}
        {status === 'error' && (
          <>
            <p>Something went wrong on our side. Try again in a minute.</p>
            <Link href="/login" className="text-blue-300 underline">Back to login</Link>
          </>
        )}
      </div>
    </div>
  );
}

function ResendForm({ reason }: { reason: 'expired' | 'invalid' }) {
  const [email, setEmail] = useState('');
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!turnstileToken) return;
    try {
      await fetch(`${API_BASE_URL}/api/auth/resend-verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, turnstile_token: turnstileToken }),
      });
    } finally {
      setDone(true);
    }
  };

  if (done) {
    return (
      <>
        <p>If that email exists and is unverified, a fresh link is on its way.</p>
        <Link href="/login" className="text-blue-300 underline">Back to login</Link>
      </>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <h2 className="text-2xl font-bold">
        {reason === 'expired' ? 'Link expired' : 'Link is invalid'}
      </h2>
      <p className="text-sm text-gray-300">Enter your email and we&apos;ll send a fresh verification link.</p>
      <input
        type="email"
        required
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="block w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white placeholder-gray-500"
      />
      <TurnstileWidget onVerify={setTurnstileToken} onExpire={() => setTurnstileToken(null)} />
      <button type="submit" className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 rounded-md">
        Resend verification
      </button>
    </form>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-900" />}>
      <VerifyEmailInner />
    </Suspense>
  );
}
