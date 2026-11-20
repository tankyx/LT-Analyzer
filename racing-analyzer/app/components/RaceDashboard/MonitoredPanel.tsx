import React from 'react';
import { Eye, Info, Star, X } from 'lucide-react';
import StatusPill from '../../ui/StatusPill';
import { Panel, PanelHeader, EmptyState } from '../../ui/Panel';
import SegmentedControl from '../../ui/SegmentedControl';
import Button from '../../ui/Button';
import IconButton from '../../ui/IconButton';
import TrendArrows from './TrendArrows';
import { PitAlertButton } from './StandingsRow';
import { displayTeamName } from './lib/teamName';
import type { DeltaData, Team } from './lib/gaps';

interface MonitoredPanelProps {
  /** Gap to your team per monitored kart, already computed. */
  deltas: Record<string, DeltaData>;
  teams: Team[];
  monitoredTeams: string[];
  myTeam: string;
  isQualificationMode: boolean;
  showAdjustedGap: boolean;
  onShowAdjustedGapChange: (adjusted: boolean) => void;
  /** Seconds per pit stop, for the adjusted-gap note. */
  pitStopTime: number;
  /** Kart highlighted from the delta chart, if any. */
  hoveredTeam: string | null;
  /** Livery colour per kart. */
  teamColors: Record<string, string>;
  selectedTrackId: number;
  onStopMonitoring: (kart: string) => void;
  onClearAll: () => void;
  onTriggerAlert?: (kartNum: string, teamName: string, trackId: number) => Promise<void>;
}

/**
 * The Monitored tab's panel: one card per starred team with its gap to you
 * (raw or adjusted for remaining stops), the trend, and last/best/stops.
 */
const MonitoredPanel: React.FC<MonitoredPanelProps> = ({
  deltas,
  teams,
  monitoredTeams,
  myTeam,
  isQualificationMode,
  showAdjustedGap,
  onShowAdjustedGapChange,
  pitStopTime,
  hoveredTeam,
  teamColors,
  selectedTrackId,
  onStopMonitoring,
  onClearAll,
  onTriggerAlert,
}) => (
    <Panel as="div" className="overflow-hidden">
      <PanelHeader
        title="Monitored"
        icon={<Eye size={18} />}
        count={monitoredTeams.length}
        actions={
          <>
            {!isQualificationMode && (
              <SegmentedControl
                label="Gap mode"
                value={showAdjustedGap ? 'adjusted' : 'raw'}
                onChange={(v) => onShowAdjustedGapChange(v === 'adjusted')}
                options={[
                  { value: 'raw', label: 'Raw' },
                  { value: 'adjusted', label: 'Adjusted' },
                ]}
              />
            )}
            {monitoredTeams.length > 0 && (
              <Button variant="quiet" size="sm" className="hover:text-alarm" onClick={onClearAll}>
                Clear all
              </Button>
            )}
          </>
        }
      />

      <div className="p-3 flex flex-col gap-2">
        {Object.entries(deltas)
          .sort((a, b) => a[1].position - b[1].position)
          .map(([kart, data]) => {
            const team = teams.find(t => t.Kart === kart);
            const inPit = team?.Status === 'Pit-in';
            const gapValue = showAdjustedGap ? (data.adjusted_gap ?? data.gap) : data.gap;
            const trend = data.trends?.lap_1?.arrow ? data.trends.lap_1
              : data.trends?.lap_5?.arrow ? data.trends.lap_5
              : data.trends?.lap_10?.arrow ? data.trends.lap_10 : undefined;
            return (
              <div
                key={kart}
                className={`border p-3 flex flex-col gap-2 transition-colors ${
                  inPit ? 'border-alarm/50 bg-alarm/8' : 'border-line bg-canvas'
                } ${hoveredTeam === kart ? 'ring-2 ring-info/60' : ''}`}
                style={{ boxShadow: teamColors[kart] ? `inset 3px 0 0 ${teamColors[kart]}` : undefined }}
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-surface-2 font-cond font-bold text-base flex items-center justify-center shrink-0">
                    {data.position}
                  </div>
                  <div className="flex flex-col min-w-0 flex-1">
                    <span className="text-sm font-semibold truncate">{displayTeamName(data.team_name)}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono tabular text-2xs text-muted">#{kart}</span>
                      {team?.Status !== undefined && <StatusPill status={team.Status} variant="inline" />}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {team && !['Pit-in', 'Finished', 'DNF', 'DSQ'].includes(team.Status || '') && (
                      <PitAlertButton kartNum={kart} teamName={team.Team} trackId={selectedTrackId} onTriggerAlert={onTriggerAlert} />
                    )}
                    <span className={`font-mono tabular text-lg font-semibold ${gapValue >= 0 ? 'text-live' : 'text-alarm'}`}>
                      {gapValue >= 0 ? '+' : '−'}{Math.abs(gapValue).toFixed(3)}
                    </span>
                    {trend ? <TrendArrows trend={showAdjustedGap ? (data.adjusted_trends?.lap_1 ?? trend) : trend} /> : null}
                    <IconButton label={`Stop monitoring ${data.team_name}`} onClick={() => onStopMonitoring(kart)} className="md:w-9 md:h-9">
                      <X size={16} />
                    </IconButton>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="flex flex-col">
                    <span className="eyebrow text-muted">Last</span>
                    <span className="font-mono tabular text-sm">{data.last_lap || '—'}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="eyebrow text-muted">Best</span>
                    <span className="font-mono tabular text-sm">{data.best_lap || '—'}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="eyebrow text-muted">{isQualificationMode ? 'Laps' : 'Stops'}</span>
                    <span className="font-mono tabular text-sm">
                      {data.pit_stops || '0'}
                      {!isQualificationMode && showAdjustedGap && data.remaining_stops !== undefined && (
                        <span className="text-muted"> · {data.remaining_stops > 0 ? `${data.remaining_stops} to go` : 'done'}</span>
                      )}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        {Object.keys(deltas).length === 0 && (
          !myTeam ? (
            <EmptyState icon={<Star size={36} />} title="Pick your team first">
              Gaps are measured from your team, so choose it in the card above.
            </EmptyState>
          ) : (
            <EmptyState icon={<Star size={36} />} title="No teams monitored yet">
              Tap the star on a standings row to track its gap to you.
            </EmptyState>
          )
        )}
      </div>

      {!isQualificationMode && showAdjustedGap && Object.keys(deltas).length > 0 && (
        <div className="px-4 py-2 text-xs text-muted border-t border-line bg-surface-2 flex items-center gap-1.5">
          <Info size={14} className="text-info shrink-0" />
          Adjusted gap accounts for remaining pit stops ({Math.floor(pitStopTime / 60)}:{String(pitStopTime % 60).padStart(2, '0')} per stop). Positive = they are behind you.
        </div>
      )}
    </Panel>
);

export default MonitoredPanel;
