import React from 'react';
import { cn } from './cn';

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  /** Shown instead of `label` below the md breakpoint. */
  short?: string;
  count?: number;
}

export interface SegmentedControlProps<T extends string> {
  /** Names the group for assistive tech: "Filter by class". */
  label: string;
  options: Array<SegmentOption<T>>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/** Two to four views of the same data. For moving between tools, use tabs. */
function SegmentedControl<T extends string>({ label, options, value, onChange, className }: SegmentedControlProps<T>) {
  return (
    <div role="group" aria-label={label} className={cn('inline-flex gap-1 p-[3px] bg-surface border border-line', className)}>
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              'h-9 md:h-8 px-3 text-sm font-semibold transition-colors',
              active ? 'bg-surface-2 text-ink' : 'text-muted hover:text-ink',
            )}
          >
            {opt.short ? (
              <>
                <span className="md:hidden">{opt.short}</span>
                <span className="hidden md:inline">{opt.label}</span>
              </>
            ) : (
              opt.label
            )}
            {opt.count !== undefined && opt.count > 0 && <span className="ml-1.5 tabular text-xs opacity-80">{opt.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export default SegmentedControl;
