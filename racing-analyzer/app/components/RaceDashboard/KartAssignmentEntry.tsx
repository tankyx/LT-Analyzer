'use client';

import React, { useEffect, useRef, useState } from 'react';
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
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
      if (e.key === 'Tab' && dialogRef.current) {
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, input, select, [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

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

  const panel = 'bg-surface text-ink';
  const field = isDarkMode ? 'bg-canvas border-line text-ink' : 'bg-surface border-line';

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50"
      onClick={onCancel}
      data-testid="assignment-overlay"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={prompt ? `Assign kart to ${prompt.teamName}` : 'Assign a kart'}
        className={`w-full sm:max-w-md rounded-t-none sm:rounded-none shadow-xl p-4 sm:p-6 ${panel}`}
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
          <div className={`min-h-[44px] px-3 flex items-center rounded-none border ${field} mb-4 opacity-80`}>
            {prompt.teamName}
          </div>
        ) : (
          <input
            list="fleet-team-options"
            value={teamName}
            onChange={e => setTeamName(e.target.value)}
            placeholder="Team name"
            className={`w-full min-h-[44px] px-3 rounded-none border ${field} mb-4`}
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
          className={`w-full min-h-[44px] px-3 rounded-none border ${field} mb-1`}
          data-testid="kart-select"
        >
          <option value="">Select a kart…</option>
          {activeKarts.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
        </select>
        {activeKarts.length === 0 && (
          <p className="text-sm text-alarm mb-2">No karts registered yet — add some in the fleet manager.</p>
        )}

        <div className="flex gap-2 mt-5">
          <button
            onClick={onCancel}
            className={`flex-1 min-h-[48px] rounded-none font-medium border ${'border-line'}`}
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="flex-1 min-h-[48px] rounded-none font-semibold text-white bg-info hover:bg-info disabled:opacity-50"
          >
            {submitting ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default KartAssignmentEntry;
