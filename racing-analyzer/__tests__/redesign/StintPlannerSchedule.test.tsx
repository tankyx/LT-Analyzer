/**
 * The planned schedule must always span exactly the configured race length:
 * changing the race length or the pit duration has to rebuild the table, and
 * per-stint rounding must not lose or invent minutes.
 */
import '@testing-library/jest-dom';
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

jest.mock('@/app/services/UserPrefsService', () => ({
  __esModule: true,
  getPrefs: jest.fn().mockResolvedValue({}),
  makePrefsDebouncer: jest.fn(() => ({ schedule: jest.fn(), flush: jest.fn() })),
  getLastSeenUpdatedAt: jest.fn(() => null),
}));
jest.mock('@/app/services/WebSocketService', () => ({
  __esModule: true,
  default: { addPrefsListener: jest.fn(() => () => {}) },
}));

import StintPlanner from '@/app/components/RaceDashboard/StintPlanner';

const setField = async (label: RegExp, value: string) => {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  await waitFor(() => expect(screen.getByLabelText(label)).toHaveValue(Number(value)));
};

/** Durations from the stint table, in order. */
const durations = (): number[] =>
  screen
    .queryAllByLabelText(/^Stint \d+ duration in minutes$/)
    .map((el) => Number((el as HTMLInputElement).value));

/** Total wall-clock the plan occupies: stint time plus the pit stops between. */
const plannedSpan = (pitDuration: number): number => {
  const d = durations();
  return d.reduce((a, b) => a + b, 0) + pitDuration * Math.max(0, d.length - 1);
};

describe('StintPlanner schedule', () => {
  beforeEach(() => {
    const store: Record<string, string> = {};
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation((k: string) => store[k] ?? null);
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation((k: string, v: string) => {
      store[k] = v;
    });
  });
  afterEach(() => jest.restoreAllMocks());

  test('a 358 minute race with 10 stints is planned over 358 minutes, not the previous length', async () => {
    render(<StintPlanner trackId={1} trackName="Mariembourg" />);
    await waitFor(() => expect(durations().length).toBeGreaterThan(0));

    await setField(/number of stints/i, '10');
    await setField(/total race time/i, '358');

    await waitFor(() => expect(durations()).toHaveLength(10));
    expect(plannedSpan(5)).toBe(358);
  });

  test('changing the race length alone rebuilds the plan', async () => {
    render(<StintPlanner trackId={1} trackName="Mariembourg" />);
    await waitFor(() => expect(durations().length).toBeGreaterThan(0));

    await setField(/total race time/i, '240');
    await waitFor(() => expect(plannedSpan(5)).toBe(240));

    await setField(/total race time/i, '358');
    await waitFor(() => expect(plannedSpan(5)).toBe(358));
  });

  test('changing the pit duration rebuilds the plan to still fit the race', async () => {
    render(<StintPlanner trackId={1} trackName="Mariembourg" />);
    await waitFor(() => expect(durations().length).toBeGreaterThan(0));

    await setField(/total race time/i, '358');
    await setField(/pit duration/i, '3');

    await waitFor(() => expect(plannedSpan(3)).toBe(358));
  });

  test('the schedule fills the race exactly for awkward divisions', async () => {
    render(<StintPlanner trackId={1} trackName="Mariembourg" />);
    await waitFor(() => expect(durations().length).toBeGreaterThan(0));

    for (const [stints, total] of [['7', '358'], ['11', '359'], ['13', '361'], ['9', '400']]) {
      await setField(/number of stints/i, stints);
      await setField(/total race time/i, total);
      await waitFor(() => expect(durations()).toHaveLength(Number(stints)));
      expect(plannedSpan(5)).toBe(Number(total));
    }
  });

  test('the last stint ends at the chequered flag', async () => {
    render(<StintPlanner trackId={1} trackName="Mariembourg" />);
    await waitFor(() => expect(durations().length).toBeGreaterThan(0));

    await setField(/number of stints/i, '10');
    await setField(/total race time/i, '358');
    await waitFor(() => expect(durations()).toHaveLength(10));

    const rows = screen.getAllByRole('row').filter((r) => within(r).queryAllByRole('spinbutton').length > 0);
    expect(within(rows[rows.length - 1]).getByText(/- 5h 58m$/)).toBeInTheDocument();
  });

  test('the summary spells out stints versus pit stops and the planned total', async () => {
    render(<StintPlanner trackId={1} trackName="Mariembourg" />);
    await waitFor(() => expect(durations().length).toBeGreaterThan(0));

    await setField(/number of stints/i, '10');
    await setField(/total race time/i, '358');
    await waitFor(() => expect(durations()).toHaveLength(10));

    const summary = screen.getAllByRole('status').find(el => /pit stops/.test(el.textContent || ''))!;
    expect(summary).toHaveTextContent('10 stints');
    expect(summary).toHaveTextContent('9 pit stops');
    expect(summary).toHaveTextContent('Planned 5h 58m of 5h 58m');
    expect(summary.textContent).not.toMatch(/short by|over by/);
  });

  test('a plan that no longer fits the race is flagged rather than left silent', async () => {
    render(<StintPlanner trackId={1} trackName="Mariembourg" />);
    await waitFor(() => expect(durations().length).toBeGreaterThan(0));

    await setField(/number of stints/i, '6');
    await setField(/total race time/i, '300');
    await waitFor(() => expect(plannedSpan(5)).toBe(300));

    // Shorten the LAST stint: there is nothing after it to absorb the time,
    // so the plan now stops short of the flag.
    fireEvent.change(screen.getByLabelText('Stint 6 duration in minutes'), { target: { value: '25' } });

    const summary = () => screen.getAllByRole('status').find(el => /pit stops/.test(el.textContent || ''))!;
    await waitFor(() => expect(summary().textContent).toMatch(/short by|over by/));
  });
});
