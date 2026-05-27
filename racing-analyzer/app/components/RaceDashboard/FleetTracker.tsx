'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import ApiService from '../../services/ApiService';
import { FleetKartState } from '../../services/WebSocketService';

// Physical-kart registry item (mirrors the backend fleet_karts row).
export interface FleetKart {
  id: number;
  label: string;
  notes?: string | null;
  is_active: boolean;
}

interface FleetTrackerProps {
  isDarkMode?: boolean;
  fleetBoard: FleetKartState[];
  registry: FleetKart[];
  trackId: number;
  sessionId?: number | null;
  isActive?: boolean;
  canEditRegistry: boolean;
  onReassign: (fleetKartId: number) => void;   // opens the assign-to-team sheet
  onAddAssignment: () => void;
  onRegistryChange: () => void;                 // refetch registry + board
}

const DEFAULT_LANES = 4;
const MAX_LANES = 8;

// Static (literal) class strings so Tailwind keeps them through purge.
const LANE_STYLE = [
  { light: 'bg-blue-50 border-blue-300', dark: 'bg-blue-900/30 border-blue-700', dot: 'bg-blue-500' },
  { light: 'bg-emerald-50 border-emerald-300', dark: 'bg-emerald-900/30 border-emerald-700', dot: 'bg-emerald-500' },
  { light: 'bg-amber-50 border-amber-300', dark: 'bg-amber-900/30 border-amber-700', dot: 'bg-amber-500' },
  { light: 'bg-violet-50 border-violet-300', dark: 'bg-violet-900/30 border-violet-700', dot: 'bg-violet-500' },
  { light: 'bg-rose-50 border-rose-300', dark: 'bg-rose-900/30 border-rose-700', dot: 'bg-rose-500' },
  { light: 'bg-cyan-50 border-cyan-300', dark: 'bg-cyan-900/30 border-cyan-700', dot: 'bg-cyan-500' },
  { light: 'bg-lime-50 border-lime-300', dark: 'bg-lime-900/30 border-lime-700', dot: 'bg-lime-500' },
  { light: 'bg-orange-50 border-orange-300', dark: 'bg-orange-900/30 border-orange-700', dot: 'bg-orange-500' },
];
const laneStyle = (lane: number) => LANE_STYLE[(lane - 1) % LANE_STYLE.length];

const fmtDelta = (d: number | null): string =>
  d == null ? '' : `${d < 0 ? '-' : '+'}${Math.abs(d).toFixed(1)}s`;

/**
 * Mobile-first pit-lane kanban: On track / In pit / Available columns, the
 * Available column split into colored lanes. On track <-> In pit follow the
 * live timing automatically; the user assigns karts out of Available and
 * releases dropped karts back into a lane. Tap a card for actions (works
 * one-handed) or drag on desktop.
 */
const FleetTracker: React.FC<FleetTrackerProps> = ({
  isDarkMode, fleetBoard, registry, trackId, sessionId, isActive, canEditRegistry,
  onReassign, onAddAssignment, onRegistryChange,
}) => {
  const [showRegistry, setShowRegistry] = useState(false);
  const [newLabel, setNewLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [autoMsg, setAutoMsg] = useState<string | null>(null);
  const [laneCount, setLaneCount] = useState(DEFAULT_LANES);
  const [selected, setSelected] = useState<FleetKartState | null>(null);  // tap-to-move
  const dragKart = useRef<FleetKartState | null>(null);
  const autoAttemptedTrack = useRef<number | null>(null);

  // Lane count is a per-track display preference (kept client-side).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const v = parseInt(window.localStorage.getItem(`fleet_lanes_${trackId}`) || '', 10);
    setLaneCount(Number.isFinite(v) && v >= 1 ? Math.min(v, MAX_LANES) : DEFAULT_LANES);
  }, [trackId]);

  const changeLaneCount = (n: number) => {
    const clamped = Math.max(1, Math.min(MAX_LANES, n));
    setLaneCount(clamped);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(`fleet_lanes_${trackId}`, String(clamped));
    }
  };

  const subtle = isDarkMode ? 'text-gray-400' : 'text-gray-500';
  const colHeader = isDarkMode ? 'text-gray-200' : 'text-gray-700';
  const cardBase = isDarkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200 text-gray-900';

  const paceChipClass = (cls: string) => {
    if (cls === 'fast') return isDarkMode ? 'bg-green-900 text-green-200' : 'bg-green-100 text-green-800';
    if (cls === 'slow') return isDarkMode ? 'bg-red-900 text-red-200' : 'bg-red-100 text-red-800';
    if (cls === 'insufficient') return isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-500';
    return isDarkMode ? 'bg-gray-700 text-gray-200' : 'bg-gray-100 text-gray-700';
  };

  const onTrack = useMemo(
    () => fleetBoard.filter(k => k.column === 'on_track').sort(byPace), [fleetBoard]);
  const inPit = useMemo(
    () => fleetBoard.filter(k => k.column === 'in_pit').sort(byPace), [fleetBoard]);
  const available = useMemo(
    () => fleetBoard.filter(k => k.column === 'available'), [fleetBoard]);
  const unlaned = available.filter(k => k.lane == null);
  const lanes = Array.from({ length: laneCount }, (_, i) => i + 1);

  // ---- actions --------------------------------------------------------------
  const doRelease = async (kart: FleetKartState, lane: number | null) => {
    setBusy(true);
    try {
      await ApiService.releaseFleetKart(trackId, kart.fleet_kart_id, lane, sessionId ?? null);
      onRegistryChange();
    } catch (err) {
      console.error('release failed', err);
    } finally {
      setBusy(false);
      setSelected(null);
    }
  };

  const doSetLane = async (kart: FleetKartState, lane: number | null) => {
    setBusy(true);
    try {
      await ApiService.setFleetKartLane(trackId, kart.fleet_kart_id, lane);
      onRegistryChange();
    } catch (err) {
      console.error('move lane failed', err);
    } finally {
      setBusy(false);
      setSelected(null);
    }
  };

  const doAssign = (kart: FleetKartState) => {
    setSelected(null);
    onReassign(kart.fleet_kart_id);  // opens the team picker (preselected kart)
  };

  // Drop a dragged card into a lane (release if held, re-lane if available).
  const dropToLane = (lane: number) => {
    const k = dragKart.current;
    dragKart.current = null;
    if (!k) return;
    if (k.column === 'available') doSetLane(k, lane);
    else doRelease(k, lane);
  };
  const dropToOnTrack = () => {
    const k = dragKart.current;
    dragKart.current = null;
    if (k && k.column === 'available') doAssign(k);
  };

  // ---- registry management --------------------------------------------------
  const handleAutoPopulate = async () => {
    setBusy(true);
    setAutoMsg(null);
    try {
      const res = await ApiService.autoPopulateFleet(trackId);
      const n = res.created_karts?.length ?? 0;
      setAutoMsg(n > 0
        ? `Added ${n} kart${n === 1 ? '' : 's'} from the session.`
        : 'Fleet already matches the session.');
      onRegistryChange();
    } catch (err) {
      setAutoMsg(`Auto-add failed: ${err instanceof Error ? err.message : 'error'}`);
    } finally {
      setBusy(false);
    }
  };

  const handleAddKart = async () => {
    const label = newLabel.trim();
    if (!label) return;
    setBusy(true);
    try {
      await ApiService.createFleetKart(trackId, label);
      setNewLabel('');
      onRegistryChange();
    } catch (err) {
      console.error('add kart failed', err);
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteKart = async (kartId: number) => {
    setBusy(true);
    try {
      await ApiService.deleteFleetKart(trackId, kartId);
      onRegistryChange();
    } catch (err) {
      console.error('delete kart failed', err);
    } finally {
      setBusy(false);
    }
  };

  // Auto-seed the roster when the tab is opened on an empty fleet + live session.
  useEffect(() => {
    if (isActive && canEditRegistry && registry.length === 0 && sessionId != null
        && autoAttemptedTrack.current !== trackId && !busy) {
      autoAttemptedTrack.current = trackId;
      handleAutoPopulate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive, canEditRegistry, registry.length, sessionId, trackId]);

  // ---- card renderer --------------------------------------------------------
  const renderCard = (kart: FleetKartState) => (
    <div
      key={kart.fleet_kart_id}
      data-testid="fleet-kart-card"
      draggable
      onDragStart={() => { dragKart.current = kart; }}
      onClick={() => setSelected(kart)}
      className={`rounded-lg border p-2 mb-2 cursor-pointer active:opacity-80 ${cardBase}`}
    >
      <div className="flex items-center justify-between">
        <span className="font-bold">{kart.label}</span>
        {kart.classification !== 'insufficient' && kart.pace_delta_vs_fleet != null ? (
          <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${paceChipClass(kart.classification)}`}
            data-testid="pace-chip">
            {fmtDelta(kart.pace_delta_vs_fleet)}
          </span>
        ) : (
          <span className={`px-2 py-0.5 rounded-full text-xs ${paceChipClass('insufficient')}`}>low data</span>
        )}
      </div>
      <div className={`text-xs mt-1 ${subtle}`}>
        {kart.holder_team
          ? <>{kart.holder_team}{kart.holder_position != null ? ` · P${kart.holder_position}` : ''}</>
          : 'unassigned'}
      </div>
    </div>
  );

  const columnWrap = isDarkMode ? 'bg-gray-900/40' : 'bg-gray-50';

  return (
    <div className="p-3 sm:p-4">
      {/* Quick actions */}
      <div className="flex flex-wrap gap-2 mb-3">
        <button
          onClick={onAddAssignment}
          className="flex-1 min-h-[44px] px-4 rounded-lg font-semibold text-white bg-blue-600 hover:bg-blue-700"
        >
          + Record kart assignment
        </button>
        {canEditRegistry && (
          <button
            onClick={() => setShowRegistry(s => !s)}
            className={`min-h-[44px] px-4 rounded-lg font-medium border ${isDarkMode ? 'border-gray-600 text-gray-200' : 'border-gray-300 text-gray-700'}`}
          >
            {showRegistry ? 'Close fleet' : 'Manage fleet'}
          </button>
        )}
      </div>

      {/* Registry editor */}
      {canEditRegistry && showRegistry && (
        <div className={`mb-4 p-3 rounded-lg border ${cardBase}`}>
          <button
            onClick={handleAutoPopulate}
            disabled={busy}
            className="w-full min-h-[44px] mb-2 px-4 rounded-lg font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
          >
            Auto-add karts from session
          </button>
          {autoMsg && <p className={`text-xs mb-3 ${subtle}`}>{autoMsg}</p>}
          <div className="flex items-center justify-between mb-3">
            <span className={`text-sm ${subtle}`}>Pit lanes</span>
            <div className="flex items-center gap-2">
              <button onClick={() => changeLaneCount(laneCount - 1)}
                className={`w-9 h-9 rounded-lg border text-lg ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>−</button>
              <span className="w-6 text-center font-semibold">{laneCount}</span>
              <button onClick={() => changeLaneCount(laneCount + 1)}
                className={`w-9 h-9 rounded-lg border text-lg ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>+</button>
            </div>
          </div>
          <div className="flex gap-2 mb-2">
            <input
              value={newLabel}
              onChange={e => setNewLabel(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAddKart(); }}
              placeholder="Add a kart (e.g. K12)"
              className={`flex-1 min-h-[44px] px-3 rounded-lg border ${isDarkMode ? 'bg-gray-900 border-gray-600 text-white' : 'bg-white border-gray-300'}`}
            />
            <button onClick={handleAddKart} disabled={busy || !newLabel.trim()}
              className="min-h-[44px] px-4 rounded-lg font-semibold text-white bg-green-600 hover:bg-green-700 disabled:opacity-50">Add</button>
          </div>
          {registry.length > 0 && (
            <ul className="space-y-1 max-h-32 overflow-y-auto">
              {registry.map(k => (
                <li key={k.id} className="flex items-center justify-between text-sm">
                  <span>{k.label}</span>
                  <button onClick={() => handleDeleteKart(k.id)} disabled={busy}
                    className="min-h-[36px] px-3 text-red-500 hover:text-red-600">Retire</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Empty state */}
      {registry.length === 0 ? (
        <div className={`text-center py-10 ${subtle}`}>
          <p className="font-medium">No physical karts registered yet.</p>
          {canEditRegistry ? (
            <>
              <p className="text-sm mt-1 mb-4">One tap creates a kart for every team in the session.</p>
              <button onClick={handleAutoPopulate} disabled={busy}
                className="min-h-[44px] px-5 rounded-lg font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50">
                Auto-add karts from session
              </button>
              {autoMsg && <p className="text-xs mt-3">{autoMsg}</p>}
            </>
          ) : <p className="text-sm mt-1">Ask an admin to set up the fleet.</p>}
        </div>
      ) : (
        // 3-column board (stacks on mobile)
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* On track */}
          <div
            onDragOver={e => e.preventDefault()} onDrop={dropToOnTrack}
            className={`rounded-lg p-2 ${columnWrap}`} data-testid="col-on-track"
          >
            <h3 className={`font-semibold mb-2 ${colHeader}`}>On track <span className={subtle}>({onTrack.length})</span></h3>
            {onTrack.map(renderCard)}
            {onTrack.length === 0 && <p className={`text-xs ${subtle}`}>Drag an Available kart here to assign it.</p>}
          </div>

          {/* In pit (timing-driven) */}
          <div className={`rounded-lg p-2 ${columnWrap}`} data-testid="col-in-pit">
            <h3 className={`font-semibold mb-2 ${colHeader}`}>In pit <span className={subtle}>({inPit.length})</span></h3>
            {inPit.map(renderCard)}
            {inPit.length === 0 && <p className={`text-xs ${subtle}`}>Teams currently in the pits appear here.</p>}
          </div>

          {/* Available, split into lanes */}
          <div className={`rounded-lg p-2 ${columnWrap}`} data-testid="col-available">
            <h3 className={`font-semibold mb-2 ${colHeader}`}>Available <span className={subtle}>({available.length})</span></h3>
            {lanes.map(lane => {
              const st = laneStyle(lane);
              const karts = available.filter(k => k.lane === lane);
              return (
                <div key={lane}
                  onDragOver={e => e.preventDefault()} onDrop={() => dropToLane(lane)}
                  data-testid={`lane-${lane}`}
                  className={`rounded-lg border p-2 mb-2 ${isDarkMode ? st.dark : st.light}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`w-3 h-3 rounded-full ${st.dot}`} />
                    <span className={`text-xs font-medium ${colHeader}`}>Lane {lane}</span>
                  </div>
                  {karts.map(renderCard)}
                  {karts.length === 0 && <p className={`text-xs ${subtle}`}>empty</p>}
                </div>
              );
            })}
            {unlaned.length > 0 && (
              <div data-testid="lane-unsorted"
                className={`rounded-lg border border-dashed p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                <span className={`text-xs font-medium ${colHeader}`}>Just dropped — place in a lane</span>
                <div className="mt-1">{unlaned.map(renderCard)}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tap-to-move action sheet */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50"
          onClick={() => setSelected(null)} data-testid="kart-action-sheet">
          <div onClick={e => e.stopPropagation()}
            className={`w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl shadow-xl p-4 sm:p-6 ${isDarkMode ? 'bg-gray-800 text-gray-100' : 'bg-white text-gray-900'}`}>
            <h2 className="text-lg font-bold mb-1">Kart {selected.label}</h2>
            <p className={`text-sm mb-4 ${subtle}`}>
              {selected.column === 'available'
                ? (selected.lane != null ? `In lane ${selected.lane}` : 'Just dropped (no lane)')
                : `On ${selected.holder_team || 'a team'} (${selected.column === 'in_pit' ? 'in pit' : 'on track'})`}
            </p>

            {selected.column === 'available' ? (
              <>
                <button onClick={() => doAssign(selected)}
                  className="w-full min-h-[48px] mb-3 rounded-lg font-semibold text-white bg-blue-600 hover:bg-blue-700">
                  Assign to a team…
                </button>
                <p className={`text-sm mb-2 ${subtle}`}>Move to lane</p>
              </>
            ) : (
              <p className={`text-sm mb-2 ${subtle}`}>Team dropped it — release to lane</p>
            )}

            <div className="flex flex-wrap gap-2 mb-2">
              {lanes.map(lane => {
                const st = laneStyle(lane);
                return (
                  <button key={lane} disabled={busy}
                    onClick={() => selected.column === 'available' ? doSetLane(selected, lane) : doRelease(selected, lane)}
                    className={`min-h-[44px] px-4 rounded-lg border font-medium flex items-center gap-2 ${isDarkMode ? st.dark : st.light}`}>
                    <span className={`w-3 h-3 rounded-full ${st.dot}`} />Lane {lane}
                  </button>
                );
              })}
            </div>

            <button onClick={() => setSelected(null)}
              className={`w-full min-h-[44px] mt-2 rounded-lg font-medium border ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

function byPace(a: FleetKartState, b: FleetKartState): number {
  if (a.pace_delta_vs_fleet == null && b.pace_delta_vs_fleet == null) return a.label.localeCompare(b.label);
  if (a.pace_delta_vs_fleet == null) return 1;
  if (b.pace_delta_vs_fleet == null) return -1;
  return a.pace_delta_vs_fleet - b.pace_delta_vs_fleet;
}

export default FleetTracker;
