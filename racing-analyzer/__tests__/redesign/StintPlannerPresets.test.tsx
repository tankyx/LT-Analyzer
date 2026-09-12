/**
 * Stint Planner preset flows, driven through the UI:
 *  - an existing preset can be overwritten (Update) instead of only cloned
 *  - a duplicate name is refused, with an explicit overwrite offer
 */
import '@testing-library/jest-dom';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

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
import { getTrackPresets } from '@/app/utils/persistence';

const TRACK_ID = 1;
const TRACK_NAME = 'Mariembourg';

const renderPlanner = () =>
  render(<StintPlanner trackId={TRACK_ID} trackName={TRACK_NAME} myTeam="14" teams={[]} />);

/** Save the current config as a new preset called `name`. */
const saveAsNew = async (name: string) => {
  await userEvent.click(screen.getByRole('button', { name: 'Save as new' }));
  await userEvent.type(screen.getByLabelText('New preset name'), name);
  await userEvent.click(screen.getByRole('button', { name: 'Save' }));
};

/**
 * Set the stint count so the selected preset becomes dirty. fireEvent.change
 * sets the whole value at once; typing into a number input that coerces empty
 * to 1 would concatenate digits instead.
 */
const bumpStints = async (value: string) => {
  fireEvent.change(screen.getByLabelText(/number of stints/i), { target: { value } });
  await waitFor(() => expect(screen.getByLabelText(/number of stints/i)).toHaveValue(Number(value)));
};

describe('StintPlanner presets', () => {
  let store: Record<string, string>;

  beforeEach(() => {
    store = {};
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation((k: string) => store[k] ?? null);
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation((k: string, v: string) => {
      store[k] = v;
    });
    jest.spyOn(window, 'confirm').mockReturnValue(true);
  });
  afterEach(() => jest.restoreAllMocks());

  test('Update overwrites the selected preset instead of creating another one', async () => {
    renderPlanner();
    await saveAsNew('6 Hour Race');
    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1));
    const originalId = getTrackPresets(TRACK_ID)!.presets[0].id;
    const originalStints = getTrackPresets(TRACK_ID)!.presets[0].config.numStints;

    await bumpStints('9');
    expect(await screen.findByText(/Unsaved changes to "6 Hour Race"/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Update' }));

    const stored = getTrackPresets(TRACK_ID)!.presets;
    expect(stored).toHaveLength(1);
    expect(stored[0].id).toBe(originalId);
    expect(stored[0].name).toBe('6 Hour Race');
    expect(stored[0].config.numStints).toBe(9);
    expect(stored[0].config.numStints).not.toBe(originalStints);
    expect(screen.getByRole('status')).toHaveTextContent('Preset saved.');
  });

  test('Update is disabled while the preset already matches the current settings', async () => {
    renderPlanner();
    await saveAsNew('6 Hour Race');
    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1));

    // Freshly saved: the stored config matches the form, nothing to overwrite.
    expect(screen.getByRole('button', { name: 'Update' })).toBeDisabled();

    await bumpStints('13');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Update' })).toBeEnabled());
  });

  test('a duplicate name is refused and never creates a second preset', async () => {
    renderPlanner();
    await saveAsNew('6 Hour Race');
    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1));

    await bumpStints('11');
    await saveAsNew('  6 HOUR race  '); // same name, different case and padding

    expect(await screen.findByRole('alert')).toHaveTextContent('"6 Hour Race" already exists for this track.');
    expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1);
    expect(getTrackPresets(TRACK_ID)!.presets[0].config.numStints).not.toBe(11);
  });

  test('the clash prompt can overwrite the existing preset in place', async () => {
    renderPlanner();
    await saveAsNew('6 Hour Race');
    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1));
    const originalId = getTrackPresets(TRACK_ID)!.presets[0].id;

    await bumpStints('12');
    await saveAsNew('6 hour race');
    await userEvent.click(await screen.findByRole('button', { name: 'Overwrite it' }));

    const stored = getTrackPresets(TRACK_ID)!.presets;
    expect(stored).toHaveLength(1);
    expect(stored[0].id).toBe(originalId);
    expect(stored[0].name).toBe('6 Hour Race'); // original casing kept
    expect(stored[0].config.numStints).toBe(12);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('a genuinely different name still creates a second preset', async () => {
    renderPlanner();
    await saveAsNew('6 Hour Race');
    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1));

    await bumpStints('10');
    await saveAsNew('12h Endurance');

    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(2));
    expect(getTrackPresets(TRACK_ID)!.presets.map(p => p.name)).toEqual(['6 Hour Race', '12h Endurance']);
  });
});
