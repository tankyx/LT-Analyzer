'use client';

import React, { useState } from 'react';
import { FleetKart } from './FleetTracker';

// Minimal shape we need from a live team row (decoupled from the various
// Team interfaces in the app, whose optional fields differ).
type TeamOption = { Kart: string; Team: string };

interface KartAssignmentEntryProps {
  isDarkMode?: boolean;
  registry: FleetKart[];
  teams: TeamOption[];
  prompt?: { teamNumber: string; teamName: string };
  defaultKartId?: number;
  onSubmit: (args: { teamName: string; fleetKartId: number; stintIndex?: number }) => Promise<void>;
  onCancel: () => void;
}

/**
 * Fast manual mapping of a team to the physical kart it just took. Rendered as
 * a bottom-sheet on mobile (thumb-reachable, large picker) and a centered
 * dialog on desktop. Opened automatically when a tracked team pits, or
 * manually from the Fleet Tracker board.
 */
const KartAssignmentEntry: React.FC<KartAssignmentEntryProps> = ({
  isDarkMode, registry, teams, prompt, defaultKartId, onSubmit, onCancel,
}) => {
  const [teamName, setTeamName] = useState(prompt?.teamName ?? '');
  const [fleetKartId, setFleetKartId] = useState<number | ''>(defaultKartId ?? '');
  const [submitting, setSubmitting] = useState(false);

  const activeKarts = registry.filter(k => k.is_active);
  const canSubmit = teamName.trim() !== '' && fleetKartId !== '' && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await onSubmit({ teamName: teamName.trim(), fleetKartId: Number(fleetKartId) });
    } catch {
      // The caller surfaces the failure (alert); keep the sheet open for retry.
    } finally {
      setSubmitting(false);
    }
  };

  const panel = isDarkMode ? 'bg-gray-800 text-gray-100' : 'bg-white text-gray-900';
  const field = isDarkMode ? 'bg-gray-900 border-gray-600 text-white' : 'bg-white border-gray-300';

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50"
      onClick={onCancel}
      data-testid="assignment-overlay"
    >
      <div
        className={`w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl shadow-xl p-4 sm:p-6 ${panel}`}
        onClick={e => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold mb-4">
          {prompt
            ? `${prompt.teamName} (#${prompt.teamNumber}) just pitted — which kart?`
            : 'Record kart assignment'}
        </h2>

        {/* Team field: locked in prompt mode, selectable otherwise */}
        <label className="block text-sm font-medium mb-1">Team</label>
        {prompt ? (
          <div className={`min-h-[44px] px-3 flex items-center rounded-lg border ${field} mb-4 opacity-80`}>
            {prompt.teamName}
          </div>
        ) : (
          <input
            list="fleet-team-options"
            value={teamName}
            onChange={e => setTeamName(e.target.value)}
            placeholder="Team name"
            className={`w-full min-h-[44px] px-3 rounded-lg border ${field} mb-4`}
          />
        )}
        {!prompt && (
          <datalist id="fleet-team-options">
            {teams.map(t => <option key={t.Kart} value={t.Team} />)}
          </datalist>
        )}

        <label className="block text-sm font-medium mb-1">Physical kart</label>
        <select
          value={fleetKartId}
          onChange={e => setFleetKartId(e.target.value === '' ? '' : Number(e.target.value))}
          className={`w-full min-h-[44px] px-3 rounded-lg border ${field} mb-1`}
          data-testid="kart-select"
        >
          <option value="">Select a kart…</option>
          {activeKarts.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
        </select>
        {activeKarts.length === 0 && (
          <p className="text-sm text-red-500 mb-2">No karts registered yet — add some in the fleet manager.</p>
        )}

        <div className="flex gap-2 mt-5">
          <button
            onClick={onCancel}
            className={`flex-1 min-h-[48px] rounded-lg font-medium border ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="flex-1 min-h-[48px] rounded-lg font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default KartAssignmentEntry;
