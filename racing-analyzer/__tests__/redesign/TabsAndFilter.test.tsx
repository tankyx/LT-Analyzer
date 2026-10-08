import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TabbedInterface from '@/app/components/RaceDashboard/TabbedInterface';
import ClassFilter from '@/app/components/RaceDashboard/ClassFilter';

describe('TabbedInterface', () => {
  const tabs = [
    { id: 'a', label: 'Alpha', count: 3 },
    { id: 'b', label: 'Bravo' },
  ];

  test('renders a desktop console dock and a phone bottom nav for the same tabs', () => {
    render(
      <TabbedInterface tabs={tabs} pinnedId="a">
        <div>panel a</div>
        <div>panel b</div>
      </TabbedInterface>,
    );
    // desktop dock (excludes the pinned tower tab)
    const dock = screen.getByRole('tablist', { name: 'Dashboard tools' });
    expect(within(dock).getByRole('tab', { name: /Bravo/ })).toBeInTheDocument();
    // phone bottom nav (all tabs)
    const nav = screen.getByRole('navigation', { name: 'Dashboard sections' });
    expect(within(nav).getByRole('button', { name: /Alpha/ })).toBeInTheDocument();
    expect(within(nav).getByRole('button', { name: /Bravo/ })).toBeInTheDocument();
  });

  test('switching from the bottom nav swaps panels and notifies', async () => {
    const onTabChange = jest.fn();
    render(
      <TabbedInterface tabs={tabs} pinnedId="a" onTabChange={onTabChange}>
        <div>panel a</div>
        <div>panel b</div>
      </TabbedInterface>,
    );
    const nav = screen.getByRole('navigation', { name: 'Dashboard sections' });
    await userEvent.click(within(nav).getByRole('button', { name: /Bravo/ }));
    expect(onTabChange).toHaveBeenCalledWith('b');
    // the dock tab reflects the active workbench tab
    const dock = screen.getByRole('tablist', { name: 'Dashboard tools' });
    expect(within(dock).getByRole('tab', { name: /Bravo/ })).toHaveAttribute('aria-selected', 'true');
  });
});

describe('ClassFilter', () => {
  test('shows counts and reports the chosen class', async () => {
    const onClassChange = jest.fn();
    render(<ClassFilter selectedClass="all" onClassChange={onClassChange} teamCount={{ all: 24, '1': 13, '2': 11 }} />);
    expect(screen.getByRole('button', { name: /All.*24/ })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: /Class 1.*13/ }));
    expect(onClassChange).toHaveBeenCalledWith('1');
  });
});
