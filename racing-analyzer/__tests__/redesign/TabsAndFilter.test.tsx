import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TabbedInterface from '@/app/components/RaceDashboard/TabbedInterface';
import ClassFilter from '@/app/components/RaceDashboard/ClassFilter';

describe('TabbedInterface', () => {
  const tabs = [
    { id: 'a', label: 'Alpha', count: 3 },
    { id: 'b', label: 'Bravo' },
  ];

  test('renders both a desktop tablist and a phone bottom nav for the same tabs', () => {
    render(
      <TabbedInterface tabs={tabs}>
        <div>panel a</div>
        <div>panel b</div>
      </TabbedInterface>,
    );
    expect(screen.getByRole('tablist')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Dashboard sections' })).toBeInTheDocument();
    expect(screen.getByText('panel a')).toBeVisible();
    expect(screen.getByText('panel b')).not.toBeVisible();
  });

  test('switching from the bottom nav swaps panels and notifies', async () => {
    const onTabChange = jest.fn();
    render(
      <TabbedInterface tabs={tabs} onTabChange={onTabChange}>
        <div>panel a</div>
        <div>panel b</div>
      </TabbedInterface>,
    );
    const nav = screen.getByRole('navigation', { name: 'Dashboard sections' });
    await userEvent.click(nav.querySelectorAll('button')[1]);
    expect(onTabChange).toHaveBeenCalledWith('b');
    expect(screen.getByText('panel b')).toBeVisible();
    expect(screen.getByText('panel a')).not.toBeVisible();
    expect(screen.getByRole('tab', { name: /Bravo/ })).toHaveAttribute('aria-selected', 'true');
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
