import React from 'react';
import { cn } from './cn';

export interface StatProps {
  label: string;
  value: React.ReactNode;
  /** A word under the figure: "closing", "4 to go". */
  sub?: React.ReactNode;
  /** A text colour class when the figure reports a state. */
  tone?: string;
  className?: string;
}

/** One measurement: eyebrow label, a large mono figure, an optional caption.
 *  The figure never truncates; if stats do not fit, wrap the group. */
const Stat: React.FC<StatProps> = ({ label, value, sub, tone = 'text-ink', className }) => (
  <div className={cn('flex flex-col gap-1 min-w-0', className)}>
    <span className="eyebrow text-muted truncate">{label}</span>
    <span className={cn('tabular text-xl md:text-3xl font-bold leading-none tracking-tight', tone)}>{value}</span>
    {sub !== undefined && <span className="text-xs text-muted truncate">{sub}</span>}
  </div>
);

export default Stat;
