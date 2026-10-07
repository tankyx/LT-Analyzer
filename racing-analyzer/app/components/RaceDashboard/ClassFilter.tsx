import React from 'react';

interface ClassFilterProps {
  selectedClass: string;
  onClassChange: (classValue: string) => void;
  /** Kept for call-site compatibility; theming now comes from CSS tokens. */
  isDarkMode?: boolean;
  teamCount?: Record<string, number>;
}

const OPTIONS: Array<{ value: string; label: string; short: string }> = [
  { value: 'all', label: 'All', short: 'All' },
  { value: '1', label: 'Class 1', short: 'C1' },
  { value: '2', label: 'Class 2', short: 'C2' },
];

/** Segmented control for the class filter. Mobile shows short labels. */
const ClassFilter: React.FC<ClassFilterProps> = ({
  selectedClass,
  onClassChange,
  teamCount = { all: 0, '1': 0, '2': 0 },
}) => {
  return (
    <div
      role="group"
      aria-label="Filter by class"
      className="inline-flex gap-1 p-[3px] rounded-none bg-surface border border-line"
    >
      {OPTIONS.map((opt) => {
        const active = selectedClass === opt.value;
        const count = teamCount?.[opt.value] ?? 0;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => onClassChange(opt.value)}
            className={`h-9 md:h-8 px-3 rounded-none text-[13px] font-semibold transition-colors ${
              active ? 'bg-surface-2 text-ink' : 'text-muted hover:text-ink'
            }`}
          >
            <span className="md:hidden">{opt.short}</span>
            <span className="hidden md:inline">{opt.label}</span>
            {count > 0 && <span className="ml-1.5 tabular font-mono text-xs opacity-80">{count}</span>}
          </button>
        );
      })}
    </div>
  );
};

export default ClassFilter;
