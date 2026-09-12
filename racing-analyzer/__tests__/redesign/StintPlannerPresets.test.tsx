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

const renameDriver = async (index: number, name: string) => {
  fireEvent.change(screen.getByLabelText(`Driver ${index}`), { target: { value: name } });
  await waitFor(() => expect(screen.getByLabelText(`Driver ${index}`)).toHaveValue(name));
};

/** Wait for the debounced auto-save to land on the stored preset. */
const storedPreset = () => getTrackPresets(TRACK_ID)!.presets[0];
const waitForAutoSave = async (check: (p: ReturnType<typeof storedPreset>) => boolean) =>
  waitFor(() => expect(check(storedPreset())).toBe(true), { timeout: 4000 });

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

  test('editing the plan auto-saves into the selected preset, without cloning it', async () => {
    renderPlanner();
    await saveAsNew('6 Hour Race');
    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1));
    const originalId = storedPreset().id;

    await bumpStints('9');
    await waitForAutoSave(p => p.config.numStints === 9);

    const stored = getTrackPresets(TRACK_ID)!.presets;
    expect(stored).toHaveLength(1);
    expect(stored[0].id).toBe(originalId);
    expect(stored[0].name).toBe('6 Hour Race');
  });

  test('a preset stores the driver names, and auto-saves later edits to them', async () => {
    renderPlanner();
    await renameDriver(1, 'Tanguy');
    await renameDriver(2, 'Céline');
    await saveAsNew('6 Hour Race');

    await waitFor(() => expect(storedPreset().driverNames).toEqual(
      expect.arrayContaining(['Tanguy', 'Céline']),
    ));

    await renameDriver(3, 'Marc');
    await waitForAutoSave(p => !!p.driverNames?.includes('Marc'));
    expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1);
  });

  test('a preset stores the stint table', async () => {
    renderPlanner();
    await saveAsNew('6 Hour Race');

    await waitFor(() => expect(storedPreset().stintAssignments?.length).toBeGreaterThan(0));
    const table = storedPreset().stintAssignments!;
    expect(table[0]).toEqual(
      expect.objectContaining({ stint: 1, driver: expect.any(Number), duration: expect.any(Number) }),
    );
  });

  test('the status line reports auto-saving rather than offering a save button', async () => {
    renderPlanner();
    await saveAsNew('6 Hour Race');
    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(1));

    expect(screen.queryByRole('button', { name: 'Update' })).toBeNull();

    await bumpStints('13');
    expect(await screen.findByText(/Saving to "6 Hour Race"/)).toBeInTheDocument();
    expect(await screen.findByText(/Saved to "6 Hour Race"/, undefined, { timeout: 4000 })).toBeInTheDocument();
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

  test('switching presets restores each ones names and stint table', async () => {
    renderPlanner();

    await renameDriver(1, 'Tanguy');
    await bumpStints('6');
    await saveAsNew('6 Hour Race');
    await waitFor(() => expect(storedPreset().driverNames?.[0]).toBe('Tanguy'));

    await renameDriver(1, 'Marc');
    await bumpStints('14');
    await saveAsNew('24h Endurance');
    await waitFor(() => expect(getTrackPresets(TRACK_ID)!.presets).toHaveLength(2));

    const picker = screen.getByLabelText(/presets:/i);
    const sixHourId = getTrackPresets(TRACK_ID)!.presets[0].id;
    const enduranceId = getTrackPresets(TRACK_ID)!.presets[1].id;

    await userEvent.selectOptions(picker, sixHourId);
    await waitFor(() => expect(screen.getByLabelText('Driver 1')).toHaveValue('Tanguy'));
    expect(screen.getByLabelText(/number of stints/i)).toHaveValue(6);

    await userEvent.selectOptions(picker, enduranceId);
    await waitFor(() => expect(screen.getByLabelText('Driver 1')).toHaveValue('Marc'));
    expect(screen.getByLabelText(/number of stints/i)).toHaveValue(14);

    // Switching back and forth must not have multiplied or reordered them.
    expect(getTrackPresets(TRACK_ID)!.presets.map(p => p.name)).toEqual(['6 Hour Race', '24h Endurance']);
  });

  test('a legacy config-only preset still loads, and the first edit captures the full plan', async () => {
    // A preset saved before presets carried names or a stint table.
    store['lt_analyzer_track_stint_presets'] = JSON.stringify([
      {
        trackId: TRACK_ID,
        trackName: TRACK_NAME,
        activePresetId: 'legacy',
        presets: [
          {
            id: 'legacy',
            name: 'Old Preset',
            config: {
              numStints: 5,
              minStintTime: 25,
              maxStintTime: 60,
              pitDuration: 5,
              numDrivers: 4,
              totalRaceTime: 360,
            },
          },
        ],
      },
    ]);

    renderPlanner();

    // Config applied, stint table rebuilt from it, names left alone.
    await waitFor(() => expect(screen.getByLabelText(/number of stints/i)).toHaveValue(5));
    expect(screen.getByLabelText('Driver 1')).toHaveValue('Driver 1');

    await renameDriver(1, 'Tanguy');
    await waitForAutoSave(p => p.driverNames?.[0] === 'Tanguy');
    expect(storedPreset().id).toBe('legacy');
    expect(storedPreset().stintAssignments?.length).toBeGreaterThan(0);
  });
});
