/**
 * Gap maths for the dashboard: head-to-head gaps to your team, the per-lap gap
 * history behind the Delta chart, and the fleet polling gate. Pure functions
 * and the types they share — no React, no I/O — so they are unit-tested
 * directly (__tests__/raceDashboard/).
 */
import { parseTimeToSeconds } from '../../../../utils/raceMath';

// Types
export interface Team {
  Kart: string;
  Team: string;
  Position: string;
  'Last Lap': string;
  'Best Lap': string;
  'Pit Stops': string;
  Gap: string;
  RunTime: string;
  Status?: string;
  lastPitCount?: number;
}

export interface SessionInfo {
  dyn1?: string;
  dyn2?: string;
  light?: string;
  title?: string;
  title1?: string;
  title2?: string;
  [key: string]: string | undefined; // Allow other string fields from backend
}

export interface Alert {
  id: number;
  message: string;
  type?: 'info' | 'warning' | 'success' | 'error';
  customContent?: React.ReactNode;
  teamKart?: string; // Add team identifier for pit alerts
  fleetKartId?: number; // fleet kart identifier for fleet pit alerts
  /** Persists until dismissed or the live condition clears; skipped by auto-dismiss. */
  persistent?: boolean;
  /** Optional inline action button (e.g. Undo). */
  action?: { label: string; onClick: () => void };
}

export interface Trend {
  value: number;
  arrow: number;
}

export interface DeltaData {
  gap: number;
  adjusted_gap?: number;
  team_name: string;
  position: number;
  last_lap: string;
  best_lap: string;
  pit_stops: string;
  remaining_stops?: number;
  trends: {
    lap_1: Trend;
    lap_5: Trend;
    lap_10: Trend;
  };
  adjusted_trends?: {
    lap_1: Trend;
    lap_5: Trend;
    lap_10: Trend;
  };
}

export interface GapHistory {
  [kart: string]: {
    gaps: number[];
    adjusted_gaps?: number[];
    last_update: string;
  };
}

// parseTimeToSeconds imported from utils/raceMath.ts (canonical implementation)

// Helper function to calculate gaps between teams
export const calculateTeamGaps = (teams: Team[], myTeamKart: string, monitoredKarts: string[], pitStopTime: number, requiredPitStops: number, isQualification: boolean = false): Record<string, DeltaData> => {
  const myTeam = teams.find(t => t.Kart === myTeamKart);
  if (!myTeam) return {};

  const myPitStops = isQualification ? 0 : parseInt(myTeam['Pit Stops'] || '0');
  const myRemainingStops = isQualification ? 0 : Math.max(0, requiredPitStops - myPitStops);
  
  // Parse my team's gap
  let myGapToLeader = 0;
  let myLapsBehind = 0;
  if (myTeam.Position !== '1') {
    const gapStr = myTeam.Gap;
    // Handle lapped teams
    if (gapStr.includes('Tour')) {
      myLapsBehind = parseInt(gapStr.split(' ')[0]);
      // Use my last lap time or default
      const avgLapTime = myTeam['Last Lap'] && myTeam['Last Lap'].includes(':') 
        ? parseTimeToSeconds(myTeam['Last Lap'])
        : 90;
      myGapToLeader = myLapsBehind * avgLapTime;
    } else {
      try {
        myGapToLeader = parseTimeToSeconds(gapStr);
      } catch {
        myGapToLeader = 0;
      }
    }
  }
  
  // Count laps difference between positions
  const countLapDifference = (myPos: number, monPos: number): number => {
    if (myPos === monPos) return 0;
    
    const startPos = Math.min(myPos, monPos);
    const endPos = Math.max(myPos, monPos);
    let lapDiff = 0;
    
    // Check all teams between the two positions
    teams.forEach(t => {
      const teamPos = parseInt(t.Position);
      if (startPos < teamPos && teamPos < endPos) {
        if (t.Gap.includes('Tour')) {
          lapDiff += parseInt(t.Gap.split(' ')[0]);
        }
      }
    });
    
    return lapDiff;
  };
  
  const myPosition = parseInt(myTeam.Position);

  const deltas: Record<string, DeltaData> = {};

  monitoredKarts.forEach(kart => {
    const monitoredTeam = teams.find(t => t.Kart === kart);
    if (!monitoredTeam) return;

    const monPitStops = isQualification ? 0 : parseInt(monitoredTeam['Pit Stops'] || '0');
    const monRemainingStops = isQualification ? 0 : Math.max(0, requiredPitStops - monPitStops);
    
    const monPosition = parseInt(monitoredTeam.Position);
    
    // Parse monitored team's gap
    let monGapToLeader = 0;
    let monLapsBehind = 0;
    if (monPosition !== 1) {
      const gapStr = monitoredTeam.Gap;
      // Handle lapped teams and special cases
      if (gapStr.includes('Tour')) {
        // Check if this is P1 showing total laps (e.g., "Tour 56")
        if (monPosition === 1) {
          // This is the winner showing total laps completed
          monGapToLeader = 0; // Leader has no gap
          monLapsBehind = 0;
        } else {
          // This is laps behind the leader (e.g., "1 Tour", "2 Tours")
          monLapsBehind = parseInt(gapStr.split(' ')[0]);
          
          // Check if there are lapped teams between us
          const lapsBetween = countLapDifference(myPosition, monPosition);
          
          // Calculate actual lap difference
          let actualLapDiff = 0;
          if (myPosition < monPosition) {
            // Monitored team is behind us
            actualLapDiff = monLapsBehind - myLapsBehind - lapsBetween;
          } else {
            // Monitored team is ahead of us
            actualLapDiff = monLapsBehind - myLapsBehind + lapsBetween;
          }
          
          // If actual lap diff is 0, we're on the same lap
          if (actualLapDiff === 0) {
            // We're on the same lap, calculate based on position
            // This will be handled by the normal gap calculation below
            monGapToLeader = myGapToLeader; // Start with same base
          } else {
            // Different laps, calculate based on lap difference using best lap time
            const bestLapTime = monitoredTeam['Best Lap'] && monitoredTeam['Best Lap'].includes(':') 
              ? parseTimeToSeconds(monitoredTeam['Best Lap'])
              : 90;
            monGapToLeader = myGapToLeader + (actualLapDiff * bestLapTime);
          }
        }
      } else {
        // Gap is in seconds (time format)
        try {
          monGapToLeader = parseTimeToSeconds(gapStr);
          
          // Check if there are lapped teams between us
          const lapsBetween = countLapDifference(myPosition, monPosition);
          
          // If there are lapped teams between us, we need to account for the lap difference
          if (lapsBetween > 0) {
            const bestLapTime = monitoredTeam['Best Lap'] && monitoredTeam['Best Lap'].includes(':') 
              ? parseTimeToSeconds(monitoredTeam['Best Lap'])
              : 90;
            
            if (myPosition < monPosition) {
              // Monitored team is behind us but with lapped teams in between
              monGapToLeader += lapsBetween * bestLapTime;
            } else {
              // Monitored team is ahead of us but with lapped teams in between
              monGapToLeader -= lapsBetween * bestLapTime;
            }
          }
          // If no lapped teams between us, we're on the same lap and can use the gap as is
        } catch {
          monGapToLeader = 0;
        }
      }
    }

    // Calculate gap based on session type
    let realGap: number;
    let adjustedGap: number;
    
    if (isQualification) {
      // In qualification mode, use best lap times for gap calculation
      const myBestLap = myTeam['Best Lap'] && myTeam['Best Lap'].includes(':') 
        ? parseTimeToSeconds(myTeam['Best Lap'])
        : Infinity;
      const monBestLap = monitoredTeam['Best Lap'] && monitoredTeam['Best Lap'].includes(':')
        ? parseTimeToSeconds(monitoredTeam['Best Lap'])
        : Infinity;
      
      // Gap is the difference in best lap times
      realGap = monBestLap - myBestLap;
      adjustedGap = realGap; // No pit stop adjustments in qualification
    } else {
      // Normal race mode - calculate with pit stops
      // Calculate real gap including pit stop compensation for completed stops
      // Using 150 second compensation as base (standard Apex Timing value)
      realGap = (monGapToLeader - myGapToLeader) + ((monPitStops - myPitStops) * 150);
      
      // Calculate adjusted gap accounting for remaining required pit stops
      adjustedGap = realGap + ((monRemainingStops - myRemainingStops) * pitStopTime);
    }

    deltas[kart] = {
      gap: Math.round(realGap * 1000) / 1000, // Round to 3 decimals
      adjusted_gap: Math.round(adjustedGap * 1000) / 1000,
      team_name: monitoredTeam.Team,
      position: parseInt(monitoredTeam.Position),
      last_lap: monitoredTeam['Last Lap'],
      best_lap: monitoredTeam['Best Lap'],
      pit_stops: monitoredTeam['Pit Stops'],
      remaining_stops: isQualification ? 0 : monRemainingStops,
      trends: {
        lap_1: { value: 0, arrow: 0 },
        lap_5: { value: 0, arrow: 0 },
        lap_10: { value: 0, arrow: 0 }
      },
      adjusted_trends: {
        lap_1: { value: 0, arrow: 0 },
        lap_5: { value: 0, arrow: 0 },
        lap_10: { value: 0, arrow: 0 }
      }
    };
  });

  return deltas;
};

// Gate for live /fleet/state polling. Exported for unit tests.
// Hidden browser tabs never poll; users without a fleet only poll while the
// Fleet tab is open; users WITH a fleet poll in the background so the
// "fast kart in the pits" alerts still fire from other tabs.
export const shouldPollFleet = (
  visibilityState: DocumentVisibilityState | undefined,
  activeTab: string,
  registrySize: number,
): boolean => {
  if (visibilityState === 'hidden') return false;
  return activeTab === 'fleet' || registrySize > 0;
};

// Phase 2 dropped the backend's `gap_history`, which left the Delta chart with
// no data source (it always rendered "No data available"). Rebuild the series
// client-side from the deltas we already compute: one point per completed lap,
// appended when a monitored kart's `Last Lap` changes — the same trigger the
// old backend used. The first sample is seeded immediately so the chart draws
// at once, and the arrays are capped to bound memory. Exported for unit tests.
export const MAX_GAP_HISTORY = 60;
export const appendLapGapHistory = (
  prev: GapHistory,
  monitoredTeams: string[],
  deltas: Record<string, { gap: number; adjusted_gap?: number }>,
  teams: Array<{ Kart: string; 'Last Lap'?: string }>,
  maxEntries: number = MAX_GAP_HISTORY,
): GapHistory => {
  const next: GapHistory = { ...prev };
  let changed = false;

  monitoredTeams.forEach(kart => {
    const data = deltas[kart];
    const team = teams.find(t => t.Kart === kart);
    const lastLap = team?.['Last Lap'] || '';
    if (!data || !lastLap) return;

    const adjusted = data.adjusted_gap ?? data.gap;
    const existing = next[kart];
    if (!existing) {
      next[kart] = { gaps: [data.gap], adjusted_gaps: [adjusted], last_update: lastLap };
      changed = true;
    } else if (existing.last_update !== lastLap) {
      next[kart] = {
        gaps: [...existing.gaps, data.gap].slice(-maxEntries),
        adjusted_gaps: [...(existing.adjusted_gaps || []), adjusted].slice(-maxEntries),
        last_update: lastLap,
      };
      changed = true;
    }
  });

  // Forget karts the user stopped monitoring.
  const monitored = new Set(monitoredTeams);
  Object.keys(next).forEach(kart => {
    if (!monitored.has(kart)) {
      delete next[kart];
      changed = true;
    }
  });

  return changed ? next : prev;
};

// A completed pit stop is treated (by the live path) as costing this many
// seconds of track position; the historical seed applies the same constant so
// the two series join up.
export const PIT_STOP_COMPENSATION_SECONDS = 150;

export interface SessionGapLap {
  lap: number;
  gap: string;
  gap_seconds: number | null;
  lap_time: string;
  pit_stops: number;
}
export type SessionGapSeries = Record<
  string,
  { kart: string; team: string; laps: SessionGapLap[] }
>;

/**
 * Seed the Delta chart from persisted per-lap gaps (endpoint
 * /api/team-data/session-gaps). The DB stores each team's gap-to-leader per
 * lap — user-independent timing data — and here we turn that into the
 * head-to-head series against `myTeam`, applying the same pit-stop
 * compensation as the live path so the two join seamlessly. Lapped laps
 * (`gap_seconds === null`) are skipped. Exported for unit tests.
 */
export const buildGapHistoryFromSeries = (
  series: SessionGapSeries,
  myTeam: string,
  monitoredTeams: string[],
  pitStopTime: number,
  requiredPitStops: number,
  maxEntries: number = MAX_GAP_HISTORY,
): GapHistory => {
  const myLaps = series[myTeam]?.laps || [];
  if (myLaps.length === 0) return {};

  const out: GapHistory = {};
  monitoredTeams.forEach(kart => {
    const laps = series[kart]?.laps || [];
    if (laps.length === 0) return;

    const gaps: number[] = [];
    const adjusted: number[] = [];
    let myGap = 0;
    for (let i = 0; i < laps.length; i++) {
      const myLap = myLaps[i];
      if (myLap && myLap.gap_seconds != null) myGap = myLap.gap_seconds;
      const xGap = laps[i].gap_seconds;
      if (xGap == null) continue; // lapped / unknown at this lap
      const xPit = laps[i].pit_stops || 0;
      const mPit = myLap?.pit_stops || 0;
      const real = (xGap - myGap) + (xPit - mPit) * PIT_STOP_COMPENSATION_SECONDS;
      const remainingComp =
        (Math.max(0, requiredPitStops - xPit) - Math.max(0, requiredPitStops - mPit)) * pitStopTime;
      gaps.push(Math.round(real * 1000) / 1000);
      adjusted.push(Math.round((real + remainingComp) * 1000) / 1000);
    }
    if (gaps.length === 0) return;

    out[kart] = {
      gaps: gaps.slice(-maxEntries),
      adjusted_gaps: adjusted.slice(-maxEntries),
      // The latest completed lap, even if its point was skipped, so the live
      // append effect doesn't re-add it.
      last_update: laps[laps.length - 1].lap_time || '',
    };
  });

  return out;
};
