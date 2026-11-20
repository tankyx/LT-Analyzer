import React from 'react';
import SegmentedControl, { SegmentOption } from '../../ui/SegmentedControl';

interface ClassFilterProps {
  selectedClass: string;
  onClassChange: (classValue: string) => void;
  teamCount?: Record<string, number>;
}

const OPTIONS: Array<SegmentOption<string>> = [
  { value: 'all', label: 'All' },
  { value: '1', label: 'Class 1', short: 'C1' },
  { value: '2', label: 'Class 2', short: 'C2' },
];

/** The class filter above the standings. Phones show the short labels. */
const ClassFilter: React.FC<ClassFilterProps> = ({ selectedClass, onClassChange, teamCount = { all: 0, '1': 0, '2': 0 } }) => (
  <SegmentedControl
    label="Filter by class"
    value={selectedClass}
    onChange={onClassChange}
    options={OPTIONS.map((o) => ({ ...o, count: teamCount?.[o.value] ?? 0 }))}
  />
);

export default ClassFilter;
