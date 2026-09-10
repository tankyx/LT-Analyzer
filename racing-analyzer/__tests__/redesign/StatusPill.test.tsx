import React from 'react';
import { render, screen } from '@testing-library/react';
import StatusPill, { describeStatus } from '@/app/components/RaceDashboard/StatusPill';

describe('describeStatus', () => {
  test.each([
    ['On Track', 'live', 'On track'],
    ['Pit-in', 'alarm', 'Pit in'],
    ['Pit-out', 'accent', 'Pit out'],
    ['Finished', 'info', 'Finished'],
    ['Stopped', 'alarm', 'Stopped'],
    ['DNF', 'alarm', 'DNF'],
    ['Lapped', 'muted', 'Lapped'],
    ['Something new', 'muted', 'Something new'],
    [undefined, 'live', 'On track'],
  ])('%s → %s / %s', (status, tone, label) => {
    expect(describeStatus(status as string | undefined)).toEqual({ tone, label });
  });
});

describe('StatusPill', () => {
  test('renders the label and exposes the tone for styling', () => {
    render(<StatusPill status="Pit-in" />);
    const pill = screen.getByText('Pit in');
    expect(pill).toHaveAttribute('data-tone', 'alarm');
  });
  test('inline variant has no capsule background', () => {
    render(<StatusPill status="On Track" variant="inline" />);
    const el = screen.getByText('On track');
    expect(el.className).not.toContain('rounded-full');
  });
});
