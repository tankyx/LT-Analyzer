/**
 * Cross-device sync for the planner: a value pushed from another tab on the
 * same account is applied, and is NOT written straight back (which would
 * bounce between tabs forever and could clobber a teammate's edit).
 */
import '@testing-library/jest-dom';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const schedule = jest.fn();
const flush = jest.fn().mockResolvedValue(undefined);
let prefsListener: ((e: { track_id: number; updated_at?: string }) => void) | null = null;

jest.mock('@/app/services/UserPrefsService', () => ({
  __esModule: true,
  getPrefs: jest.fn(),
  makePrefsDebouncer: jest.fn(() => ({ schedule, flush })),
  getLastSeenUpdatedAt: jest.fn(() => null),
}));

jest.mock('@/app/services/WebSocketService', () => ({
  __esModule: true,
  default: {
    addPrefsListener: jest.fn((cb) => {
      prefsListener = cb;
      return () => {
        prefsListener = null;
      };
    }),
  },
}));

import StintPlanner from '@/app/components/RaceDashboard/StintPlanner';
import { getPrefs } from '@/app/services/UserPrefsService';

const TRACK_ID = 1;

const prefsPayload = (over: Record<string, unknown> = {}) => ({
  track_id: TRACK_ID,
  my_team: null,
  monitored_teams: [],
  pit_stop_time: 158,
  required_pit_stops: 7,
  default_lap_time: 90,
  stint_planner_config: {},
  stint_planner_presets: [],
  stint_assignments: [],
  driver_names: [],
  current_driver_index: 0,
  updated_at: '2026-09-12T10:00:00Z',
  ...over,
});

describe('StintPlanner cross-device sync', () => {
  beforeEach(() => {
    schedule.mockClear();
    flush.mockClear();
    prefsListener = null;
    const store: Record<string, string> = {};
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation((k: string) => store[k] ?? null);
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation((k: string, v: string) => {
      store[k] = v;
    });
  });
  afterEach(() => jest.restoreAllMocks());

  const scheduledFields = () =>
    schedule.mock.calls.flatMap((c: [Record<string, unknown>]) => Object.keys(c[0]));

  test('values hydrated from the server are not written back', async () => {
    (getPrefs as jest.Mock).mockResolvedValue(
      prefsPayload({ driver_names: ['Tanguy', 'Marc', 'Céline', 'Luc'] }),
    );

    render(<StintPlanner trackId={TRACK_ID} trackName="Mariembourg" />);

    await waitFor(() => expect(screen.getByLabelText('Driver 1')).toHaveValue('Tanguy'));
    await waitFor(() => expect(schedule).not.toHaveBeenCalledWith(
      expect.objectContaining({ driver_names: expect.anything() }),
    ));
  });

  test('a push from another device is applied and not echoed back', async () => {
    (getPrefs as jest.Mock).mockResolvedValue(prefsPayload());
    render(<StintPlanner trackId={TRACK_ID} trackName="Mariembourg" />);
    await waitFor(() => expect(prefsListener).not.toBeNull());
    schedule.mockClear();

    // Another tab on this account renamed a driver and changed the config.
    (getPrefs as jest.Mock).mockResolvedValue(
      prefsPayload({
        driver_names: ['Tanguy', 'Marc', 'Céline', 'Luc'],
        stint_planner_config: {
          numStints: 11,
          minStintTime: 25,
          maxStintTime: 60,
          pitDuration: 5,
          numDrivers: 4,
          totalRaceTime: 360,
        },
        updated_at: '2026-09-12T10:05:00Z',
      }),
    );
    await prefsListener!({ track_id: TRACK_ID, updated_at: '2026-09-12T10:05:00Z' });

    // Applied: both the names and the config land in the form.
    await waitFor(() => expect(screen.getByLabelText('Driver 1')).toHaveValue('Tanguy'));
    await waitFor(() => expect(screen.getByLabelText(/number of stints/i)).toHaveValue(11));

    // Not echoed: neither field is scheduled for a PUT.
    await waitFor(() => expect(schedule).not.toHaveBeenCalled());
    expect(scheduledFields()).not.toContain('driver_names');
    expect(scheduledFields()).not.toContain('stint_planner_config');
  });

  test('a local edit after a push is still sent', async () => {
    (getPrefs as jest.Mock).mockResolvedValue(prefsPayload());
    render(<StintPlanner trackId={TRACK_ID} trackName="Mariembourg" />);
    await waitFor(() => expect(prefsListener).not.toBeNull());

    (getPrefs as jest.Mock).mockResolvedValue(
      prefsPayload({ driver_names: ['Tanguy', 'Marc', 'Céline', 'Luc'], updated_at: '2026-09-12T10:05:00Z' }),
    );
    await prefsListener!({ track_id: TRACK_ID, updated_at: '2026-09-12T10:05:00Z' });
    await waitFor(() => expect(screen.getByLabelText('Driver 1')).toHaveValue('Tanguy'));
    schedule.mockClear();

    fireEvent.change(screen.getByLabelText('Driver 1'), { target: { value: 'Simon' } });

    await waitFor(() => expect(scheduledFields()).toContain('driver_names'));
  });

  test('a local config edit is sent, along with the stint table it rebuilds', async () => {
    (getPrefs as jest.Mock).mockResolvedValue(prefsPayload());
    render(<StintPlanner trackId={TRACK_ID} trackName="Mariembourg" />);
    await waitFor(() => expect(prefsListener).not.toBeNull());
    schedule.mockClear();

    fireEvent.change(screen.getByLabelText(/number of stints/i), { target: { value: '9' } });

    await waitFor(() => expect(scheduledFields()).toContain('stint_planner_config'));
    await waitFor(() => expect(scheduledFields()).toContain('stint_assignments'));
  });

  test('a snapshot in flight never overwrites a name the user is still typing', async () => {
    (getPrefs as jest.Mock).mockResolvedValue(prefsPayload());
    render(<StintPlanner trackId={TRACK_ID} trackName="Mariembourg" />);
    await waitFor(() => expect(prefsListener).not.toBeNull());

    // The server emits prefs_updated BEFORE its PUT response returns, so our
    // own write can slip past the updated_at dedup. Hold the fetch open to
    // stand in for that window.
    let releaseFetch: (() => void) | null = null;
    (getPrefs as jest.Mock).mockImplementation(
      () =>
        new Promise((resolve) => {
          releaseFetch = () =>
            resolve(prefsPayload({ driver_names: ['Tan', 'Driver 2', 'Driver 3', 'Driver 4'] }));
        }),
    );

    const push = prefsListener!({ track_id: TRACK_ID, updated_at: '2026-09-12T11:00:00Z' });
    await waitFor(() => expect(releaseFetch).not.toBeNull());

    // The user keeps typing while that fetch is outstanding.
    fireEvent.change(screen.getByLabelText('Driver 1'), { target: { value: 'Tanguy' } });
    await waitFor(() => expect(screen.getByLabelText('Driver 1')).toHaveValue('Tanguy'));

    releaseFetch!();
    await push;

    // The stale snapshot must not have reverted the field to "Tan".
    await waitFor(() => expect(screen.getByLabelText('Driver 1')).toHaveValue('Tanguy'));
    expect(screen.getByLabelText('Driver 1')).toHaveValue('Tanguy');
  });
});
