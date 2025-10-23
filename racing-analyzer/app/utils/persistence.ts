/**
 * Persistence utility for storing user preferences in localStorage
 */

// Storage keys
const STORAGE_KEYS = {
  SELECTED_TRACK: 'lt_analyzer_selected_track',
  MY_TEAM: 'lt_analyzer_my_team',
  STINT_CONFIG: 'lt_analyzer_stint_config',
  DRIVER_NAMES: 'lt_analyzer_driver_names',
  STINT_ASSIGNMENTS: 'lt_analyzer_stint_assignments',
  CURRENT_DRIVER_INDEX: 'lt_analyzer_current_driver_index',
  TRACK_STINT_PRESETS: 'lt_analyzer_track_stint_presets',
} as const;

// Types for stint presets
export interface StintPreset {
  id: string;
  name: string;
  config: {
    numStints: number;
    minStintTime: number;
    maxStintTime: number;
    pitDuration: number;
    numDrivers: number;
    totalRaceTime: number;
  };
}

export interface TrackStintPresets {
  trackId: number;
  trackName: string;
  presets: StintPreset[];
  activePresetId?: string;
}

/**
 * Generic function to save data to localStorage
 */
export const saveToStorage = <T>(key: string, value: T): void => {
  try {
    if (typeof window !== 'undefined') {
      const serialized = JSON.stringify(value);
      localStorage.setItem(key, serialized);
    }
  } catch (error) {
    console.error(`Error saving to localStorage (${key}):`, error);
  }
};

/**
 * Generic function to load data from localStorage
 */
export const loadFromStorage = <T>(key: string, defaultValue: T): T => {
  try {
    if (typeof window !== 'undefined') {
      const item = localStorage.getItem(key);
      if (item) {
        return JSON.parse(item) as T;
      }
    }
  } catch (error) {
    console.error(`Error loading from localStorage (${key}):`, error);
  }
  return defaultValue;
};

/**
 * Remove item from localStorage
 */
export const removeFromStorage = (key: string): void => {
  try {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(key);
    }
  } catch (error) {
    console.error(`Error removing from localStorage (${key}):`, error);
  }
};

/**
 * Clear all LT Analyzer data from localStorage
 */
export const clearAllStorage = (): void => {
  try {
    if (typeof window !== 'undefined') {
      Object.values(STORAGE_KEYS).forEach(key => {
        localStorage.removeItem(key);
      });
    }
  } catch (error) {
    console.error('Error clearing localStorage:', error);
  }
};

// Specific persistence functions

export const saveSelectedTrack = (trackId: number): void => {
  saveToStorage(STORAGE_KEYS.SELECTED_TRACK, trackId);
};

export const loadSelectedTrack = (): number | null => {
  return loadFromStorage<number | null>(STORAGE_KEYS.SELECTED_TRACK, null);
};

export const saveMyTeam = (teamKart: string): void => {
  saveToStorage(STORAGE_KEYS.MY_TEAM, teamKart);
};

export const loadMyTeam = (): string => {
  return loadFromStorage<string>(STORAGE_KEYS.MY_TEAM, '');
};

export const saveStintConfig = (config: unknown): void => {
  saveToStorage(STORAGE_KEYS.STINT_CONFIG, config);
};

export const loadStintConfig = <T>(defaultConfig: T): T => {
  return loadFromStorage<T>(STORAGE_KEYS.STINT_CONFIG, defaultConfig);
};

export const saveDriverNames = (names: string[]): void => {
  saveToStorage(STORAGE_KEYS.DRIVER_NAMES, names);
};

export const loadDriverNames = (): string[] | null => {
  return loadFromStorage<string[] | null>(STORAGE_KEYS.DRIVER_NAMES, null);
};

export const saveStintAssignments = (assignments: unknown[]): void => {
  saveToStorage(STORAGE_KEYS.STINT_ASSIGNMENTS, assignments);
};

export const loadStintAssignments = <T>(): T[] | null => {
  return loadFromStorage<T[] | null>(STORAGE_KEYS.STINT_ASSIGNMENTS, null);
};

export const saveCurrentDriverIndex = (index: number): void => {
  saveToStorage(STORAGE_KEYS.CURRENT_DRIVER_INDEX, index);
};

export const loadCurrentDriverIndex = (): number => {
  return loadFromStorage<number>(STORAGE_KEYS.CURRENT_DRIVER_INDEX, 0);
};

// Track Stint Presets Management

/**
 * Get all track stint presets from localStorage
 */
const getAllTrackPresets = (): TrackStintPresets[] => {
  return loadFromStorage<TrackStintPresets[]>(STORAGE_KEYS.TRACK_STINT_PRESETS, []);
};

/**
 * Save all track stint presets to localStorage
 */
const saveAllTrackPresets = (allPresets: TrackStintPresets[]): void => {
  saveToStorage(STORAGE_KEYS.TRACK_STINT_PRESETS, allPresets);
};

/**
 * Get presets for a specific track
 */
export const getTrackPresets = (trackId: number): TrackStintPresets | null => {
  const allPresets = getAllTrackPresets();
  return allPresets.find(tp => tp.trackId === trackId) || null;
};

/**
 * Save a new preset for a track
 */
export const saveTrackPreset = (
  trackId: number,
  trackName: string,
  preset: StintPreset
): void => {
  const allPresets = getAllTrackPresets();
  const trackPresetsIndex = allPresets.findIndex(tp => tp.trackId === trackId);

  if (trackPresetsIndex >= 0) {
    // Track exists, update or add preset
    const existingPresetIndex = allPresets[trackPresetsIndex].presets.findIndex(
      p => p.id === preset.id
    );

    if (existingPresetIndex >= 0) {
      // Update existing preset
      allPresets[trackPresetsIndex].presets[existingPresetIndex] = preset;
    } else {
      // Add new preset
      allPresets[trackPresetsIndex].presets.push(preset);
    }
  } else {
    // Track doesn't exist, create new entry
    allPresets.push({
      trackId,
      trackName,
      presets: [preset],
      activePresetId: preset.id,
    });
  }

  saveAllTrackPresets(allPresets);
};

/**
 * Delete a preset from a track
 */
export const deleteTrackPreset = (trackId: number, presetId: string): void => {
  const allPresets = getAllTrackPresets();
  const trackPresetsIndex = allPresets.findIndex(tp => tp.trackId === trackId);

  if (trackPresetsIndex >= 0) {
    const trackPresets = allPresets[trackPresetsIndex];
    trackPresets.presets = trackPresets.presets.filter(p => p.id !== presetId);

    // If we deleted the active preset, clear activePresetId
    if (trackPresets.activePresetId === presetId) {
      trackPresets.activePresetId = trackPresets.presets[0]?.id;
    }

    // If no presets left, remove the track entry
    if (trackPresets.presets.length === 0) {
      allPresets.splice(trackPresetsIndex, 1);
    }

    saveAllTrackPresets(allPresets);
  }
};

/**
 * Set the active preset for a track
 */
export const setActivePreset = (trackId: number, presetId: string): void => {
  const allPresets = getAllTrackPresets();
  const trackPresetsIndex = allPresets.findIndex(tp => tp.trackId === trackId);

  if (trackPresetsIndex >= 0) {
    allPresets[trackPresetsIndex].activePresetId = presetId;
    saveAllTrackPresets(allPresets);
  }
};

/**
 * Get the active preset for a track
 */
export const getActivePreset = (trackId: number): StintPreset | null => {
  const trackPresets = getTrackPresets(trackId);
  if (!trackPresets || !trackPresets.activePresetId) {
    return trackPresets?.presets[0] || null;
  }

  return (
    trackPresets.presets.find(p => p.id === trackPresets.activePresetId) ||
    trackPresets.presets[0] ||
    null
  );
};
