'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUp, Info, RefreshCw } from 'lucide-react';
import ApiService from '../../services/ApiService';

export interface PaceStint {
  stint_index: number;
  start_ts: string;
  end_ts: string;
  lap_count: number;
  mean: number;
  best: number;
  field_median: number | null;
  field_laps: number;
  field_basis: string;
  residual: number | null;
  confidence: 'low' | 'medium' | 'high';
}

export interface PaceReport {
  team: string;
  matched_team: string | null;
  session_id: number | null;
  stints: PaceStint[];
  current: PaceStint | null;
  current_laps?: number[];
  recent: { laps: number; mean: number; residual: number } | null;
  trend: 'improving' | 'stable' | 'fading' | 'unknown';
  trend_drift: number | null;
  field_ref_seconds: number | null;
  own_norm_residual: number | null;
  kart: { fleet_kart_id: number; label: string } | null;
  verdict: {
    verdict: 'keep' | 'consider_switch' | 'switch' | 'watch' | 'insufficient';
    reason: string;
    delta_vs_own_norm: number | null;
    band: number | null;
  };
}

interface PaceMonitorProps {
  trackId: number;
  /** Team name as the timing feed spells it. Empty when none is chosen. */
  teamName: string;
  sessionId?: number | null;
  /** Bumped by the dashboard on each live update, to trigger a throttled refetch. */
  updateTick?: number;
  isActive?: boolean;
}

/** Seconds a lap, signed, with a true minus sign. Negative is faster. */
export const formatDelta = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
  const sign = seconds < 0 ? '−' : '+';
  return `${sign}${Math.abs(seconds).toFixed(2)}s`;
};

/** Faster than the reference is good; the sign alone decides the colour. */
export const paceTone = (residual: number | null | undefined): string => {
  if (residual === null || residual === undefined) return 'text-muted';
  if (residual < -0.1) return 'text-live';
  if (residual > 0.1) return 'text-alarm';
  return 'text-ink';
};

const VERDICT_COPY: Record<PaceReport['verdict']['verdict'], { title: string; tone: string }> = {
  keep: { title: 'Keep this kart', tone: 'border-live/50 bg-live/10 text-live' },
  watch: { title: 'Watch it', tone: 'border-accent/60 bg-accent/10 text-accent' },
  consider_switch: { title: 'Consider switching', tone: 'border-accent/60 bg-accent/10 text-accent' },
  switch: { title: 'Switch at the next stop', tone: 'border-alarm/60 bg-alarm/10 text-alarm' },
  insufficient: { title: 'Not enough laps yet', tone: 'border-line bg-surface-2 text-muted' },
};

const TREND_COPY: Record<PaceReport['trend'], { label: string; icon: React.ReactNode; tone: string }> = {
  improving: { label: 'Coming to us', icon: <ArrowDown size={14} />, tone: 'text-live' },
  stable: { label: 'Holding', icon: <ArrowRight size={14} />, tone: 'text-ink' },
  fading: { label: 'Fading', icon: <ArrowUp size={14} />, tone: 'text-alarm' },
  unknown: { label: 'Too early to say', icon: <ArrowRight size={14} />, tone: 'text-muted' },
};

const REFRESH_THROTTLE_MS = 5000;

/**
 * Live read on how the team is actually going, independent of track position:
 * pace against the field at the same moment, stint by stint, and whether the
 * kart underneath is worth keeping.
 */
const PaceMonitor: React.FC<PaceMonitorProps> = ({
  trackId,
  teamName,
  sessionId,
  updateTick = 0,
  isActive = true,
}) => {
  const [report, setReport] = useState<PaceReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const lastFetchRef = useRef(0);

  const load = useCallback(async () => {
    if (!teamName || !trackId) return;
    lastFetchRef.current = Date.now();
    setLoading(true);
    try {
      const data = await ApiService.getTeamPace(trackId, teamName, sessionId ?? undefined);
      setReport(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load pace');
    } finally {
      setLoading(false);
    }
  }, [trackId, teamName, sessionId]);

  useEffect(() => {
    if (!isActive) return;
    load();
  }, [isActive, load]);

  // Follow the live feed, but no faster than the throttle.
  useEffect(() => {
    if (!isActive || updateTick === 0) return;
    if (Date.now() - lastFetchRef.current < REFRESH_THROTTLE_MS) return;
    load();
  }, [updateTick, isActive, load]);

  if (!teamName) {
    return (
      <div className="p-6 text-center text-muted text-sm">
        Choose your team above to track its pace.
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 flex flex-col items-center gap-3 text-center">
        <p className="text-sm text-muted">
          {error === 'no_active_session' ? 'No session running on this track yet.' : error}
        </p>
        <button
          type="button"
          onClick={load}
          className="h-10 px-4 rounded-lg border border-line bg-surface-2 text-sm font-semibold"
        >
          Try again
        </button>
      </div>
    );
  }

  if (!report) {
    return <div className="p-6 text-center text-sm text-muted">Reading lap times…</div>;
  }

  const { current, recent, verdict, kart, trend } = report;
  const verdictCopy = VERDICT_COPY[verdict.verdict] || VERDICT_COPY.insufficient;
  const trendCopy = TREND_COPY[trend] || TREND_COPY.unknown;
  const worst = report.stints.reduce<number | null>(
    (acc, s) => (s.residual === null ? acc : acc === null || s.residual > acc ? s.residual : acc), null);
  const best = report.stints.reduce<number | null>(
    (acc, s) => (s.residual === null ? acc : acc === null || s.residual < acc ? s.residual : acc), null);

  return (
    <div className="p-3 md:p-4 flex flex-col gap-3">
      {/* Verdict — the one thing a crew needs at a glance. */}
      <div className={`rounded-xl border p-3 md:p-4 ${verdictCopy.tone}`}>
        <div className="flex items-center justify-between gap-3">
          <span className="font-cond font-bold text-xl md:text-2xl tracking-wide uppercase">
            {verdictCopy.title}
          </span>
          {kart && (
            <span className="font-mono tabular text-xs px-2 py-1 rounded-md bg-surface/70 text-ink shrink-0">
              {kart.label}
            </span>
          )}
        </div>
        <p className="text-sm mt-1 text-ink/90">{verdict.reason}</p>
      </div>

      {/* Pace now, against the field at the same moment. */}
      <div className="rounded-xl border border-line bg-surface p-3 md:p-4 grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] md:text-[11px] font-bold tracking-[.08em] uppercase text-muted">
            This stint vs field
          </span>
          <span className={`font-mono tabular text-2xl md:text-3xl font-semibold leading-none ${paceTone(current?.residual)}`}>
            {formatDelta(current?.residual)}
          </span>
          <span className="text-xs text-muted">
            {current ? `${current.lap_count} laps · ${current.confidence} confidence` : 'no laps yet'}
          </span>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-[10px] md:text-[11px] font-bold tracking-[.08em] uppercase text-muted">
            Last {recent?.laps ?? 5} laps
          </span>
          <span className={`font-mono tabular text-2xl md:text-3xl font-semibold leading-none ${paceTone(recent?.residual)}`}>
            {formatDelta(recent?.residual)}
          </span>
          <span className={`text-xs flex items-center gap-1 ${trendCopy.tone}`}>
            {trendCopy.icon}
            {trendCopy.label}
          </span>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-[10px] md:text-[11px] font-bold tracking-[.08em] uppercase text-muted">
            Your normal pace
          </span>
          <span className="font-mono tabular text-2xl md:text-3xl font-semibold leading-none text-ink">
            {formatDelta(report.own_norm_residual)}
          </span>
          <span className="text-xs text-muted">across earlier stints</span>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-[10px] md:text-[11px] font-bold tracking-[.08em] uppercase text-muted">
            Field right now
          </span>
          <span className="font-mono tabular text-2xl md:text-3xl font-semibold leading-none text-ink">
            {report.field_ref_seconds ? `${report.field_ref_seconds.toFixed(2)}s` : '—'}
          </span>
          <span className="text-xs text-muted">median lap</span>
        </div>
      </div>

      {/* Stint by stint. */}
      <div className="rounded-xl border border-line bg-surface overflow-hidden">
        <div className="flex items-center justify-between px-3 md:px-4 h-11 border-b border-line bg-surface-2">
          <h3 className="font-cond font-bold text-lg tracking-wide">STINTS</h3>
          <button
            type="button"
            onClick={load}
            aria-label="Refresh pace"
            className="w-9 h-9 rounded-lg flex items-center justify-center text-muted hover:text-ink hover:bg-surface"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        {report.stints.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted">
            No clean laps recorded for {report.team} in this session yet.
          </div>
        ) : (
          <div className="divide-y divide-line">
            {report.stints.map((stint) => {
              const isCurrent = current !== null && stint.stint_index === current.stint_index;
              const isBest = stint.residual !== null && stint.residual === best && report.stints.length > 1;
              const isWorst = stint.residual !== null && stint.residual === worst && report.stints.length > 1;
              return (
                <div
                  key={stint.stint_index}
                  className={`flex items-center gap-3 px-3 md:px-4 py-2.5 ${isCurrent ? 'bg-accent/[.07]' : ''}`}
                >
                  <div className="w-8 h-8 rounded-lg bg-surface-2 font-cond font-bold flex items-center justify-center shrink-0">
                    {stint.stint_index + 1}
                  </div>
                  <div className="flex flex-col min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`font-mono tabular text-base font-semibold ${paceTone(stint.residual)}`}>
                        {formatDelta(stint.residual)}
                      </span>
                      {isCurrent && <span className="text-[10px] font-bold tracking-wide text-accent">CURRENT</span>}
                      {isBest && !isCurrent && <span className="text-[10px] font-bold tracking-wide text-live">BEST</span>}
                      {isWorst && !isCurrent && <span className="text-[10px] font-bold tracking-wide text-alarm">WORST</span>}
                    </div>
                    <span className="text-xs text-muted">
                      {stint.lap_count} laps · avg {stint.mean.toFixed(2)}s · best {stint.best.toFixed(2)}s
                    </span>
                  </div>
                  {stint.confidence === 'low' && (
                    <span className="text-[10px] text-muted shrink-0">thin sample</span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="px-3 md:px-4 py-2 border-t border-line bg-surface-2 text-xs text-muted flex items-start gap-1.5">
          <Info size={14} className="text-info shrink-0 mt-0.5" />
          <span>
            Pace is measured against the rest of the field at the same moment, so track
            conditions cancel out. It does not separate the kart from the driver, so read a
            slow stint alongside who was in the seat.
          </span>
        </div>
      </div>
    </div>
  );
};

export default PaceMonitor;
