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
  isActive?: boolean;          // true when the Fleet Tracker tab is open
  canEditRegistry: boolean;
  onReassign: (fleetKartId: number) => void;
  onAddAssignment: () => void;
  onRegistryChange: () => void;
}

const fmtDelta = (d: number | null): string => {
  if (d == null) return '—';
  const s = Math.abs(d).toFixed(1);
  return d < 0 ? `-${s}s` : `+${s}s`;
};

const locationLabel: Record<string, string> = {
  'on-track': 'On track',
  'in-pits': 'In pits',
  'available': 'Available',
  'unknown': 'Unknown',
};

/**
 * Mobile-first live board of physical karts ranked by inferred pace. Used
 * trackside on a phone: single-column cards, large touch targets, glanceable
 * colour-coded pace/location chips. See FleetTracker integration in
 * RaceDashboard/index.tsx.
 */
const FleetTracker: React.FC<FleetTrackerProps> = ({
  isDarkMode, fleetBoard, registry, trackId, sessionId, isActive, canEditRegistry,
  onReassign, onAddAssignment, onRegistryChange,
}) => {
  const [showRegistry, setShowRegistry] = useState(false);
  const [newLabel, setNewLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [autoMsg, setAutoMsg] = useState<string | null>(null);
  // Remember which track we've already auto-populated so opening the tab
  // doesn't repeatedly fire for a session that genuinely has no teams yet.
  const autoAttemptedTrack = useRef<number | null>(null);

  const sorted = useMemo(() => {
    return [...fleetBoard].sort((a, b) => {
      if (a.pace_delta_vs_fleet == null && b.pace_delta_vs_fleet == null) {
        return a.label.localeCompare(b.label);
      }
      if (a.pace_delta_vs_fleet == null) return 1;
      if (b.pace_delta_vs_fleet == null) return -1;
      return a.pace_delta_vs_fleet - b.pace_delta_vs_fleet;
    });
  }, [fleetBoard]);

  const card = isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200';
  const subtle = isDarkMode ? 'text-gray-400' : 'text-gray-500';

  const paceChipClass = (cls: string) => {
    if (cls === 'fast') return isDarkMode ? 'bg-green-900 text-green-200' : 'bg-green-100 text-green-800';
    if (cls === 'slow') return isDarkMode ? 'bg-red-900 text-red-200' : 'bg-red-100 text-red-800';
    if (cls === 'insufficient') return isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-500';
    return isDarkMode ? 'bg-gray-700 text-gray-200' : 'bg-gray-100 text-gray-700';
  };

  const locationChipClass = (loc: string) => {
    if (loc === 'in-pits') return isDarkMode ? 'bg-amber-900 text-amber-200' : 'bg-amber-100 text-amber-800';
    if (loc === 'on-track') return isDarkMode ? 'bg-blue-900 text-blue-200' : 'bg-blue-100 text-blue-800';
    return isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600';
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

  const handleAutoPopulate = async () => {
    setBusy(true);
    setAutoMsg(null);
    try {
      const res = await ApiService.autoPopulateFleet(trackId);
      const n = res.created_karts?.length ?? 0;
      setAutoMsg(
        n > 0
          ? `Added ${n} kart${n === 1 ? '' : 's'} from the session (assigned to their start teams).`
          : 'Fleet already matches the session — nothing to add.',
      );
      onRegistryChange();
    } catch (err) {
      setAutoMsg(`Auto-add failed: ${err instanceof Error ? err.message : 'error'}`);
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

  // When the operator opens the Fleet Tracker tab on a track whose fleet is
  // still empty (and a session is live), seed the roster automatically — one
  // attempt per track so a team-less session doesn't loop.
  useEffect(() => {
    if (isActive && canEditRegistry && registry.length === 0 && sessionId != null
        && autoAttemptedTrack.current !== trackId && !busy) {
      autoAttemptedTrack.current = trackId;
      handleAutoPopulate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive, canEditRegistry, registry.length, sessionId, trackId]);

  return (
    <div className="p-3 sm:p-4">
      {/* Always-available quick action — large touch target for trackside use */}
      <div className="flex flex-wrap gap-2 mb-3">
        <button
          onClick={onAddAssignment}
          className="flex-1 min-h-[44px] px-4 rounded-lg font-semibold text-white bg-blue-600 hover:bg-blue-700 active:bg-blue-800"
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

      {/* Registry editor (admin only) */}
      {canEditRegistry && showRegistry && (
        <div className={`mb-4 p-3 rounded-lg border ${card}`}>
          {/* One-tap roster seed: create a kart per team in the session and
              assign each to its start team (exact before the first pit). */}
          <button
            onClick={handleAutoPopulate}
            disabled={busy}
            className="w-full min-h-[44px] mb-2 px-4 rounded-lg font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
          >
            Auto-add karts from session
          </button>
          {autoMsg && <p className={`text-xs mb-3 ${subtle}`}>{autoMsg}</p>}
          <p className={`text-xs mb-2 ${subtle}`}>
            Add spare karts waiting in the pit lane below (they start unassigned).
          </p>
          <div className="flex gap-2 mb-3">
            <input
              value={newLabel}
              onChange={e => setNewLabel(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAddKart(); }}
              placeholder="New kart label (e.g. K12)"
              className={`flex-1 min-h-[44px] px-3 rounded-lg border ${isDarkMode ? 'bg-gray-900 border-gray-600 text-white' : 'bg-white border-gray-300'}`}
            />
            <button
              onClick={handleAddKart}
              disabled={busy || !newLabel.trim()}
              className="min-h-[44px] px-4 rounded-lg font-semibold text-white bg-green-600 hover:bg-green-700 disabled:opacity-50"
            >
              Add
            </button>
          </div>
          {registry.length === 0 ? (
            <p className={`text-sm ${subtle}`}>No karts yet. Add the physical karts in your fleet.</p>
          ) : (
            <ul className="space-y-1">
              {registry.map(k => (
                <li key={k.id} className="flex items-center justify-between text-sm">
                  <span className={isDarkMode ? 'text-gray-200' : 'text-gray-800'}>{k.label}</span>
                  <button
                    onClick={() => handleDeleteKart(k.id)}
                    disabled={busy}
                    className="min-h-[36px] px-3 text-red-500 hover:text-red-600"
                  >
                    Retire
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Empty states */}
      {registry.length === 0 && (
        <div className={`text-center py-10 ${subtle}`}>
          <p className="font-medium">No physical karts registered yet.</p>
          {canEditRegistry ? (
            <>
              <p className="text-sm mt-1 mb-4">One tap creates a kart for every team in the session.</p>
              <button
                onClick={handleAutoPopulate}
                disabled={busy}
                className="min-h-[44px] px-5 rounded-lg font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
              >
                Auto-add karts from session
              </button>
              {autoMsg && <p className="text-xs mt-3">{autoMsg}</p>}
              <p className="text-xs mt-2">…or use “Manage fleet” to add karts by hand.</p>
            </>
          ) : (
            <p className="text-sm mt-1">Ask an admin to set up the fleet.</p>
          )}
        </div>
      )}

      {registry.length > 0 && sorted.length === 0 && (
        <div className={`text-center py-10 ${subtle}`}>
          <p className="font-medium">Waiting for lap data…</p>
          <p className="text-sm mt-1">Pace ranking appears once teams complete clean laps.</p>
        </div>
      )}

      {/* Ranked board — single column on phones, two columns on large screens */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {sorted.map(k => (
          <div key={k.fleet_kart_id} className={`rounded-lg border p-3 ${card}`} data-testid="fleet-kart-card">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {k.rank != null && (
                  <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-sm font-bold ${isDarkMode ? 'bg-gray-700 text-gray-100' : 'bg-gray-100 text-gray-800'}`}>
                    {k.rank}
                  </span>
                )}
                <span className={`text-lg font-bold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>{k.label}</span>
              </div>
              <span className={`px-2 py-1 rounded-full text-xs font-semibold ${paceChipClass(k.classification)}`} data-testid="pace-chip">
                {k.classification === 'insufficient' ? 'low data' : fmtDelta(k.pace_delta_vs_fleet)}
              </span>
            </div>

            <div className="flex items-center justify-between text-sm">
              <span className={`px-2 py-1 rounded-full text-xs font-medium ${locationChipClass(k.location)}`} data-testid="location-chip">
                {locationLabel[k.location] || 'Unknown'}
              </span>
              <span className={subtle}>
                {k.holder_team
                  ? <>{k.holder_team}{k.holder_kart_number != null ? ` (#${k.holder_kart_number})` : ''}{k.holder_position != null ? ` · P${k.holder_position}` : ''}</>
                  : 'No team assigned'}
              </span>
            </div>

            <div className="flex items-center justify-between mt-2">
              <span className={`text-xs ${subtle}`}>
                {k.classification === 'insufficient'
                  ? 'Not enough laps yet'
                  : `${k.sample_laps} laps · ${k.n_stints} stint${k.n_stints === 1 ? '' : 's'}`}
              </span>
              <button
                onClick={() => onReassign(k.fleet_kart_id)}
                className={`min-h-[36px] px-3 rounded-lg text-sm font-medium ${isDarkMode ? 'text-blue-300 hover:text-blue-200' : 'text-blue-600 hover:text-blue-700'}`}
              >
                Reassign
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default FleetTracker;
