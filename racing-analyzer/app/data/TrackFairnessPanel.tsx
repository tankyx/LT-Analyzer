'use client';

/**
 * Kart-draw fairness for one track: how consistent each driver's pace is
 * across sessions, and who is suspiciously consistent. Split out of the
 * Driver stats page; it owns its own filters and data.
 */
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import ApiService from '../services/ApiService';
import { CHART, seriesColor } from '../ui/chartTheme';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ScatterChart, Scatter, ZAxis, ReferenceLine, Cell,
} from 'recharts';
import type { Track, VarDefVerdict } from './types';

interface TrackFairnessDriver {
  name: string;
  sessions: number;
  pb: string;
  pb_seconds: number;
  mean_session_best_seconds: number;
  stddev_session_best_seconds: number;
  mean_gap_to_pb_pct: number;
  max_gap_to_pb_pct: number;
  pct_within_1pct_pb: number;
  pct_within_0_5pct_pb: number;
  mean_relative_pace: number | null;
  stddev_relative_pace: number | null;
  best_relative_pace: number | null;
  worst_relative_pace: number | null;
  vardef_n_sessions: number;
  vardef_observed_sd_seconds: number | null;
  vardef_expected_sd_seconds: number | null;
  vardef_ratio: number | null;
  vardef_p_value: number | null;
  vardef_verdict: VarDefVerdict;
}

type FairnessSortKey =
  | 'mean_gap_to_pb_pct'
  | 'stddev_session_best_seconds'
  | 'pct_within_1pct_pb'
  | 'sessions'
  | 'pb_seconds'
  | 'stddev_relative_pace'
  | 'mean_relative_pace'
  | 'vardef_ratio'
  | 'vardef_p_value';

interface SessionConfigsResponse {
  track_id: number;
  track_name: string;
  session_count: number;
  field_best_min: number | null;
  field_best_max: number | null;
  histogram: { field_best_bin: number; count: number }[];
  suggested_splits: { gap: number; below: number; above: number }[];
}

interface LayoutEntry {
  id: number;
  name: string;
  min_field_best: number | null;
  max_field_best: number | null;
  is_default: boolean;
}

export default function TrackFairnessPanel({ tracks }: { tracks: Track[] }) {
  const router = useRouter();
  const [trackId, setTrackId] = useState<number | null>(null);
  const [minSessions, setMinSessions] = useState<number>(5);
  const [minFieldBest, setMinFieldBest] = useState<string>('');
  const [maxFieldBest, setMaxFieldBest] = useState<string>('');
  const [layoutId, setLayoutId] = useState<number | null>(null);
  const [windowMonths, setWindowMonths] = useState<number>(12);
  const [layouts, setLayouts] = useState<LayoutEntry[]>([]);
  const [data, setData] = useState<TrackFairnessDriver[] | null>(null);
  const [configs, setConfigs] = useState<SessionConfigsResponse | null>(null);
  const [trackName, setTrackName] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<FairnessSortKey>('stddev_relative_pace');
  const [sortDesc, setSortDesc] = useState(false);

  // Default to first track once tracks load
  useEffect(() => {
    if (trackId === null && tracks.length > 0) setTrackId(tracks[0].id);
  }, [tracks, trackId]);

  // Load session-config histogram to help pick layout thresholds
  useEffect(() => {
    if (trackId === null) return;
    let cancelled = false;
    ApiService.getTrackSessionConfigs(trackId)
      .then(res => { if (!cancelled) setConfigs(res); })
      .catch(() => { if (!cancelled) setConfigs(null); });
    return () => { cancelled = true; };
  }, [trackId]);

  // Load layouts for the selected track
  useEffect(() => {
    if (trackId === null) { setLayouts([]); setLayoutId(null); return; }
    let cancelled = false;
    ApiService.getTrackLayouts(trackId)
      .then(res => {
        if (cancelled) return;
        const list: LayoutEntry[] = res?.layouts || [];
        setLayouts(list);
        // Reset selection whenever track changes; user opts in per track.
        setLayoutId(null);
      })
      .catch(() => {
        if (!cancelled) { setLayouts([]); setLayoutId(null); }
      });
    return () => { cancelled = true; };
  }, [trackId]);

  useEffect(() => {
    if (trackId === null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    const minFB = minFieldBest.trim() === '' ? undefined : parseFloat(minFieldBest);
    const maxFB = maxFieldBest.trim() === '' ? undefined : parseFloat(maxFieldBest);
    ApiService.getTrackKartFairness(trackId, minSessions, minFB, maxFB, layoutId, windowMonths)
      .then(res => {
        if (cancelled) return;
        setData(res.drivers || []);
        setTrackName(res.track_name || '');
      })
      .catch(err => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load kart fairness');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [trackId, minSessions, minFieldBest, maxFieldBest, layoutId, windowMonths]);

  const sortedDrivers = (() => {
    if (!data) return [];
    const copy = [...data];
    copy.sort((a, b) => {
      const dir = sortDesc ? -1 : 1;
      switch (sortKey) {
        case 'mean_gap_to_pb_pct':
          return dir * (a.mean_gap_to_pb_pct - b.mean_gap_to_pb_pct);
        case 'stddev_session_best_seconds':
          return dir * (a.stddev_session_best_seconds - b.stddev_session_best_seconds);
        case 'pct_within_1pct_pb':
          return dir * (b.pct_within_1pct_pb - a.pct_within_1pct_pb);
        case 'sessions':
          return dir * (a.sessions - b.sessions);
        case 'pb_seconds':
          return dir * (a.pb_seconds - b.pb_seconds);
        case 'stddev_relative_pace': {
          const av = a.stddev_relative_pace ?? 1e9;
          const bv = b.stddev_relative_pace ?? 1e9;
          return dir * (av - bv);
        }
        case 'mean_relative_pace': {
          const av = a.mean_relative_pace ?? 1e9;
          const bv = b.mean_relative_pace ?? 1e9;
          return dir * (av - bv);
        }
        case 'vardef_ratio': {
          // Lower ratio = less variance than typical fleet → suspect.
          const av = a.vardef_ratio ?? 99;
          const bv = b.vardef_ratio ?? 99;
          return dir * (av - bv);
        }
        case 'vardef_p_value': {
          // Smaller p = more significant variance deficit.
          const av = a.vardef_p_value ?? 2;
          const bv = b.vardef_p_value ?? 2;
          return dir * (av - bv);
        }
      }
    });
    return copy;
  })();

  const toggleSort = (k: FairnessSortKey) => {
    if (sortKey === k) {
      setSortDesc(!sortDesc);
    } else {
      setSortKey(k);
      setSortDesc(false);
    }
  };

  const headerCell = (k: FairnessSortKey, label: string) => (
    <th
      onClick={() => toggleSort(k)}
      className="px-3 py-2 text-ink cursor-pointer hover:text-ink select-none"
    >
      {label} {sortKey === k && (sortDesc ? '↓' : '↑')}
    </th>
  );

  // Scatter: each point is one driver. X = σRel, Y = MeanRel. Axis positions
  // are descriptive — tight, fast-relative-to-field drivers are in the
  // lower-left, but this mixes skill and kart-luck and is NOT by itself
  // evidence of favoritism. The variance-deficit panel above is the test
  // that speaks to "is the fleet's kart variation showing up in this
  // driver's outcomes?"
  const scatterData = (data || [])
    .filter(r => r.stddev_relative_pace !== null && r.mean_relative_pace !== null)
    .map(r => ({
      name: r.name,
      x: r.stddev_relative_pace as number,
      y: r.mean_relative_pace as number,
      sessions: r.sessions,
      pb: r.pb,
      worst: r.worst_relative_pace,
      vardefVerdict: r.vardef_verdict,
    }));

  const vardefFlagged = scatterData.filter(p => p.vardefVerdict === 'deficit_flagged');

  const fmtRel = (v: number) => v.toFixed(4);

  return (
    <div className="bg-surface p-6 mb-6 border border-line">
      <h2 className="text-xl font-semibold text-ink mb-2">Kart-Draw Fairness — {trackName || 'select a track'}</h2>
      <p className="text-sm text-muted mb-4">
        The direct test for kart-draw favouritism is the <b>variance-deficit test</b> below. For each of a driver&apos;s
        sessions we subtract that day&apos;s field-median from their session-best — this cancels the part of the swing
        that comes from track conditions (grip, temperature, wear), since those move the whole field together. What&apos;s
        left is the driver-specific variation: kart effect + execution noise. Under random kart draws the remaining
        spread should look similar across drivers. When a driver&apos;s residual σ is significantly smaller than the
        fleet-typical residual σ, the fleet&apos;s kart-to-kart noise isn&apos;t showing up in their outcomes —
        evidence of systematically favourable draws. The test doesn&apos;t need stable kart numbers across sessions;
        kart plates being shuffled between races doesn&apos;t break it.{' '}
        <span className="text-muted">
          σRel / MeanRel are shown for reference (consistency of relative pace) but mix skill and luck, so they
          are <u>not</u> by themselves evidence of favouritism.
        </span>
      </p>

      <div className="flex items-end gap-4 mb-4 flex-wrap">
        <div>
          <label className="block text-xs text-muted mb-1">Track</label>
          <select
            value={trackId ?? ''}
            onChange={e => setTrackId(parseInt(e.target.value))}
            className="px-3 py-2 bg-surface-2 text-ink"
          >
            {tracks.map(t => (
              <option key={t.id} value={t.id}>{t.track_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Min sessions</label>
          <input
            type="number"
            min={2}
            max={50}
            value={minSessions}
            onChange={e => {
              const v = parseInt(e.target.value);
              if (!isNaN(v)) setMinSessions(Math.max(2, Math.min(50, v)));
            }}
            className="w-20 px-3 py-2 bg-surface-2 text-ink"
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Layout</label>
          <select
            value={layoutId ?? ''}
            onChange={e => setLayoutId(e.target.value === '' ? null : parseInt(e.target.value))}
            disabled={layouts.length === 0}
            className="px-3 py-2 bg-surface-2 text-ink disabled:opacity-50"
          >
            <option value="">
              {layouts.length === 0 ? 'no layouts configured' : 'all layouts'}
            </option>
            {layouts.map(l => {
              const band = [
                l.min_field_best !== null ? `${l.min_field_best}s+` : '',
                l.max_field_best !== null ? `<${l.max_field_best}s` : '',
              ].filter(Boolean).join(' ');
              return (
                <option key={l.id} value={l.id}>
                  {l.name}{band ? ` (${band})` : ''}{l.is_default ? ' (default)' : ''}
                </option>
              );
            })}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Window (months)</label>
          <select
            value={windowMonths}
            onChange={e => setWindowMonths(parseInt(e.target.value))}
            className="px-3 py-2 bg-surface-2 text-ink"
          >
            <option value={3}>3</option>
            <option value={6}>6</option>
            <option value={12}>12</option>
            <option value={24}>24</option>
            <option value={0}>all</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Min field best (s)</label>
          <input
            type="number"
            step={0.5}
            value={minFieldBest}
            onChange={e => setMinFieldBest(e.target.value)}
            placeholder="any"
            className="w-24 px-3 py-2 bg-surface-2 text-ink"
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Max field best (s)</label>
          <input
            type="number"
            step={0.5}
            value={maxFieldBest}
            onChange={e => setMaxFieldBest(e.target.value)}
            placeholder="any"
            className="w-24 px-3 py-2 bg-surface-2 text-ink"
          />
        </div>
        <div className="flex flex-col text-xs text-muted max-w-xs">
          <span>Layout = physical track configuration (admins define bands in the admin panel).</span>
          <span>Window caps fleet-drift: a kart labelled #7 today isn&apos;t always the same hardware a year ago.</span>
        </div>
      </div>

      {configs && configs.session_count > 0 && (
        <div className="bg-canvas p-3 mb-4">
          <div className="text-xs text-muted mb-2">
            Session field-best distribution ({configs.session_count} sessions, {configs.field_best_min}s–{configs.field_best_max}s).
            Peaks = layouts. Suggested splits at largest gaps:{' '}
            {configs.suggested_splits.slice(0, 3).map((s, i) => (
              <span key={i} className="text-accent mr-2">
                {s.below}s ⇢ {s.above}s ({s.gap.toFixed(1)}s gap)
              </span>
            ))}
          </div>
          <div style={{ height: 100 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={configs.histogram} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                <XAxis
                  dataKey="field_best_bin"
                  stroke={CHART.axis}
                  tick={{ fill: CHART.axis, fontSize: 10 }}
                  tickFormatter={v => `${v}s`}
                />
                <YAxis stroke={CHART.axis} tick={{ fill: CHART.axis, fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: CHART.tooltipBg, border: `1px solid ${CHART.grid}`, color: CHART.ink, fontSize: 12 }}
                  labelFormatter={v => `${v}s field best`}
                />
                <Bar dataKey="count" fill={seriesColor(9)} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {data && !loading && (
        <div className="text-sm text-muted mb-3">
          {data.length} driver{data.length === 1 ? '' : 's'} at {trackName}
          {vardefFlagged.length > 0 && (
            <span className="ml-3 text-alarm">
              {vardefFlagged.length} driver{vardefFlagged.length === 1 ? '' : 's'} with a statistically significant variance deficit
            </span>
          )}
        </div>
      )}

      {loading && <div className="text-ink py-4">Loading fairness data — this can take a few seconds for large tracks…</div>}
      {error && <div className="text-alarm py-4">{error}</div>}

      {data && !loading && <VarianceDeficitPanel drivers={data} router={router} />}

      {data && !loading && scatterData.length > 0 && (
        <div className="bg-canvas p-3 mb-4">
          <div className="text-xs text-ink mb-2">
            <b>Consistency of relative pace</b> — each dot is a driver. X = σ of their session-best ÷ field median
            (low = tight), Y = mean of that ratio (&lt; 1 = faster than field). Descriptive only: low-σ / fast drivers
            mix skill and kart-luck. Red dots are the drivers formally flagged by the variance-deficit test above —
            those are the kart-favoritism candidates, not position on this scatter.
          </div>
          <div style={{ height: 360 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 10, right: 20, bottom: 40, left: 50 }}>
                <CartesianGrid stroke={CHART.grid} />
                <XAxis
                  type="number"
                  dataKey="x"
                  stroke={CHART.axis}
                  tick={{ fill: CHART.axis, fontSize: 10 }}
                  tickFormatter={v => v.toFixed(3)}
                  label={{
                    value: 'σRel (relative-pace variance, lower = tighter)',
                    position: 'bottom',
                    fill: CHART.axis,
                    offset: 15,
                    fontSize: 11,
                  }}
                  domain={[0, 'auto']}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  stroke={CHART.axis}
                  tick={{ fill: CHART.axis, fontSize: 10 }}
                  tickFormatter={v => v.toFixed(3)}
                  label={{
                    value: 'MeanRel (pace vs field median, < 1 = faster)',
                    angle: -90,
                    position: 'insideLeft',
                    fill: CHART.axis,
                    offset: -5,
                    fontSize: 11,
                  }}
                  domain={['auto', 'auto']}
                />
                <ZAxis type="number" dataKey="sessions" range={[40, 320]} />
                <Tooltip
                  contentStyle={{ background: CHART.tooltipBg, border: `1px solid ${CHART.grid}`, color: CHART.ink, fontSize: 12 }}
                  formatter={(value: number | string, name: string) => {
                    if (name === 'x' || name === 'σRel') return [Number(value).toFixed(4), 'σRel'];
                    if (name === 'y' || name === 'MeanRel') return [Number(value).toFixed(4), 'MeanRel'];
                    return [value, name];
                  }}
                  labelFormatter={() => ''}
                  content={({ active, payload }) => {
                    if (!active || !payload || payload.length === 0) return null;
                    const p = payload[0].payload as typeof scatterData[0];
                    return (
                      <div className="bg-surface border border-line px-3 py-2 text-xs">
                        <div className="text-ink font-semibold">{p.name}</div>
                        <div className="text-ink">Sessions: {p.sessions} · PB: {p.pb}</div>
                        <div className="text-ink">σRel: {fmtRel(p.x)}</div>
                        <div className="text-ink">MeanRel: {fmtRel(p.y)}</div>
                        <div className="text-muted">Worst rel: {p.worst ? fmtRel(p.worst) : '—'}</div>
                      </div>
                    );
                  }}
                />
                {/* Prominent baseline at the field median. Above the line =
                    slower than median, below = faster. */}
                <ReferenceLine
                  y={1.0}
                  stroke={CHART.ink}
                  strokeWidth={2}
                  strokeDasharray="6 3"
                  label={{ value: 'field median (y = 1.000)', position: 'insideTopRight', fill: CHART.ink, fontSize: 11 }}
                />
                <Scatter data={scatterData} onClick={(p: { name?: string }) => { if (p?.name) router.push(`/team/${encodeURIComponent(p.name)}`); }} cursor="pointer">
                  {scatterData.map((p, i) => {
                    const isFlagged = p.vardefVerdict === 'deficit_flagged';
                    return (
                      <Cell
                        key={i}
                        fill={isFlagged ? CHART.alarm : seriesColor(2)}
                        stroke={isFlagged ? CHART.alarm : CHART.surface}
                      />
                    );
                  })}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="text-xs text-muted mt-2">
            Dot size scales with session count (bigger = more data = more reliable). Click a dot to open that driver&apos;s profile.
          </div>
        </div>
      )}

      {data && !loading && (
        data.length === 0 ? (
          <div className="text-muted">No drivers reached the minimum sample threshold for this track.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="tabular w-full text-sm">
              <thead className="bg-surface-2">
                <tr className="text-left">
                  <th className="px-3 py-2 text-ink">#</th>
                  <th className="px-3 py-2 text-ink">Driver</th>
                  {headerCell('sessions', 'Sess')}
                  {headerCell('pb_seconds', 'PB')}
                  {headerCell('stddev_relative_pace', 'σRel')}
                  {headerCell('mean_relative_pace', 'MeanRel')}
                  {headerCell('vardef_ratio', 'VarDef σ/σ*')}
                  {headerCell('vardef_p_value', 'p')}
                  <th className="px-3 py-2 text-ink">Verdict</th>
                  {headerCell('mean_gap_to_pb_pct', 'PB gap')}
                  {headerCell('pct_within_1pct_pb', '<1% PB')}
                </tr>
              </thead>
              <tbody>
                {sortedDrivers.map((dr, i) => {
                  // σRel thresholds: < 0.002 = extreme, < 0.003 = flag, < 0.005
                  // = tight, > 0.010 = wide/normal-ish. MeanRel: < 1.00 means
                  // consistently faster than field median. Combined lucky = both.
                  const sig = dr.stddev_relative_pace;
                  const mean = dr.mean_relative_pace;
                  const sigClass =
                    sig === null ? 'text-muted' :
                    sig < 0.002 ? 'text-alarm font-semibold' :
                    sig < 0.003 ? 'text-accent' :
                    sig > 0.010 ? 'text-info' : 'text-ink';
                  const meanClass =
                    mean === null ? 'text-muted' :
                    mean < 0.99 ? 'text-live font-semibold' :
                    mean < 1.00 ? 'text-live' :
                    mean > 1.02 ? 'text-info' : 'text-ink';
                  const pbgapClass =
                    dr.mean_gap_to_pb_pct < 0.5 ? 'text-alarm' :
                    dr.mean_gap_to_pb_pct > 2.0 ? 'text-info' : 'text-ink';
                  // Variance-deficit formatting
                  const v = dr.vardef_verdict;
                  const ratio = dr.vardef_ratio;
                  const vp = dr.vardef_p_value;
                  const obsSd = dr.vardef_observed_sd_seconds;
                  const expSd = dr.vardef_expected_sd_seconds;
                  const verdictLabel =
                    v === 'deficit_flagged' ? 'variance deficit'
                    : v === 'consistent' ? 'consistent'
                    : `(n=${dr.vardef_n_sessions}/15)`;
                  const verdictClass =
                    v === 'deficit_flagged' ? 'text-alarm font-semibold'
                    : v === 'consistent' ? 'text-live'
                    : 'text-muted';
                  const ratioClass =
                    ratio === null ? 'text-muted'
                    : ratio < 0.5 ? 'text-alarm font-semibold'
                    : ratio < 0.8 ? 'text-accent'
                    : ratio < 1.2 ? 'text-ink'
                    : 'text-info';
                  const pClass =
                    vp === null ? 'text-muted'
                    : vp < 0.01 ? 'text-alarm font-semibold'
                    : vp < 0.05 ? 'text-accent'
                    : 'text-ink';
                  const rowHighlight =
                    v === 'deficit_flagged' ? 'bg-alarm/15 bg-opacity-25 hover:bg-opacity-40'
                    : 'hover:bg-surface-2';

                  return (
                    <tr
                      key={`${dr.name}-${i}`}
                      className={`border-b border-line cursor-pointer ${rowHighlight}`}
                      onClick={() => router.push(`/team/${encodeURIComponent(dr.name)}`)}
                    >
                      <td className="px-3 py-2 text-muted">{i + 1}</td>
                      <td className="px-3 py-2 text-ink">{dr.name}</td>
                      <td className="px-3 py-2 text-ink">{dr.sessions}</td>
                      <td className="px-3 py-2 text-live">{dr.pb}</td>
                      <td className={`px-3 py-2 font-mono ${sigClass}`}>
                        {sig !== null ? sig.toFixed(4) : '—'}
                      </td>
                      <td className={`px-3 py-2 font-mono ${meanClass}`}>
                        {mean !== null ? mean.toFixed(4) : '—'}
                      </td>
                      <td
                        className={`px-3 py-2 font-mono ${ratioClass}`}
                        title={
                          obsSd !== null && expSd !== null
                            ? `Observed σ=${obsSd.toFixed(2)}s · fleet-typical σ=${expSd.toFixed(2)}s`
                            : ''
                        }
                      >
                        {ratio !== null ? ratio.toFixed(2) : '—'}
                      </td>
                      <td className={`px-3 py-2 font-mono ${pClass}`}>
                        {vp !== null ? (vp < 0.0001 ? '<0.0001' : vp.toFixed(4)) : '—'}
                      </td>
                      <td className={`px-3 py-2 text-xs ${verdictClass}`}>
                        {verdictLabel}
                      </td>
                      <td className={`px-3 py-2 ${pbgapClass}`}>{dr.mean_gap_to_pb_pct.toFixed(2)}%</td>
                      <td className="px-3 py-2 text-ink">{(dr.pct_within_1pct_pb * 100).toFixed(0)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="text-xs text-muted mt-3">
              <b>σRel</b> / <b>MeanRel</b> describe <i>outcome</i> consistency (session-best ÷ field median) — a
              mix of skill and kart-luck that is <u>not</u> by itself evidence of favouritism. The direct test is{' '}
              <b>VarDef σ/σ*</b> — the ratio of the driver&apos;s own σ of (session-best − session-median) vs. the
              fleet-typical σ. The subtraction cancels track conditions (grip, weather, wear) that move the whole
              field together, so what&apos;s left is each driver&apos;s own kart-effect + execution-noise spread.
              Under random kart draws the ratio should be ≈ 1. A ratio well below 1, with a significant <b>p</b>,
              means the fleet&apos;s kart-to-kart variation isn&apos;t showing up in this driver&apos;s results —
              the telltale of systematically favourable draws.{' '}
              <b>Verdict</b> fires only at n ≥ 15 sessions AND ratio &lt; 0.8 AND p &lt; 0.05; below that threshold the
              cell shows <span className="text-muted">(n/15)</span> so we don&apos;t cry wolf on small samples.
              Click any header to resort — try <b>VarDef σ/σ*</b> ascending to surface the tightest-variance drivers.
            </p>
          </div>
        )
      )}
    </div>
  );
}

// ============================================================================
// Variance-Deficit Panel — flags drivers whose session-best spread is tighter
// than the fleet's inherent kart variation should impose under random draws.
// ============================================================================

function VardefCard({
  dr,
  tone,
  router,
}: {
  dr: TrackFairnessDriver;
  tone: 'red' | 'yellow';
  router: ReturnType<typeof useRouter>;
}) {
  const obs = dr.vardef_observed_sd_seconds;
  const exp = dr.vardef_expected_sd_seconds;
  const ratio = dr.vardef_ratio;
  const p = dr.vardef_p_value;
  const fmtP = (v: number | null) => v === null ? '—' : (v < 0.0001 ? '<0.0001' : v.toFixed(4));
  const border =
    tone === 'red' ? 'border-alarm bg-alarm/15 bg-opacity-25'
    : 'border-accent bg-accent/15 bg-opacity-20';
  return (
    <div
      onClick={() => router.push(`/team/${encodeURIComponent(dr.name)}`)}
      className={`border ${border} p-3 cursor-pointer hover:brightness-110`}
    >
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-ink font-semibold">{dr.name}</span>
        <span className="text-xs text-muted">{dr.vardef_n_sessions} sessions</span>
      </div>
      <div className="text-xs text-ink font-mono">
        Observed σ: <b>{obs !== null ? `${obs.toFixed(2)}s` : '—'}</b> ·
        Fleet-typical σ: <b>{exp !== null ? `${exp.toFixed(2)}s` : '—'}</b> ·
        Ratio: <b>{ratio !== null ? ratio.toFixed(2) : '—'}</b>
      </div>
      <div className="text-xs text-muted font-mono">
        One-sided χ² p = {fmtP(p)}
      </div>
    </div>
  );
}

function VarianceDeficitPanel({
  drivers,
  router,
}: {
  drivers: TrackFairnessDriver[];
  router: ReturnType<typeof useRouter>;
}) {
  // Buckets: formally flagged (n >= 15, ratio < 0.8, p < 0.05), watch
  // (ratio < 0.8 and p < 0.05 but n < 15), and everyone else.
  const flagged: TrackFairnessDriver[] = [];
  const watch: TrackFairnessDriver[] = [];
  let eligible = 0;
  let expectedSd: number | null = null;
  for (const d of drivers) {
    if (expectedSd === null && d.vardef_expected_sd_seconds !== null) {
      expectedSd = d.vardef_expected_sd_seconds;
    }
    if (d.vardef_n_sessions >= 3) eligible += 1;
    const ratio = d.vardef_ratio;
    const p = d.vardef_p_value;
    if (ratio === null || p === null) continue;
    if (d.vardef_verdict === 'deficit_flagged') {
      flagged.push(d);
    } else if (ratio < 0.8 && p < 0.05) {
      watch.push(d);
    }
  }
  const byRatioAsc = (a: TrackFairnessDriver, b: TrackFairnessDriver) =>
    (a.vardef_ratio ?? 99) - (b.vardef_ratio ?? 99);
  flagged.sort(byRatioAsc);
  watch.sort(byRatioAsc);

  if (eligible === 0) {
    return (
      <div className="bg-canvas p-4 mb-4 text-sm text-muted border border-line">
        <b>Variance-deficit shortlist</b>: no driver has enough sessions in the current filter. Widen the window or
        loosen min-sessions.
      </div>
    );
  }

  return (
    <div className="bg-canvas p-4 mb-4 border border-line">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-ink font-semibold">Variance-deficit shortlist</h3>
        <span className="text-xs text-muted">
          Scanned {eligible} driver{eligible === 1 ? '' : 's'} · fleet-typical σ ≈ {expectedSd !== null ? `${expectedSd.toFixed(2)}s` : '—'} · {flagged.length + watch.length} candidate{flagged.length + watch.length === 1 ? '' : 's'}
        </span>
      </div>
      <p className="text-xs text-muted mb-3">
        For each driver we compute the standard deviation of (session-best − session-median) — this cancels track
        conditions so only driver-specific variation remains. Then we compare it to the median residual σ across all
        qualifying drivers (fleet-typical σ). Under random kart assignment the ratio should be ≈ 1. A ratio
        significantly below 1 means the fleet&apos;s kart-to-kart variation isn&apos;t showing up in this
        driver&apos;s results — consistent with systematically favourable draws.
        <b> Flagged</b> = formal verdict (n ≥ 15, ratio &lt; 0.8, p &lt; 0.05).
        <b> Watch list</b> = same magnitude + p-value but fewer than 15 sessions yet. Click any card for the profile.
      </p>

      {flagged.length === 0 && watch.length === 0 && (
        <div className="text-sm text-live">
          No driver&apos;s session-best spread is tighter than the fleet&apos;s inherent variation allows — consistent
          with random kart draws.
        </div>
      )}

      {flagged.length > 0 && (
        <div className="mb-3">
          <div className="text-sm text-alarm font-semibold mb-2">
            Variance deficit — formal verdict (n ≥ 15)
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {flagged.map(d => (
              <VardefCard key={d.name} dr={d} tone="red" router={router} />
            ))}
          </div>
        </div>
      )}

      {watch.length > 0 && (
        <div>
          <div className="text-sm text-accent font-semibold mb-2">
            Watch list — tight σ + p &lt; 0.05 but fewer than 15 sessions
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {watch.map(d => (
              <VardefCard key={d.name} dr={d} tone="yellow" router={router} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
