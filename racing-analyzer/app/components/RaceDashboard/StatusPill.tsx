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

// Pill: the label is ink; the hue lives in the dot and the 15% ground. Tone
// text on its own tint reads at 3.6-4.2:1 in the light theme at this size.
// Inline (no ground) keeps the coloured word, which passes on `surface`.
const TONE_CLASSES: Record<StatusTone, { pill: string; dot: string; text: string }> = {
  live: { pill: 'bg-live/15 text-ink', dot: 'bg-live', text: 'text-live' },
  alarm: { pill: 'bg-alarm/15 text-ink', dot: 'bg-alarm', text: 'text-alarm' },
  accent: { pill: 'bg-accent/15 text-ink', dot: 'bg-accent', text: 'text-accent' },
  info: { pill: 'bg-info/15 text-ink', dot: 'bg-info', text: 'text-info' },
  muted: { pill: 'bg-muted/15 text-ink', dot: 'bg-muted', text: 'text-muted' },
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
      <span className={`inline-flex items-center gap-1.5 text-2xs font-semibold ${c.text} ${className}`} data-tone={tone}>
        <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
        {label}
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-2xs font-semibold uppercase tracking-wide whitespace-nowrap ${c.pill} ${className}`}
      data-tone={tone}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {label}
    </span>
  );
};

export default StatusPill;
