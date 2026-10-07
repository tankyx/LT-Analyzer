'use client';

import React from 'react';
import { Cpu } from 'lucide-react';

/** One row of `GET /api/device/tokens`. */
export interface DeviceToken {
  id: number;
  label: string;
  created_at: string;
  expires_at: string;
  last_seen_at: string | null;
  revoked: boolean;
  revoked_at?: string | null;
  online: boolean;
}

/** `'all'` = every board following the track; a number = that board only. */
export type PitAlertTargetValue = 'all' | number;

export const PIT_ALERT_TARGET_KEY = 'lt-pit-alert-target';

export function loadPitAlertTarget(): PitAlertTargetValue {
  try {
    const raw = localStorage.getItem(PIT_ALERT_TARGET_KEY);
    if (!raw || raw === 'all') return 'all';
    const n = Number(raw);
    return Number.isInteger(n) && n > 0 ? n : 'all';
  } catch {
    return 'all';
  }
}

export function savePitAlertTarget(v: PitAlertTargetValue): void {
  try {
    localStorage.setItem(PIT_ALERT_TARGET_KEY, String(v));
  } catch {
    /* storage unavailable: the choice just does not persist */
  }
}

/** Ids to send as `target_device_ids`, or undefined for "every board". */
export function targetIdsFor(v: PitAlertTargetValue): number[] | undefined {
  return v === 'all' ? undefined : [v];
}

export interface DeliveryReport {
  delivered_to?: number;
  devices_online?: number;
}

/**
 * Pure: the sentence shown after PIT NOW, from the trigger response. Honest
 * about boards: "no board listening" is a warning, not a success.
 */
export function describeDelivery(
  report: DeliveryReport,
  registeredBoards: number,
): { text: string; tone: 'success' | 'warning' } {
  const delivered = report.delivered_to ?? 0;
  const online = report.devices_online ?? 0;
  if (registeredBoards === 0) {
    return { text: 'sent to your phones', tone: 'success' };
  }
  if (delivered === 0) {
    return {
      text: online === 0 ? 'no board listening' : 'no board on this track or team',
      tone: 'warning',
    };
  }
  const noun = delivered === 1 ? 'board' : 'boards';
  return { text: `${delivered} ${noun} buzzed (${online} online)`, tone: 'success' };
}

interface PitAlertTargetProps {
  devices: DeviceToken[];
  value: PitAlertTargetValue;
  onChange: (v: PitAlertTargetValue) => void;
}

/** Picks which datalogger board a PIT NOW goes to. Rendered only when the
 * account has at least one board registered. */
const PitAlertTarget: React.FC<PitAlertTargetProps> = ({ devices, value, onChange }) => {
  const active = devices.filter((d) => !d.revoked);
  if (active.length === 0) return null;
  const known = value === 'all' || active.some((d) => d.id === value);
  return (
    <label className="shrink-0 flex items-center gap-1.5 text-xs text-muted" title="Which board receives the pit alert">
      <Cpu size={14} className="shrink-0" />
      <span className="sr-only">Pit alert target</span>
      <select
        aria-label="Pit alert target"
        value={known ? String(value) : 'all'}
        onChange={(e) => onChange(e.target.value === 'all' ? 'all' : Number(e.target.value))}
        className="h-9 md:h-8 max-w-[9.5rem] rounded-none border border-line bg-surface text-ink text-xs px-1.5 focus:outline-none focus:ring-2 focus:ring-accent/40"
      >
        <option value="all">All boards</option>
        {active.map((d) => (
          <option key={d.id} value={String(d.id)}>
            {d.online ? '● ' : '○ '}
            {d.label}
          </option>
        ))}
      </select>
    </label>
  );
};

export default PitAlertTarget;
