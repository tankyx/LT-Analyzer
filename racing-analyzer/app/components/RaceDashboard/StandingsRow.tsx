'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Bell, Star } from 'lucide-react';
import StatusPill, { ClassChip } from '../../ui/StatusPill';
import IconButton from '../../ui/IconButton';
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

export { getTeamClass, displayTeamName, ClassChip };

export const StarButton: React.FC<{ filled: boolean; onClick?: () => void; label: string }> = ({ filled, onClick, label }) => (
  <IconButton
    label={label}
    onClick={onClick}
    aria-pressed={filled}
    // Rests in line-strong so twenty stars do not compete with the figures.
    className={filled ? 'text-accent hover:bg-transparent hover:text-accent' : 'text-line-strong hover:bg-transparent hover:text-muted'}
  >
    <Star size={18} fill={filled ? 'currentColor' : 'none'} strokeWidth={1.8} />
  </IconButton>
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
    <IconButton
      label={`Send pit alert to ${teamName}`}
      variant="alarm"
      onClick={handleClick}
      disabled={isLoading}
      title="Send PIT NOW alert to the driver overlay"
    >
      <Bell size={18} className={isLoading ? 'live-glow' : ''} />
    </IconButton>
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

/** Returns the value from the previous render (undefined on first). */
function usePrevious<T>(value: T): T | undefined {
  const ref = useRef<T | undefined>(undefined);
  useEffect(() => {
    ref.current = value;
  }, [value]);
  return ref.current;
}

/** A timing number that "ticks" (pops) whenever the live feed rewrites it.
 *  key={value} remounts the span so the CSS animation replays on change. */
const TickingValue: React.FC<{ value: string }> = ({ value }) => (
  <span key={value} className="value-tick">{value}</span>
);

/**
 * A compact timing-tower row: livery position block, team, and the two live
 * figures a crew actually watches — gap to leader and last lap. Shaped for a
 * narrow vertical tower, not a wide spreadsheet.
 */
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
  const lapped = /tour|lap/i.test(team.Gap || '');
  const isLeader = team.Position === '1';
  const canAlert = isMonitored && !['Pit-in', 'Finished', 'DNF', 'DSQ'].includes(team.Status || '');

  // Position-change detection for the overtake/drop flash.
  const prevPosition = usePrevious(team.Position);
  const posChanged = prevPosition !== undefined && prevPosition !== team.Position;
  const pos = parseInt(team.Position, 10);
  const prevPos = parseInt(prevPosition ?? '', 10);
  const gained = posChanged && !isNaN(pos) && !isNaN(prevPos) && pos < prevPos;
  const lost = posChanged && !isNaN(pos) && !isNaN(prevPos) && pos > prevPos;

  return (
    <div
      id={`team-${team.Kart}`}
      role="row"
      data-kart={team.Kart}
      style={teamColor ? { borderLeftColor: teamColor } : undefined}
      className={`flex items-center gap-3 px-3 py-2.5 border-l-[3px] border-l-transparent border-b border-line last:border-b-0 transition-colors min-h-[56px] ${
        isMyTeam ? 'bg-accent/15' : isLeader ? 'bg-accent/8' : inPit ? 'bg-alarm/8' : 'hover:bg-surface-2/60'
      } ${isMonitored && inPit ? 'pit-alert' : ''} ${isUpdated ? 'row-updated' : ''} ${gained ? 'row-gain' : ''} ${lost ? 'row-loss' : ''}`}
    >
      {/* Position — livery ring + number, amber block for your own team */}
      <div
        role="cell"
        style={!isMyTeam && teamColor ? { color: teamColor, boxShadow: `inset 0 0 0 2px ${teamColor}` } : undefined}
        className={`w-10 h-10 shrink-0 flex items-center justify-center font-cond font-bold text-lg ${
          isMyTeam ? 'accent-block text-accent-ink' : 'bg-surface-2 text-ink'
        }`}
      >
        <TickingValue value={team.Position} />
      </div>

      {/* Team */}
      <div role="cell" className="flex-1 min-w-0 flex flex-col justify-center">
        <div className="flex items-center gap-1.5 min-w-0">
          {isMonitored && teamColor && (
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: teamColor }} aria-hidden />
          )}
          <span className="text-sm font-semibold truncate">{name}</span>
          {isMyTeam && <span className="eyebrow text-3xs text-accent shrink-0">YOU</span>}
        </div>
        <div className="flex items-center gap-1.5 min-w-0 text-2xs text-muted">
          <span className="font-mono tabular">#{team.Kart}</span>
          <ClassChip cls={cls} />
          <StatusPill status={team.Status} variant="inline" />
        </div>
      </div>

      {/* Live figures: gap to leader + last lap */}
      <div role="cell" className="shrink-0 flex flex-col items-end justify-center">
        <span className={`font-mono tabular led text-base font-semibold leading-tight ${lapped ? 'text-alarm' : 'text-ink'}`}>
          <TickingValue value={team.Gap || '—'} />
        </span>
        <span className={`font-mono tabular text-2xs ${inPit ? 'text-alarm' : 'text-muted'}`}>
          <TickingValue value={team['Last Lap'] || '—'} />
        </span>
      </div>

      {/* Watch */}
      <div role="cell" className="shrink-0 flex items-center">
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
    </div>
  );
}, (prev, next) => (
  prev.team.Position === next.team.Position &&
  prev.team.Team === next.team.Team &&
  prev.team.Kart === next.team.Kart &&
  prev.team.Status === next.team.Status &&
  prev.team['Last Lap'] === next.team['Last Lap'] &&
  prev.team.Gap === next.team.Gap &&
  prev.isMyTeam === next.isMyTeam &&
  prev.isMonitored === next.isMonitored &&
  prev.teamColor === next.teamColor &&
  prev.isUpdated === next.isUpdated &&
  prev.selectedTrackId === next.selectedTrackId &&
  prev.onToggleMonitor === next.onToggleMonitor &&
  prev.onTriggerAlert === next.onTriggerAlert
));

export default StandingsRow;
