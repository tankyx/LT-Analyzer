'use client';

import React, { useState } from 'react';
import { FleetKart } from './FleetTracker';
import Dialog from '../../ui/Dialog';
import Button from '../../ui/Button';
import { Field, Input, Select } from '../../ui/Field';

// Minimal shape we need from a live team row (decoupled from the various
// Team interfaces in the app, whose optional fields differ).
type TeamOption = { Kart: string; Team: string };

interface KartAssignmentEntryProps {
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
  registry, teams, prompt, defaultKartId, onSubmit, onCancel,
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

  return (
    <Dialog
      label={prompt ? `Assign kart to ${prompt.teamName}` : 'Assign a kart'}
      onClose={onCancel}
      scrimTestId="assignment-overlay"
      className="sm:max-w-md md:w-full p-4 sm:p-6 gap-4"
    >
      <h2 className="text-lg font-bold">
        {prompt
          ? `${prompt.teamName} (#${prompt.teamNumber}) just pitted — which kart?`
          : 'Record kart assignment'}
      </h2>

      {/* Team: locked in prompt mode, selectable otherwise */}
      {prompt ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-muted">Team</span>
          <div className="min-h-[44px] px-3 flex items-center border border-line bg-canvas text-ink opacity-80">
            {prompt.teamName}
          </div>
        </div>
      ) : (
        <Field label="Team">
          <Input
            list="fleet-team-options"
            value={teamName}
            onChange={e => setTeamName(e.target.value)}
            placeholder="Team name"
          />
        </Field>
      )}
      {!prompt && (
        <datalist id="fleet-team-options">
          {teams.map(t => <option key={t.Kart} value={t.Team} />)}
        </datalist>
      )}

      <Field
        label="Physical kart"
        error={activeKarts.length === 0 ? 'No karts registered yet — add some in the fleet manager.' : undefined}
      >
        <Select
          value={fleetKartId}
          onChange={e => setFleetKartId(e.target.value === '' ? '' : Number(e.target.value))}
          data-testid="kart-select"
        >
          <option value="">Select a kart…</option>
          {activeKarts.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
        </Select>
      </Field>

      <div className="flex gap-2 mt-1">
        <Button size="lg" className="flex-1" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="primary" size="lg" className="flex-1" onClick={handleSubmit} disabled={!canSubmit}>
          {submitting ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </Dialog>
  );
};

export default KartAssignmentEntry;
