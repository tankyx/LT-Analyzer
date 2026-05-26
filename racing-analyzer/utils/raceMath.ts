/**
 * Phase 2: delta math that used to live on the backend now runs client-side.
 *
 * The dashboard receives a `teams` snapshot from the backend (one row per
 * kart with Gap, Position, Pit Stops, etc.). These helpers turn that snapshot
 * into the head-to-head deltas the user actually wants to see.
 *
 * Kept intentionally simple — the previous backend implementation had complex
 * lapped-team adjustment using running averages of lap times. That math is
 * being deferred until we see a real session where the simple version is
 * misleading; for everyday racing the gap-field on each team is already in
 * seconds and the simple subtraction works.
 */

export interface TeamRow {
  Kart?: string;
  Team?: string;
  Position?: string;
  Gap?: string;
  'Last Lap'?: string;
  'Best Lap'?: string;
  'Pit Stops'?: string;
}

export interface UserPitConfig {
  pit_stop_time: number;
  required_pit_stops: number;
}

/** Parse Apex Timing time strings to seconds. Supports "MM:SS.mmm" and "SS.mmm". */
export function parseTimeToSeconds(s: string | undefined | null): number {
  if (!s) return 0;
  const trimmed = s.trim();
  if (!trimmed) return 0;
  if (trimmed.includes(':')) {
    const [m, rest] = trimmed.split(':');
    return (parseInt(m, 10) || 0) * 60 + (parseFloat(rest) || 0);
  }
  const n = parseFloat(trimmed);
  return Number.isFinite(n) ? n : 0;
}

/** Gap-to-leader in seconds for a single team. Lapped rows ("1 Tour") return Infinity. */
export function gapToLeaderSeconds(team: TeamRow): number {
  const g = (team.Gap || '').trim();
  if (!g) return 0;
  if (g.toLowerCase().includes('tour')) return Number.POSITIVE_INFINITY;
  return parseTimeToSeconds(g);
}

/** Pit stops a team has completed (parsed defensively). */
export function pitStopsCount(team: TeamRow): number {
  const raw = (team['Pit Stops'] || '').trim();
  if (!raw) return 0;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : 0;
}

/** Position as an integer (1 = leader). 0 for unparseable. */
export function position(team: TeamRow): number {
  const raw = (team.Position || '').trim();
  if (!raw) return 0;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Head-to-head raw gap between two teams (positive = `other` is BEHIND `me`).
 * Both teams' Gap fields are gap-to-leader, so we subtract. If either team
 * is lapped (Infinity), we return NaN so callers can fall back to "—".
 */
export function headToHeadGap(me: TeamRow, other: TeamRow): number {
  const a = gapToLeaderSeconds(me);
  const b = gapToLeaderSeconds(other);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return Number.NaN;
  // Same sign convention as the previous backend: positive means `other` is
  // further from the leader (so behind `me`).
  return +(b - a).toFixed(3);
}

/**
 * Adjusted gap = raw gap + the time disadvantage from any remaining required
 * pit stops. If `me` still owes more stops than `other`, the adjusted gap to
 * `other` shrinks (we'll lose time relative to them on the next stop).
 */
export function adjustedGap(rawGap: number, me: TeamRow, other: TeamRow, cfg: UserPitConfig): number {
  if (!Number.isFinite(rawGap)) return Number.NaN;
  const myRemaining = Math.max(0, cfg.required_pit_stops - pitStopsCount(me));
  const otherRemaining = Math.max(0, cfg.required_pit_stops - pitStopsCount(other));
  return +(rawGap + (otherRemaining - myRemaining) * cfg.pit_stop_time).toFixed(3);
}

/**
 * Simple trend: takes a current value and a recent history (oldest → newest)
 * and returns delta-per-step plus an arrow direction (-1/0/1).
 */
export function calculateTrend(current: number, history: number[]): { value: number; arrow: -1 | 0 | 1 } {
  if (!Number.isFinite(current) || history.length === 0) {
    return { value: 0, arrow: 0 };
  }
  const oldest = history[0];
  if (!Number.isFinite(oldest)) return { value: 0, arrow: 0 };
  const delta = +(current - oldest).toFixed(3);
  if (Math.abs(delta) < 0.05) return { value: delta, arrow: 0 };
  return { value: delta, arrow: delta > 0 ? 1 : -1 };
}

export interface DeltaSummary {
  kart: string;
  team_name: string;
  position: number;
  last_lap: string;
  best_lap: string;
  pit_stops: number;
  gap: number;           // raw head-to-head
  adjusted_gap: number;  // with pit-config adjustment
  // Trend arrays are owned by the React component; this struct is one snapshot.
}

/**
 * Convenience builder: produce a summary for one monitored team relative to "me".
 */
export function buildDelta(me: TeamRow, other: TeamRow, cfg: UserPitConfig): DeltaSummary {
  const raw = headToHeadGap(me, other);
  return {
    kart: other.Kart || '',
    team_name: other.Team || '',
    position: position(other),
    last_lap: other['Last Lap'] || '',
    best_lap: other['Best Lap'] || '',
    pit_stops: pitStopsCount(other),
    gap: raw,
    adjusted_gap: adjustedGap(raw, me, other, cfg),
  };
}
