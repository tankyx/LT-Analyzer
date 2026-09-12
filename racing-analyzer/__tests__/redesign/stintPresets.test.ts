/**
 * Per-track stint presets: names are unique per track, and saving by an
 * existing id overwrites that preset in place rather than appending a copy.
 */
import {
  findPresetByName,
  isSameStintConfig,
  normalizePresetName,
  getTrackPresets,
  saveTrackPreset,
  StintPreset,
} from '@/app/utils/persistence';

const cfg = (over: Partial<StintPreset['config']> = {}): StintPreset['config'] => ({
  numStints: 6,
  minStintTime: 1800,
  maxStintTime: 2400,
  pitDuration: 158,
  numDrivers: 4,
  totalRaceTime: 21600,
  ...over,
});

const preset = (id: string, name: string, over: Partial<StintPreset['config']> = {}): StintPreset => ({
  id,
  name,
  config: cfg(over),
});

describe('normalizePresetName', () => {
  test('trims, collapses whitespace and case-folds', () => {
    expect(normalizePresetName('  6 Hour   Race ')).toBe('6 hour race');
    expect(normalizePresetName('6 HOUR RACE')).toBe(normalizePresetName('6 hour race'));
  });
});

describe('findPresetByName', () => {
  const presets = [preset('a', '6 Hour Race'), preset('b', '24h Endurance')];

  test('matches regardless of case and surrounding whitespace', () => {
    expect(findPresetByName(presets, '  6 hour race ')?.id).toBe('a');
    expect(findPresetByName(presets, '24H ENDURANCE')?.id).toBe('b');
  });

  test('returns undefined for a genuinely new name or an empty one', () => {
    expect(findPresetByName(presets, '12h Night')).toBeUndefined();
    expect(findPresetByName(presets, '   ')).toBeUndefined();
  });

  test('excludeId lets a preset keep its own name', () => {
    expect(findPresetByName(presets, '6 Hour Race', 'a')).toBeUndefined();
    expect(findPresetByName(presets, '6 Hour Race', 'b')?.id).toBe('a');
  });
});

describe('isSameStintConfig', () => {
  test('true only when every field matches', () => {
    expect(isSameStintConfig(cfg(), cfg())).toBe(true);
    expect(isSameStintConfig(cfg(), cfg({ numStints: 7 }))).toBe(false);
    expect(isSameStintConfig(cfg(), cfg({ pitDuration: 160 }))).toBe(false);
    expect(isSameStintConfig(cfg(), cfg({ totalRaceTime: 21601 }))).toBe(false);
  });

  test('a missing config is never "same"', () => {
    expect(isSameStintConfig(undefined, cfg())).toBe(false);
    expect(isSameStintConfig(cfg(), undefined)).toBe(false);
  });
});

describe('saveTrackPreset', () => {
  let store: Record<string, string>;

  beforeEach(() => {
    store = {};
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation((k: string) => store[k] ?? null);
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation((k: string, v: string) => {
      store[k] = v;
    });
  });
  afterEach(() => jest.restoreAllMocks());

  test('saving a known id overwrites in place, keeping list length and order', () => {
    saveTrackPreset(1, 'Mariembourg', preset('a', '6 Hour Race'));
    saveTrackPreset(1, 'Mariembourg', preset('b', '24h Endurance'));

    saveTrackPreset(1, 'Mariembourg', preset('a', '6 Hour Race', { numStints: 9 }));

    const stored = getTrackPresets(1)!;
    expect(stored.presets).toHaveLength(2);
    expect(stored.presets.map(p => p.id)).toEqual(['a', 'b']);
    expect(stored.presets[0].config.numStints).toBe(9);
  });

  test('an unknown id is appended, and tracks stay separate', () => {
    saveTrackPreset(1, 'Mariembourg', preset('a', '6 Hour Race'));
    saveTrackPreset(2, 'Spa', preset('c', '6 Hour Race'));

    expect(getTrackPresets(1)!.presets.map(p => p.id)).toEqual(['a']);
    expect(getTrackPresets(2)!.presets.map(p => p.id)).toEqual(['c']);
  });
});
