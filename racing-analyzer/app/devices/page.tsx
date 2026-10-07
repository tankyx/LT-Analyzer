'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Check, Copy, Cpu, Link2, Plus, Trash2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import type { DeviceToken } from '../components/RaceDashboard/PitAlertTarget';
import { formatSeen } from './formatSeen';

interface NewToken {
  id: number;
  label: string;
  token: string;
  expires_at: string;
}

interface PairingCode {
  id: number;
  label: string;
  code: string;
  expires_at: string;
}

type PairStatus = 'pending' | 'paired' | 'expired';

const PAIR_POLL_MS = 3000;

/**
 * Devices: pair a datalogger board with an 8-character code (the normal
 * path), or mint a raw token for scripts. Tokens can be revoked here.
 */
export default function DevicesPage() {
  const { user, loading: authLoading, apiFetch } = useAuth();
  const router = useRouter();
  const [tokens, setTokens] = useState<DeviceToken[]>([]);
  const [error, setError] = useState('');

  // Pairing flow
  const [pairLabel, setPairLabel] = useState('');
  const [pairing, setPairing] = useState<PairingCode | null>(null);
  const [pairStatus, setPairStatus] = useState<PairStatus>('pending');
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [pairBusy, setPairBusy] = useState(false);

  // Raw token flow (advanced)
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<NewToken | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.push('/login');
  }, [user, authLoading, router]);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch('/api/device/tokens');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setTokens(body.tokens ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load devices');
    }
  }, [apiFetch]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  // Poll the pairing code until the board redeems it or it expires.
  useEffect(() => {
    if (!pairing || pairStatus !== 'pending') return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await apiFetch(`/api/device/pairing-codes/${pairing.id}`);
        if (!r.ok || cancelled) return;
        const body = await r.json();
        if (body.status === 'paired') {
          setPairStatus('paired');
          void load();
        } else if (body.status === 'expired') {
          setPairStatus('expired');
        }
      } catch {
        /* transient; next tick retries */
      }
    };
    const timer = setInterval(tick, PAIR_POLL_MS);
    void tick();
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [pairing, pairStatus, apiFetch, load]);

  // Countdown shown beside the code.
  useEffect(() => {
    if (!pairing || pairStatus !== 'pending') return;
    const update = () => {
      const left = Math.max(0, Math.round((new Date(pairing.expires_at).getTime() - Date.now()) / 1000));
      setSecondsLeft(left);
      if (left === 0) setPairStatus('expired');
    };
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [pairing, pairStatus]);

  const startPairing = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setPairBusy(true);
    try {
      const r = await apiFetch('/api/device/pairing-codes', {
        method: 'POST',
        body: JSON.stringify({ label: pairLabel.trim() }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.error === 'invalid_label' ? 'Label must be 1–64 printable characters' : `HTTP ${r.status}`);
      setPairing(body);
      setPairStatus('pending');
      setPairLabel('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start pairing');
    } finally {
      setPairBusy(false);
    }
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const r = await apiFetch('/api/device/tokens', {
        method: 'POST',
        body: JSON.stringify({ label: label.trim() }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.error === 'invalid_label' ? 'Label must be 1–64 printable characters' : `HTTP ${r.status}`);
      setFresh(body);
      setCopied(false);
      setLabel('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the token');
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (t: DeviceToken) => {
    if (!window.confirm(`Revoke "${t.label}"? The board using it stops working on its next request.`)) return;
    setError('');
    try {
      const r = await apiFetch(`/api/device/tokens/${t.id}/revoke`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (fresh?.id === t.id) setFresh(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not revoke the token');
    }
  };

  const copy = async () => {
    if (!fresh) return;
    try {
      await navigator.clipboard.writeText(fresh.token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  if (authLoading || !user) {
    return (
      <div className="min-h-screen canvas text-ink flex items-center justify-center">
        <span className="text-muted text-sm">Loading…</span>
      </div>
    );
  }

  const active = tokens.filter((t) => !t.revoked);
  const revoked = tokens.filter((t) => t.revoked);
  const mm = String(Math.floor(secondsLeft / 60)).padStart(1, '0');
  const ss = String(secondsLeft % 60).padStart(2, '0');

  return (
    <div className="min-h-screen canvas text-ink">
      <div className="max-w-3xl mx-auto px-4 py-6 flex flex-col gap-5">
        <header className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => router.push('/dashboard')}
            aria-label="Back to dashboard"
            className="w-10 h-10 rounded-lg flex items-center justify-center hover:bg-surface-2"
          >
            <ArrowLeft size={18} />
          </button>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Cpu size={20} className="text-accent" />
            Devices
          </h1>
        </header>

        <p className="text-sm text-muted">
          A datalogger board reads your live timing and raises pit alerts without a browser login. Pair
          it with a short code: the board exchanges the code once for its own long-lived token, which you
          can revoke here if the board is lost.
        </p>

        {/* Pairing */}
        <section className="rounded-xl border border-line bg-surface p-4 flex flex-col gap-3" aria-label="Pair a board">
          <div className="text-xs font-bold tracking-[.08em] uppercase text-muted flex items-center gap-2">
            <Link2 size={14} />
            Pair a board
          </div>
          {!pairing || pairStatus !== 'pending' ? (
            <form onSubmit={startPairing} className="flex flex-col sm:flex-row gap-2">
              <input
                value={pairLabel}
                onChange={(e) => setPairLabel(e.target.value)}
                placeholder="Board name, e.g. datalogger-p4"
                maxLength={64}
                required
                aria-label="Board name"
                className="flex-1 h-11 rounded-lg border border-line bg-canvas px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
              />
              <button
                type="submit"
                disabled={pairBusy || !pairLabel.trim()}
                className="h-11 px-4 rounded-lg bg-accent text-accent-ink font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-50"
              >
                <Link2 size={16} />
                {pairBusy ? 'Starting…' : 'Get pairing code'}
              </button>
            </form>
          ) : null}

          {pairing && pairStatus === 'pending' && (
            <div className="flex flex-col items-center gap-2 py-2" aria-live="polite">
              <div className="text-sm text-muted">
                Enter this code on <span className="font-semibold text-ink">{pairing.label}</span>
              </div>
              <div className="font-mono tabular text-4xl md:text-5xl font-bold tracking-[.12em] select-all" data-testid="pairing-code">
                {pairing.code}
              </div>
              <div className="text-xs text-muted flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-live animate-live-blink" />
                Waiting for the board… expires in {mm}:{ss}
              </div>
              <button
                type="button"
                onClick={() => setPairing(null)}
                className="text-xs text-muted underline hover:text-ink"
              >
                Cancel
              </button>
            </div>
          )}

          {pairing && pairStatus === 'paired' && (
            <div role="status" className="rounded-lg border border-live/60 bg-live/10 px-3 py-2 text-sm flex items-center gap-2">
              <Check size={16} className="text-live" />
              <span>
                <span className="font-semibold">{pairing.label}</span> is paired. The board holds its token now.
              </span>
              <button type="button" onClick={() => setPairing(null)} className="ml-auto text-xs text-muted underline hover:text-ink">
                Pair another
              </button>
            </div>
          )}

          {pairing && pairStatus === 'expired' && (
            <div role="status" className="rounded-lg border border-accent/50 bg-accent/10 px-3 py-2 text-sm flex items-center gap-2">
              The code for <span className="font-semibold">{pairing.label}</span> expired before the board used it.
              <button type="button" onClick={() => setPairing(null)} className="ml-auto text-xs underline">
                Try again
              </button>
            </div>
          )}
        </section>

        {error && (
          <div role="alert" className="rounded-lg border border-alarm/50 bg-alarm/10 px-3 py-2 text-sm text-alarm">
            {error}
          </div>
        )}

        {/* Token list */}
        <section className="rounded-xl border border-line bg-surface overflow-hidden" aria-label="Device tokens">
          <div className="px-4 py-3 border-b border-line text-xs font-bold tracking-[.08em] uppercase text-muted">
            Paired boards ({active.length})
          </div>
          {active.length === 0 ? (
            <div className="px-4 py-6 text-sm text-muted">No boards paired yet.</div>
          ) : (
            <ul>
              {active.map((t) => (
                <li key={t.id} className="px-4 py-3 border-b border-line last:border-b-0 flex items-center gap-3">
                  <span
                    className={`w-2.5 h-2.5 rounded-full shrink-0 ${t.online ? 'bg-live' : 'bg-line'}`}
                    title={t.online ? 'Streaming now' : 'Not connected'}
                    aria-label={t.online ? 'online' : 'offline'}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold truncate">{t.label}</div>
                    <div className="text-xs text-muted">
                      Created {formatSeen(t.created_at)} · Last seen {formatSeen(t.last_seen_at)} · Expires{' '}
                      {formatSeen(t.expires_at)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => revoke(t)}
                    aria-label={`Revoke ${t.label}`}
                    className="shrink-0 h-10 px-3 rounded-lg text-sm font-medium text-alarm hover:bg-alarm/10 flex items-center gap-1.5"
                  >
                    <Trash2 size={15} />
                    <span className="hidden sm:inline">Revoke</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {revoked.length > 0 && (
          <section className="rounded-xl border border-line bg-surface overflow-hidden" aria-label="Revoked tokens">
            <div className="px-4 py-3 border-b border-line text-xs font-bold tracking-[.08em] uppercase text-muted">
              Revoked ({revoked.length})
            </div>
            <ul>
              {revoked.map((t) => (
                <li key={t.id} className="px-4 py-3 border-b border-line last:border-b-0 text-sm text-muted flex items-center gap-3">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0 bg-line" />
                  <span className="flex-1 truncate line-through">{t.label}</span>
                  <span className="text-xs">Revoked {formatSeen(t.revoked_at)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Advanced: raw token */}
        <details className="rounded-xl border border-line bg-surface">
          <summary className="cursor-pointer px-4 py-3 text-xs font-bold tracking-[.08em] uppercase text-muted select-none">
            Advanced: create a raw token (scripts, curl)
          </summary>
          <div className="px-4 pb-4 flex flex-col gap-3">
            <form onSubmit={create} className="flex flex-col sm:flex-row gap-2">
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Label, e.g. laptop-curl"
                maxLength={64}
                required
                aria-label="Device label"
                className="flex-1 h-11 rounded-lg border border-line bg-canvas px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
              />
              <button
                type="submit"
                disabled={busy || !label.trim()}
                className="h-11 px-4 rounded-lg border border-line bg-surface-2 font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-50"
              >
                <Plus size={16} />
                {busy ? 'Creating…' : 'Create token'}
              </button>
            </form>

            {fresh && (
              <section className="rounded-xl border border-live/60 bg-live/10 p-4 flex flex-col gap-3" aria-label="New token">
                <div className="text-sm font-semibold">
                  Token for <span className="font-mono">{fresh.label}</span> — shown once, copy it now.
                </div>
                <div className="flex items-stretch gap-2">
                  <code className="flex-1 min-w-0 rounded-lg border border-line bg-canvas px-3 py-2 font-mono text-xs break-all select-all">
                    {fresh.token}
                  </code>
                  <button
                    type="button"
                    onClick={copy}
                    aria-label="Copy token"
                    className="shrink-0 w-11 rounded-lg border border-line bg-surface flex items-center justify-center hover:bg-surface-2"
                  >
                    {copied ? <Check size={16} className="text-live" /> : <Copy size={16} />}
                  </button>
                </div>
                <div className="text-xs text-muted">
                  Expires {formatSeen(fresh.expires_at)}. Send it as <span className="font-mono">Authorization: Bearer …</span> on
                  <span className="font-mono"> /api/device/*</span>.
                </div>
              </section>
            )}
          </div>
        </details>
      </div>
    </div>
  );
}
