'use client';

import React, { useState } from 'react';
import { Bell, Star } from 'lucide-react';
import StatusPill, { describeStatus, toneClasses } from './StatusPill';
import { getTeamClass, displayTeamName } from './lib/teamName';

export interface RowTeam {
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

export { getTeamClass, displayTeamName };

export const ClassChip: React.FC<{ cls: string | null }> = ({ cls }) =>
  cls ? (
    <span
      className={`inline-block px-1.5 rounded text-[11px] font-semibold leading-[18px] border ${
        cls === '1' ? 'border-class1/40 text-class1' : 'border-class2/40 text-class2'
      }`}
    >
      C{cls}
    </span>
  ) : null;

export const StarButton: React.FC<{ filled: boolean; onClick?: () => void; label: string }> = ({ filled, onClick, label }) => (
  <button
    type="button"
    onClick={onClick}
    aria-pressed={filled}
    aria-label={label}
    className={`w-11 h-11 md:w-9 md:h-9 rounded-lg flex items-center justify-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 ${
      filled ? 'text-accent' : 'text-line hover:text-muted'
    }`}
  >
    <Star size={18} fill={filled ? 'currentColor' : 'none'} strokeWidth={1.8} />
  </button>
);

export const PitAlertButton: React.FC<{
  kartNum: string;
  teamName: string;
  trackId: number;
  onTriggerAlert?: (kartNum: string, teamName: string, trackId: number) => Promise<void>;
}> = ({ kartNum, teamName, trackId, onTriggerAlert }) => {
  const [isLoading, setIsLoading] = useState(false);
  const handleClick = async () => {
    setIsLoading(true);
    try {
      await onTriggerAlert?.(kartNum, teamName, trackId);
    } catch (error) {
      console.error('Failed to trigger pit alert:', error);
    } finally {
      setIsLoading(false);
    }
  };
  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isLoading}
      title="Send PIT NOW alert to the driver overlay"
      aria-label={`Send pit alert to ${teamName}`}
      className="w-11 h-11 md:w-9 md:h-9 rounded-lg flex items-center justify-center text-alarm hover:bg-alarm/10 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <Bell size={18} className={isLoading ? 'animate-live-blink' : ''} />
    </button>
  );
};

interface StandingsRowProps {
  team: RowTeam;
  isMyTeam: boolean;
  isMonitored: boolean;
  teamColor?: string;
  isUpdated: boolean;
  selectedTrackId: number;
  onToggleMonitor: (kart: string) => void;
  onTriggerAlert?: (kartNum: string, teamName: string, trackId: number) => Promise<void>;
  /** Kept for call-site compatibility; theming now comes from CSS tokens. */
  isDarkMode?: boolean;
}

/** Shared column template: phone (4 cells) and desktop (8 cells). */
export const STANDINGS_GRID =
  'grid items-center gap-2 md:gap-3 grid-cols-[32px_minmax(0,1fr)_auto_auto] md:grid-cols-[56px_minmax(0,1fr)_120px_116px_116px_104px_72px_96px]';

const StandingsRow = React.memo(function StandingsRow({
  team,
  isMyTeam,
  isMonitored,
  teamColor,
  isUpdated,
  selectedTrackId,
  onToggleMonitor,
  onTriggerAlert,
}: StandingsRowProps) {
  const cls = getTeamClass(team.Team);
  const name = displayTeamName(team.Team);
  const inPit = team.Status === 'Pit-in';
  const { tone } = describeStatus(team.Status);
  const lapped = /tour|lap/i.test(team.Gap || '');
  const canAlert = isMonitored && !['Pit-in', 'Finished', 'DNF', 'DSQ'].includes(team.Status || '');

  return (
    <div
      id={`team-${team.Kart}`}
      role="row"
      data-kart={team.Kart}
      className={`${STANDINGS_GRID} min-h-[60px] md:min-h-[52px] pl-3 pr-1 md:px-4 border-b border-line last:border-b-0 transition-colors ${
        isMyTeam ? 'bg-accent/10' : inPit ? 'bg-alarm/[.07]' : 'hover:bg-surface-2/60'
      } ${isMonitored && inPit ? 'pit-alert' : ''} ${isUpdated ? 'row-updated' : ''}`}
    >
      {/* Position */}
      <div
        className={`w-[30px] h-[30px] md:w-8 md:h-8 rounded-[7px] md:rounded-lg font-cond font-bold text-base md:text-[17px] flex items-center justify-center ${
          isMyTeam ? 'bg-accent text-accent-ink' : 'bg-surface-2 text-ink'
        }`}
      >
        {team.Position}
      </div>

      {/* Team */}
      <div className="flex flex-col gap-0.5 min-w-0 py-1.5">
        <div className="flex items-center gap-2 min-w-0">
          {isMonitored && teamColor && (
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: teamColor }} aria-hidden />
          )}
          <span className="text-sm md:text-[15px] font-semibold truncate">{name}</span>
          <span className="hidden md:inline-flex"><ClassChip cls={cls} /></span>
          {isMyTeam && <span className="text-[11px] font-bold tracking-[.06em] text-accent shrink-0">YOU</span>}
        </div>
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono tabular text-[11px] md:text-xs text-muted">#{team.Kart}</span>
          <span className="md:hidden inline-flex"><ClassChip cls={cls} /></span>
          <span className="md:hidden">
            <StatusPill status={team.Status} variant="inline" />
          </span>
        </div>
      </div>

      {/* Phone: last lap over gap */}
      <div className="md:hidden flex flex-col items-end gap-0.5 pr-1">
        <span className={`font-mono tabular text-[15px] font-medium ${inPit ? 'text-alarm' : 'text-ink'}`}>
          {team['Last Lap'] || '—'}
        </span>
        <span className={`font-mono tabular text-xs ${lapped || !team.Gap ? 'text-muted' : 'text-muted'}`}>
          {team.Gap || '—'}
        </span>
      </div>

      {/* Desktop columns */}
      <div className="hidden md:block">
        <StatusPill status={team.Status} />
      </div>
      <div className={`hidden md:block font-mono tabular text-[15px] font-medium ${inPit ? 'text-alarm' : 'text-ink'}`}>
        {team['Last Lap'] || '—'}
      </div>
      <div className="hidden md:block font-mono tabular text-[15px] text-ink">{team['Best Lap'] || '—'}</div>
      <div className={`hidden md:block font-mono tabular text-[15px] text-right ${lapped ? 'text-muted' : 'text-ink'}`}>
        {team.Gap || '—'}
      </div>
      <div className="hidden md:block font-mono tabular text-[13px] text-muted text-right">{team['Pit Stops'] || '0'}</div>

      {/* Watch */}
      <div className="flex items-center justify-end md:justify-center">
        {canAlert && (
          <span className="hidden md:inline-flex">
            <PitAlertButton kartNum={team.Kart} teamName={team.Team} trackId={selectedTrackId} onTriggerAlert={onTriggerAlert} />
          </span>
        )}
        <StarButton
          filled={isMonitored}
          onClick={() => onToggleMonitor(team.Kart)}
          label={isMonitored ? `Stop monitoring ${name}` : `Monitor ${name}`}
        />
      </div>
      <span className="sr-only">{toneClasses(tone).text}</span>
    </div>
  );
}, (prev, next) => (
  prev.team.Position === next.team.Position &&
  prev.team.Team === next.team.Team &&
  prev.team.Kart === next.team.Kart &&
  prev.team.Status === next.team.Status &&
  prev.team['Last Lap'] === next.team['Last Lap'] &&
  prev.team['Best Lap'] === next.team['Best Lap'] &&
  prev.team.Gap === next.team.Gap &&
  prev.team['Pit Stops'] === next.team['Pit Stops'] &&
  prev.isMyTeam === next.isMyTeam &&
  prev.isMonitored === next.isMonitored &&
  prev.teamColor === next.teamColor &&
  prev.isUpdated === next.isUpdated &&
  prev.selectedTrackId === next.selectedTrackId &&
  prev.onToggleMonitor === next.onToggleMonitor &&
  prev.onTriggerAlert === next.onTriggerAlert
));

export default StandingsRow;
