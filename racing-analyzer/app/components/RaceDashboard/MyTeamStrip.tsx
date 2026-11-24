'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Bell, ChevronDown, X } from 'lucide-react';
import StatusPill from '../../ui/StatusPill';
import Stat from '../../ui/Stat';
import Button from '../../ui/Button';
import IconButton from '../../ui/IconButton';
import { Select } from '../../ui/Field';
import { displayTeamName } from './lib/teamName';
import { calculateTrend, headToHeadGap, parseTimeToSeconds } from '../../../utils/raceMath';

export interface StripTeam {
  Kart: string;
  Team: string;
  Position: string;
  'Last Lap': string;
  'Best Lap': string;
  'Pit Stops': string;
  Gap: string;
  RunTime?: string;
  Status?: string;
}

export interface Neighbour {
  team: StripTeam;
  /** Seconds. Negative = they are ahead of me. null when a lap boundary makes it undefined. */
  gap: number | null;
}

export interface MyTeamContext {
  me: StripTeam;
  position: number;
  ahead: Neighbour | null;
  behind: Neighbour | null;
  isPersonalBest: boolean;
}

/** Pure: find my row and the cars either side, with head-to-head gaps. */
export function computeMyTeamContext(teams: StripTeam[], myKart: string): MyTeamContext | null {
  const me = teams.find((t) => t.Kart === myKart);
  if (!me) return null;
  const sorted = [...teams].sort((a, b) => parseInt(a.Position) - parseInt(b.Position));
  const idx = sorted.findIndex((t) => t.Kart === myKart);
  const toNeighbour = (t: StripTeam | undefined): Neighbour | null => {
    if (!t) return null;
    const g = headToHeadGap(me, t);
    return { team: t, gap: Number.isFinite(g) ? g : null };
  };
  const last = parseTimeToSeconds(me['Last Lap']);
  const best = parseTimeToSeconds(me['Best Lap']);
  return {
    me,
    position: parseInt(me.Position) || idx + 1,
    ahead: toNeighbour(idx > 0 ? sorted[idx - 1] : undefined),
    behind: toNeighbour(idx >= 0 ? sorted[idx + 1] : undefined),
    isPersonalBest: last > 0 && best > 0 && Math.abs(last - best) < 0.0005,
  };
}

export const formatGap = (gap: number | null): string => {
  if (gap === null) return '—';
  const sign = gap < 0 ? '−' : '+';
  return `${sign}${Math.abs(gap).toFixed(3)}`;
};

interface MyTeamStripProps {
  teams: StripTeam[];
  myTeam: string;
  onSelectMyTeam: (kart: string) => void;
  isQualificationMode: boolean;
  requiredPitStops: number;
  onPitAlert?: (kart: string, teamName: string) => Promise<void> | void;
  /** Optional control rendered beside the pit-alert button (board picker). */
  pitAlertTargetSlot?: React.ReactNode;
}

/**
 * The pinned "my team" card: position, last/best lap, gap to the cars ahead
 * and behind with a closing/opening trend, stops, and the pit-alert trigger.
 */
const MyTeamStrip: React.FC<MyTeamStripProps> = ({
  teams,
  myTeam,
  onSelectMyTeam,
  isQualificationMode,
  requiredPitStops,
  onPitAlert,
  pitAlertTargetSlot,
}) => {
  const [picking, setPicking] = useState(false);
  const [sending, setSending] = useState(false);
  const ctx = useMemo(() => computeMyTeamContext(teams, myTeam), [teams, myTeam]);

  // Rolling history of the gap ahead/behind, sampled when my last lap
  // changes, so the trend reads per lap rather than per feed tick.
  const histRef = useRef<{ kart: string; lastLap: string; ahead: number[]; behind: number[] }>({
    kart: '',
    lastLap: '',
    ahead: [],
    behind: [],
  });
  const [trend, setTrend] = useState<{ ahead: number; behind: number }>({ ahead: 0, behind: 0 });
  useEffect(() => {
    if (!ctx) return;
    const h = histRef.current;
    if (h.kart !== ctx.me.Kart) {
      histRef.current = { kart: ctx.me.Kart, lastLap: '', ahead: [], behind: [] };
    }
    const cur = histRef.current;
    if (cur.lastLap === ctx.me['Last Lap']) return;
    cur.lastLap = ctx.me['Last Lap'];
    const push = (arr: number[], v: number | null | undefined) => {
      if (v === null || v === undefined) return arr;
      const next = [...arr, v];
      return next.slice(-6);
    };
    cur.ahead = push(cur.ahead, ctx.ahead?.gap);
    cur.behind = push(cur.behind, ctx.behind?.gap);
    const a = ctx.ahead?.gap ?? Number.NaN;
    const b = ctx.behind?.gap ?? Number.NaN;
    setTrend({
      ahead: calculateTrend(a, cur.ahead.slice(0, -1)).arrow,
      behind: calculateTrend(b, cur.behind.slice(0, -1)).arrow,
    });
  }, [ctx]);

  const sortedTeams = useMemo(
    () => [...teams].sort((a, b) => parseInt(a.Position) - parseInt(b.Position)),
    [teams],
  );

  const picker = (
    <Select
      aria-label="Choose your team"
      value={myTeam}
      onChange={(e) => {
        onSelectMyTeam(e.target.value);
        setPicking(false);
      }}
      className="md:w-auto md:min-w-[280px]"
    >
      <option value="">Choose your team…</option>
      {sortedTeams.map((t) => (
        <option key={t.Kart} value={t.Kart}>
          P{t.Position} · {displayTeamName(t.Team)} (#{t.Kart})
        </option>
      ))}
    </Select>
  );

  if (!ctx) {
    return (
      <section className="border border-line bg-surface p-4 flex flex-col md:flex-row md:items-center gap-3" aria-label="My team" data-tour="my-team">
        <div className="flex flex-col gap-0.5 flex-1 min-w-0">
          <span className="eyebrow text-muted">My team</span>
          <span className="text-sm text-muted">
            {teams.length === 0 ? 'Waiting for live data to list the field.' : 'Pick your team to pin its gaps here.'}
          </span>
        </div>
        {teams.length > 0 && picker}
      </section>
    );
  }

  const { me, ahead, behind, position } = ctx;
  const inPit = me.Status === 'Pit-in';
  const lastTone = inPit ? 'text-alarm' : ctx.isPersonalBest ? 'text-live' : 'text-ink';
  const aheadTone = ahead?.gap === null ? 'text-muted' : trend.ahead < 0 ? 'text-live' : trend.ahead > 0 ? 'text-alarm' : 'text-ink';
  const behindTone = behind?.gap === null ? 'text-muted' : trend.behind > 0 ? 'text-live' : trend.behind < 0 ? 'text-alarm' : 'text-ink';
  const trendWord = (arrow: number, closingWhenNegative: boolean) => {
    if (arrow === 0) return 'stable';
    const closing = closingWhenNegative ? arrow < 0 : arrow > 0;
    return closing ? 'closing' : 'opening';
  };
  const stops = parseInt(me['Pit Stops'] || '0') || 0;
  const canAlert = !!onPitAlert && !inPit && !['Finished', 'DNF', 'DSQ'].includes(me.Status || '');

  return (
    <section
      className={`border bg-surface p-3.5 md:p-4 flex flex-col gap-3 ${inPit ? 'border-alarm/60 pit-alert' : 'border-line'}`}
      aria-label="My team"
      data-tour="my-team"
    >
      {/* Identity + actions. The row wraps: the identity column keeps a 10rem
          floor, so when the actions don't fit beside it they drop to their own
          line instead of squeezing the team name to nothing. */}
      <div className="flex flex-wrap items-center gap-3 md:gap-5">
        <div className="w-10 h-10 md:w-[52px] md:h-[52px] accent-block text-accent-ink font-cond font-bold text-2xl md:text-3xl flex items-center justify-center shrink-0">
          {position}
        </div>
        <div className="flex flex-col gap-1 min-w-0 flex-1 basis-40">
          {picking ? (
            <div className="flex items-center gap-2 min-w-0">
              {picker}
              <IconButton label="Cancel team change" onClick={() => setPicking(false)}>
                <X size={16} />
              </IconButton>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setPicking(true)}
              aria-label="Change my team"
              title="Change my team"
              className="group flex items-center gap-1.5 min-w-0 max-w-full -ml-1 pl-1 pr-2 h-8 text-left hover:bg-surface-2"
            >
              <span className="text-base font-bold truncate">{displayTeamName(me.Team)}</span>
              <ChevronDown size={16} className="shrink-0 text-muted group-hover:text-ink" />
              <span className="hidden md:inline shrink-0 text-xs font-semibold text-muted group-hover:text-ink">Change</span>
            </button>
          )}
          <div className="flex items-center gap-2.5 flex-wrap">
            <span className="font-mono tabular text-xs text-muted">#{me.Kart}</span>
            <StatusPill status={me.Status} />
            {me.RunTime && <span className="text-xs text-muted">run <span className="tabular">{me.RunTime}</span></span>}
          </div>
        </div>

        {canAlert && (
          <div className="ml-auto shrink-0 flex items-center gap-2 md:gap-3">
            {pitAlertTargetSlot}
            <Button
              variant="danger"
              size="lg"
              disabled={sending}
              onClick={async () => {
                setSending(true);
                try {
                  await onPitAlert?.(me.Kart, me.Team);
                } finally {
                  setSending(false);
                }
              }}
              title="Send PIT NOW alert to the driver overlay"
              // Icon-only on phones, labelled from md up.
              className="w-11 px-0 md:w-auto md:px-4 font-bold"
            >
              <Bell size={18} />
              <span className="hidden md:inline">{sending ? 'Sending…' : 'Pit alert'}</span>
            </Button>
          </div>
        )}
      </div>

      {/* Desktop stats: their own row. An auto-fit grid, so five figures sit on
          one line when the workbench is wide and wrap when it is not — they
          are never clipped and never push the pit-alert button off the card. */}
      <div
        className="hidden md:grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-x-6 gap-y-3 pt-3 border-t border-line"
        data-testid="my-team-stats"
      >
        <Stat label="Last lap" value={me['Last Lap'] || '—'} tone={lastTone} sub={ctx.isPersonalBest ? 'personal best' : undefined} />
        <Stat label="Best lap" value={me['Best Lap'] || '—'} />
        <Stat
          label={ahead ? `Ahead · P${ahead.team.Position}` : 'Ahead'}
          value={
            ahead ? (
              <span className="inline-flex items-center gap-1.5">
                {formatGap(ahead.gap)}
                {trend.ahead < 0 ? <ArrowDown size={16} /> : trend.ahead > 0 ? <ArrowUp size={16} /> : null}
              </span>
            ) : (
              'Leader'
            )
          }
          tone={ahead ? aheadTone : 'text-accent'}
          sub={ahead ? (ahead.gap === null ? 'lapped' : trendWord(trend.ahead, true)) : undefined}
        />
        <Stat
          label={behind ? `Behind · P${behind.team.Position}` : 'Behind'}
          value={
            behind ? (
              <span className="inline-flex items-center gap-1.5">
                {formatGap(behind.gap)}
                {trend.behind > 0 ? <ArrowUp size={16} /> : trend.behind < 0 ? <ArrowDown size={16} /> : null}
              </span>
            ) : (
              'Last'
            )
          }
          tone={behind ? behindTone : 'text-muted'}
          sub={behind ? (behind.gap === null ? 'lapped' : trendWord(trend.behind, false)) : undefined}
        />
        {isQualificationMode ? (
          <Stat label="Laps" value={me['Pit Stops'] || '0'} />
        ) : (
          <Stat label="Stops" value={`${stops} / ${requiredPitStops}`} sub={`${Math.max(0, requiredPitStops - stops)} to go`} />
        )}
      </div>

      {/* Phone stats grid */}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(6rem,1fr))] gap-x-2 gap-y-3 md:hidden">
        <Stat label="Last" value={me['Last Lap'] || '—'} tone={lastTone} />
        <Stat
          label={ahead ? `Ahead P${ahead.team.Position}` : 'Ahead'}
          value={
            ahead ? (
              <span className="inline-flex items-center gap-1">
                {formatGap(ahead.gap)}
                {trend.ahead < 0 ? <ArrowDown size={14} /> : trend.ahead > 0 ? <ArrowUp size={14} /> : null}
              </span>
            ) : (
              'Leader'
            )
          }
          tone={ahead ? aheadTone : 'text-accent'}
        />
        <Stat
          label={behind ? `Behind P${behind.team.Position}` : 'Behind'}
          value={
            behind ? (
              <span className="inline-flex items-center gap-1">
                {formatGap(behind.gap)}
                {trend.behind > 0 ? <ArrowUp size={14} /> : trend.behind < 0 ? <ArrowDown size={14} /> : null}
              </span>
            ) : (
              'Last'
            )
          }
          tone={behind ? behindTone : 'text-muted'}
        />
      </div>

    </section>
  );
};

export default MyTeamStrip;
