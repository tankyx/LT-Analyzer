import React from 'react';

export type StatusTone = 'live' | 'alarm' | 'accent' | 'info' | 'muted';

/** Map a timing-feed status string to a colour role and a display label. */
export function describeStatus(status: string | undefined): { tone: StatusTone; label: string } {
  const s = (status || 'On Track').trim();
  switch (s) {
    case 'On Track':
    case 'Up':
      return { tone: 'live', label: s === 'Up' ? 'Up' : 'On track' };
    case 'Pit-in':
      return { tone: 'alarm', label: 'Pit in' };
    case 'Pit-out':
      return { tone: 'accent', label: 'Pit out' };
    case 'Finished':
      return { tone: 'info', label: 'Finished' };
    case 'Stopped':
    case 'DNF':
    case 'DSQ':
    case 'Down':
      return { tone: 'alarm', label: s === 'Stopped' ? 'Stopped' : s };
    case 'Lapped':
      return { tone: 'muted', label: 'Lapped' };
    default:
      return { tone: 'muted', label: s };
  }
}

const TONE_CLASSES: Record<StatusTone, { pill: string; dot: string; text: string }> = {
  live: { pill: 'bg-live/15 text-live', dot: 'bg-live', text: 'text-live' },
  alarm: { pill: 'bg-alarm/15 text-alarm', dot: 'bg-alarm', text: 'text-alarm' },
  accent: { pill: 'bg-accent/20 text-accent', dot: 'bg-accent', text: 'text-accent' },
  info: { pill: 'bg-info/15 text-info', dot: 'bg-info', text: 'text-info' },
  muted: { pill: 'bg-muted/15 text-muted', dot: 'bg-muted', text: 'text-muted' },
};

export const toneClasses = (tone: StatusTone) => TONE_CLASSES[tone];

interface StatusPillProps {
  status?: string;
  /** `pill` = capsule with dot; `inline` = dot + text, no background (dense rows). */
  variant?: 'pill' | 'inline';
  className?: string;
}

const StatusPill: React.FC<StatusPillProps> = ({ status, variant = 'pill', className = '' }) => {
  const { tone, label } = describeStatus(status);
  const c = TONE_CLASSES[tone];
  if (variant === 'inline') {
    return (
      <span className={`inline-flex items-center gap-1.5 text-[11px] font-semibold ${c.text} ${className}`} data-tone={tone}>
        <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
        {label}
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${c.pill} ${className}`}
      data-tone={tone}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {label}
    </span>
  );
};

export default StatusPill;
