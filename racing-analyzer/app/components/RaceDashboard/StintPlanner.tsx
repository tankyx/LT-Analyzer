import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  saveStintConfig,
  loadStintConfig,
  saveDriverNames,
  loadDriverNames,
  saveStintAssignments,
  loadStintAssignments,
  saveCurrentDriverIndex,
  loadCurrentDriverIndex,
  StintPreset,
  getTrackPresets,
  saveTrackPreset,
  deleteTrackPreset,
  setActivePreset,
  getActivePreset,
  findPresetByName,
  presetMatchesPlan
} from '../../utils/persistence';
import {
  getPrefs as fetchUserPrefs,
  makePrefsDebouncer,
  getLastSeenUpdatedAt,
  UserTrackPrefs,
} from '../../services/UserPrefsService';
import webSocketService from '../../services/WebSocketService';
import {
  StintConfig,
  StintAssignment,
  buildStintTable,
  planFitsConfig,
  planSignature,
  plannedSpan,
  drivingTime,
} from './lib/stintPlan';

interface StintPlannerProps {
  isDarkMode?: boolean;
  myTeam?: string;
  teams?: Array<{
    Team: string;
    Status?: string;
  }>;
  isSimulating?: boolean;
  sessionInfo?: {
    light?: string;
  };
  trackId?: number;
  trackName?: string;
}

interface DriverStats {
  driver: number;
  name: string;
  totalTime: number;
  numStints: number;
  jokerStints: number;
  longStints: number;
}

interface ActiveStint {
  driverIndex: number;
  startTime: Date;
  elapsedTime: number;
  isPitStop: boolean;
}

const StintPlanner: React.FC<StintPlannerProps> = ({
  isDarkMode = false,
  myTeam,
  teams = [],
  isSimulating = false,
  sessionInfo,
  trackId,
  trackName
}) => {
  const defaultConfig: StintConfig = {
    numStints: 8,
    minStintTime: 25,
    maxStintTime: 60,
    pitDuration: 5,
    numDrivers: 4,
    totalRaceTime: 360,
  };

  // Initialize with default values (not from localStorage due to Next.js SSR)
  const [config, setConfig] = useState<StintConfig>(defaultConfig);
  const [stintAssignments, setStintAssignments] = useState<StintAssignment[]>([]);
  const [driverNames, setDriverNames] = useState<string[]>(['Driver 1', 'Driver 2', 'Driver 3', 'Driver 4']);
  const [currentDriverIndex, setCurrentDriverIndex] = useState<number>(0);
  const [activeStint, setActiveStint] = useState<ActiveStint | null>(null);
  const [stintHistory, setStintHistory] = useState<{driver: number, duration: number, timestamp: Date}[]>([]);
  const [selectedStintIndex, setSelectedStintIndex] = useState<number | null>(null);
  const [hasLoadedFromStorage, setHasLoadedFromStorage] = useState(false);
  // Race parameters the on-screen stint table was built for.
  const planSignatureRef = useRef<string>('');
  /**
   * Record that the current table belongs to `cfg`. A restored table that no
   * longer fits its own config (saved before the schedule maths was fixed)
   * leaves the signature empty, so the effect above rebuilds it once.
   */
  const rememberPlan = (cfg: StintConfig, assignments: StintAssignment[]) => {
    planSignatureRef.current = planFitsConfig(assignments, cfg) ? planSignature(cfg) : '';
  };
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastPitStatusRef = useRef<string>('');

  // Preset management state
  const [availablePresets, setAvailablePresets] = useState<StintPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState<string>('');
  const [showSavePresetDialog, setShowSavePresetDialog] = useState(false);
  const [newPresetName, setNewPresetName] = useState('');
  // Name clash handling: when the typed name matches an existing preset we
  // refuse to create a duplicate and offer to overwrite that one instead.
  const [presetNameError, setPresetNameError] = useState<string | null>(null);
  const [clashingPresetId, setClashingPresetId] = useState<string | null>(null);
  // Auto-save feedback for the selected preset: idle → saving → saved.
  const [presetSaveState, setPresetSaveState] = useState<'idle' | 'saving' | 'saved'>('idle');
  // Renaming the selected preset in place (its plan is untouched).
  const [renamingPreset, setRenamingPreset] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [renameError, setRenameError] = useState<string | null>(null);

  // --- Phase 2.5: cross-device sync ----------------------------------------
  // Mirror the four planner-related fields (config, presets, driverNames,
  // currentDriverIndex) to /api/me/prefs/<track_id>. The localStorage stays
  // as a cache (so we paint the previous state instantly), but the server
  // is now the source of truth across devices.
  //
  // The `hasServerPrefsSynced` flag prevents the state-watching effects below
  // from firing PUTs while we're still hydrating from the server — otherwise
  // every initial setState would echo back to the server and we'd loop.
  const prefsDebouncerRef = useRef<ReturnType<typeof makePrefsDebouncer> | null>(null);
  const [hasServerPrefsSynced, setHasServerPrefsSynced] = useState(false);

  // Only fields the USER changed here are pushed to the server.
  //
  // The persist effects below watch state, and state also changes when we
  // apply a snapshot from the server or when a derived value recomputes. Left
  // unguarded, applying a value pushed by another tab immediately schedules a
  // PUT of that same value, which broadcasts again: two tabs on one account
  // bounce values off each other forever, and a tab that had not yet re-
  // rendered can push its stale copy over a teammate's edit. Comparing values
  // is not enough — state and the snapshot are not always in step within a
  // render — so edits are marked at their source instead.
  const userEditedRef = useRef<Set<string>>(new Set());
  // When each field was last edited here. A snapshot fetched before that
  // moment is stale for the field and must not be applied over the edit.
  const lastLocalEditRef = useRef<Record<string, number>>({});
  const markUserEdit = (...fields: string[]) => {
    const now = Date.now();
    fields.forEach(f => {
      userEditedRef.current.add(f);
      lastLocalEditRef.current[f] = now;
    });
  };
  /** True when the user touched `field` after `since` (epoch ms). */
  const editedSince = (field: string, since: number) =>
    (lastLocalEditRef.current[field] ?? 0) > since;
  /** Schedule a PUT for `field`, but only if the user actually changed it. */
  const schedulePref = (field: string, patch: Partial<UserTrackPrefs>) => {
    if (!userEditedRef.current.has(field)) return;
    userEditedRef.current.delete(field);
    prefsDebouncerRef.current?.schedule(patch);
  };

  useEffect(() => {
    if (trackId === undefined) return;
    // Reset sync state for the new track. Flush any pending PUT for the old.
    prefsDebouncerRef.current?.flush();
    prefsDebouncerRef.current = makePrefsDebouncer(trackId, 500);
    setHasServerPrefsSynced(false);

    let cancelled = false;
    const hydrationStartedAt = Date.now();
    (async () => {
      try {
        const prefs = await fetchUserPrefs(trackId);
        if (cancelled) return;
        // Apply server values when they're meaningful. If server has empties
        // (new account / new track), we keep whatever came from localStorage.
        if (
          prefs.stint_planner_config && Object.keys(prefs.stint_planner_config).length > 0 &&
          !editedSince('stint_planner_config', hydrationStartedAt)
        ) {
          setConfig(prefs.stint_planner_config as unknown as StintConfig);
        }
        if (
          Array.isArray(prefs.driver_names) && prefs.driver_names.length > 0 &&
          !editedSince('driver_names', hydrationStartedAt)
        ) {
          setDriverNames(prefs.driver_names);
        }
        if (typeof prefs.current_driver_index === 'number') {
          setCurrentDriverIndex(prefs.current_driver_index);
        }
        if (
          Array.isArray(prefs.stint_planner_presets) && prefs.stint_planner_presets.length > 0 &&
          !editedSince('stint_planner_presets', hydrationStartedAt)
        ) {
          setAvailablePresets(prefs.stint_planner_presets as unknown as StintPreset[]);
        }
        if (
          Array.isArray(prefs.stint_assignments) && prefs.stint_assignments.length > 0 &&
          !editedSince('stint_assignments', hydrationStartedAt)
        ) {
          const restored = prefs.stint_assignments as unknown as StintAssignment[];
          rememberPlan(
            (prefs.stint_planner_config as unknown as StintConfig) || config,
            restored,
          );
          setStintAssignments(restored);
        }
      } catch (err) {
        console.warn('StintPlanner: failed to fetch prefs', err);
      } finally {
        if (!cancelled) setHasServerPrefsSynced(true);
      }
    })();
    return () => {
      cancelled = true;
      prefsDebouncerRef.current?.flush();
    };
  }, [trackId]);

  // Phase 2.5 live-sync: re-fetch the planner fields when another tab or
  // device writes them, so everyone signed into the account converges.
  //
  // stint_planner_config IS applied here. It used to be skipped because a
  // fetch could land mid preset-selection and revert the just-applied config,
  // but the pending PUT is flushed before the fetch below, and presets now
  // auto-save: leaving config stale would make this tab write its old numbers
  // back over a teammate's edit on the next auto-save.
  useEffect(() => {
    if (trackId === undefined) return;
    const unsubscribe = webSocketService.addPrefsListener(async (event) => {
      if (event.track_id !== trackId) return;
      if (event.updated_at && event.updated_at === getLastSeenUpdatedAt(trackId)) {
        return; // our own write coming back
      }
      // The server emits this ping BEFORE its PUT response returns, so our
      // own write can arrive here before setLastSeenUpdatedAt has recorded
      // it and slip past the dedup above. Anything the user types while the
      // fetch below is in flight would then be overwritten by the snapshot,
      // which is why every apply is guarded on editedSince().
      const fetchStartedAt = Date.now();
      try {
        await prefsDebouncerRef.current?.flush();
        const fresh = await fetchUserPrefs(trackId);
        // Applying a snapshot must not look like a local edit: the flag
        // bounces false → true so the persist effects stay quiet during the
        // batch, and nothing here marks a field as user-edited.
        setHasServerPrefsSynced(false);
        if (
          fresh.stint_planner_config &&
          Object.keys(fresh.stint_planner_config).length > 0 &&
          !editedSince('stint_planner_config', fetchStartedAt)
        ) {
          setConfig(fresh.stint_planner_config as unknown as StintConfig);
        }
        if (
          Array.isArray(fresh.driver_names) && fresh.driver_names.length > 0 &&
          !editedSince('driver_names', fetchStartedAt)
        ) {
          setDriverNames(fresh.driver_names);
        }
        if (
          typeof fresh.current_driver_index === 'number' &&
          !editedSince('current_driver_index', fetchStartedAt)
        ) {
          setCurrentDriverIndex(fresh.current_driver_index);
        }
        if (
          Array.isArray(fresh.stint_planner_presets) &&
          !editedSince('stint_planner_presets', fetchStartedAt)
        ) {
          setAvailablePresets(fresh.stint_planner_presets as unknown as StintPreset[]);
        }
        if (
          Array.isArray(fresh.stint_assignments) &&
          !editedSince('stint_assignments', fetchStartedAt)
        ) {
          const incoming = fresh.stint_assignments as unknown as StintAssignment[];
          rememberPlan(
            (fresh.stint_planner_config as unknown as StintConfig) || config,
            incoming,
          );
          setStintAssignments(incoming);
        }
        setTimeout(() => setHasServerPrefsSynced(true), 0);
      } catch (err) {
        console.warn('StintPlanner: live prefs refresh failed', err);
      }
    });
    return unsubscribe;
  }, [trackId]);

  // Load saved values from localStorage on client-side mount (after SSR)
  useEffect(() => {
    // Only run on client side
    if (typeof window !== 'undefined' && !hasLoadedFromStorage) {
      const savedConfig = loadStintConfig<StintConfig>(defaultConfig);
      const savedDriverNames = loadDriverNames();
      const savedStintAssignments = loadStintAssignments<StintAssignment>();
      const savedDriverIndex = loadCurrentDriverIndex();

      // Apply saved values if they exist
      if (savedConfig) {
        setConfig(savedConfig);
      }
      if (savedDriverNames && savedDriverNames.length > 0) {
        setDriverNames(savedDriverNames);
      }
      if (savedStintAssignments && savedStintAssignments.length > 0) {
        rememberPlan(savedConfig || config, savedStintAssignments);
        setStintAssignments(savedStintAssignments);
      }
      setCurrentDriverIndex(savedDriverIndex);

      setHasLoadedFromStorage(true);
    }
  }, []); // Run only once on mount
  // eslint-disable-next-line react-hooks/exhaustive-deps

  // Load presets when track changes
  useEffect(() => {
    if (typeof window !== 'undefined' && trackId !== undefined) {
      const trackPresets = getTrackPresets(trackId);

      if (trackPresets) {
        setAvailablePresets(trackPresets.presets);

        // Load the active preset for this track
        const activePreset = getActivePreset(trackId);
        if (activePreset) {
          setSelectedPresetId(activePreset.id);
          // Apply the preset config
          setConfig(activePreset.config);

          // Restore the plan the preset carries (names + stint table).
          if (activePreset.driverNames && activePreset.driverNames.length > 0) {
            setDriverNames(activePreset.driverNames);
          }
          if (activePreset.stintAssignments && activePreset.stintAssignments.length > 0) {
            rememberPlan(activePreset.config, activePreset.stintAssignments);
            setStintAssignments(activePreset.stintAssignments);
            return;
          }

          // Legacy preset (config only): rebuild the stint table from it.
          const rebuilt = buildStintTable(activePreset.config);
          rememberPlan(activePreset.config, rebuilt);
          setStintAssignments(rebuilt);
        } else {
          setSelectedPresetId('');
        }
      } else {
        // No presets for this track
        setAvailablePresets([]);
        setSelectedPresetId('');
      }
    }
  }, [trackId]);

  // Pastel colors for drivers (4 opposite colors on color wheel)
  // Vivid livery palette — saturated so blocks read on both themes and sit
  // in the same world as the pit-wall orange/purple (no washed-out pastels).
  const driverColors = useMemo(() => [
    '#E5484D',  // red
    '#F76B15',  // orange
    '#3E63DD',  // blue
    '#30A46C',  // green
    '#8E4EC6',  // purple
    '#00A2C7',  // cyan
    '#D6409F',  // pink
    '#65A30D',  // lime
    '#12A594',  // teal
    '#6366F1',  // indigo
  ], []);

  const getDriverColor = (index: number) => driverColors[index % driverColors.length];

  // Calculate available jokers and long stints
  const availableSpecialStints = useMemo(() => {
    const { numStints, minStintTime, maxStintTime, pitDuration, totalRaceTime } = config;
    
    // Calculate available race time (excluding pit stops)
    const totalPitTime = pitDuration * (numStints - 1);
    const availableRaceTime = totalRaceTime - totalPitTime;
    
    // Calculate base stint time
    const baseStintTime = availableRaceTime / numStints;
    
    // Calculate maximum joker stints (bad kart strategy)
    let maxJokers = 0;
    let jokerNormalTime = baseStintTime;
    
    for (let jokers = numStints; jokers >= 0; jokers--) {
      const normalStints = numStints - jokers;
      
      if (normalStints === 0) {
        // All joker stints
        const totalTime = jokers * minStintTime;
        if (Math.abs(totalTime - availableRaceTime) <= 0.5) {
          maxJokers = jokers;
          jokerNormalTime = 0;
          break;
        }
      } else {
        // Normal stints must compensate for time saved by jokers
        const normalTime = (availableRaceTime - jokers * minStintTime) / normalStints;
        
        // Check if normal stint time is valid (not exceeding max)
        if (normalTime <= maxStintTime) {
          maxJokers = jokers;
          jokerNormalTime = normalTime;
          break;
        }
      }
    }
    
    // Calculate maximum long stints (good kart strategy)
    let maxLongs = 0;
    let longNormalTime = baseStintTime;
    
    for (let longs = numStints; longs >= 0; longs--) {
      const normalStints = numStints - longs;
      
      if (normalStints === 0) {
        // All long stints
        const totalTime = longs * maxStintTime;
        if (Math.abs(totalTime - availableRaceTime) <= 0.5) {
          maxLongs = longs;
          longNormalTime = 0;
          break;
        }
      } else {
        // Normal stints must compensate for extra time used by longs
        const normalTime = (availableRaceTime - longs * maxStintTime) / normalStints;
        
        // Check if normal stint time is valid (not below min)
        if (normalTime >= minStintTime) {
          maxLongs = longs;
          longNormalTime = normalTime;
          break;
        }
      }
    }
    
    return {
      maxJokers: Math.max(0, maxJokers),
      maxLongs: Math.max(0, maxLongs),
      baseStintTime: Math.round(baseStintTime),
      jokerNormalTime: Math.round(jokerNormalTime * 10) / 10,
      longNormalTime: Math.round(longNormalTime * 10) / 10,
      jokerRange: `${minStintTime}-${minStintTime + 5}`,
      longRange: `${maxStintTime - 5}-${maxStintTime}`
    };
  }, [config]);

  // A fresh table for the current config (fills the race exactly).
  const initializeStints = useMemo(() => buildStintTable(config), [config]);

  // Rebuild the stint table when the race it describes changes.
  //
  // This used to fire only when the stint COUNT changed, so setting a race to
  // 358 minutes left the previous schedule untouched and the planner went on
  // planning the old race length. It now watches every parameter the table is
  // built from, via planSignature. Manual per-stint edits survive: they don't
  // change the signature, and handleStintDurationChange compensates within
  // the same total.
  useEffect(() => {
    if (!hasLoadedFromStorage) return;

    const signature = planSignature(config);
    const stale = planSignatureRef.current !== signature;
    const wrongShape = stintAssignments.length === 0 || stintAssignments.length !== config.numStints;
    if (!stale && !wrongShape) return;

    planSignatureRef.current = signature;
    setStintAssignments(initializeStints);
  }, [config, initializeStints, hasLoadedFromStorage, stintAssignments.length]);

  // Update driver names array when number of drivers changes
  useEffect(() => {
    setDriverNames(prevNames => {
      const newNames = [...prevNames];
      while (newNames.length < config.numDrivers) {
        newNames.push(`Driver ${newNames.length + 1}`);
      }
      while (newNames.length > config.numDrivers) {
        newNames.pop();
      }
      return newNames;
    });
  }, [config.numDrivers]);

  // Auto-detect pit stops and manage stint timer
  useEffect(() => {
    if (!myTeam || !teams || !isSimulating) {
      return;
    }

    const myTeamData = teams.find(t => t.Team === myTeam);
    if (!myTeamData) return;

    const currentStatus = myTeamData.Status || '';
    const previousStatus = lastPitStatusRef.current;

    // Detect pit in
    if (currentStatus === 'Pit In' && previousStatus !== 'Pit In' && activeStint && !activeStint.isPitStop) {
      // End current stint
      const duration = Math.round((Date.now() - activeStint.startTime.getTime()) / 60000); // Convert to minutes
      setStintHistory(prev => [...prev, {
        driver: activeStint.driverIndex + 1,
        duration,
        timestamp: new Date()
      }]);
      
      // Start pit stop timer
      setActiveStint({
        ...activeStint,
        isPitStop: true,
        startTime: new Date()
      });
    }
    // Detect pit out
    else if (currentStatus === 'Pit Out' && previousStatus === 'Pit In' && activeStint?.isPitStop) {
      // Start new stint with current driver
      setActiveStint({
        driverIndex: currentDriverIndex,
        startTime: new Date(),
        elapsedTime: 0,
        isPitStop: false
      });
    }
    // Detect race start (green flag)
    else if (!activeStint && sessionInfo?.light === 'green' && currentStatus !== 'Pit In') {
      // Start first stint
      setActiveStint({
        driverIndex: currentDriverIndex,
        startTime: new Date(),
        elapsedTime: 0,
        isPitStop: false
      });
    }

    lastPitStatusRef.current = currentStatus;
  }, [myTeam, teams, isSimulating, activeStint, currentDriverIndex, sessionInfo]);

  // Update stint timer
  useEffect(() => {
    if (activeStint && !activeStint.isPitStop) {
      intervalRef.current = setInterval(() => {
        setActiveStint(prev => {
          if (!prev) return null;
          return {
            ...prev,
            elapsedTime: Math.round((Date.now() - prev.startTime.getTime()) / 1000) // Seconds
          };
        });
      }, 1000);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [activeStint]);

  // Persist stint configuration to localStorage + (phase 2.5) to server prefs
  useEffect(() => {
    saveStintConfig(config);
    if (hasServerPrefsSynced) {
      schedulePref('stint_planner_config',
        { stint_planner_config: config as unknown as Record<string, unknown> });
    }
  }, [config, hasServerPrefsSynced]);

  // Persist driver names to localStorage + server
  useEffect(() => {
    saveDriverNames(driverNames);
    if (hasServerPrefsSynced) {
      schedulePref('driver_names', { driver_names: driverNames });
    }
  }, [driverNames, hasServerPrefsSynced]);

  // Persist stint assignments to localStorage + server. Server-side is needed
  // because per-stint manual edits (driver swap, duration tweak, joker flag)
  // would otherwise be lost on a device switch.
  useEffect(() => {
    saveStintAssignments(stintAssignments);
    if (hasServerPrefsSynced) {
      schedulePref('stint_assignments', {
        stint_assignments: stintAssignments as unknown as Array<Record<string, unknown>>,
      });
    }
  }, [stintAssignments, hasServerPrefsSynced]);

  // Persist current driver index to localStorage + server
  useEffect(() => {
    saveCurrentDriverIndex(currentDriverIndex);
    if (hasServerPrefsSynced) {
      schedulePref('current_driver_index',
        { current_driver_index: currentDriverIndex });
    }
  }, [currentDriverIndex, hasServerPrefsSynced]);

  // Phase 2.5: presets are also kept in localStorage today (via the
  // saveTrackPreset / deleteTrackPreset helpers). Mirror them to the server
  // whenever the in-memory list changes so they survive a device switch.
  useEffect(() => {
    if (hasServerPrefsSynced && trackId !== undefined) {
      schedulePref('stint_planner_presets', {
        stint_planner_presets: availablePresets as unknown as Array<Record<string, unknown>>,
      });
    }
  }, [availablePresets, hasServerPrefsSynced, trackId]);

  const driverStats = useMemo(() => {
    const stats: DriverStats[] = [];
    
    for (let driver = 1; driver <= config.numDrivers; driver++) {
      const driverStints = stintAssignments.filter(s => s.driver === driver);
      stats.push({
        driver,
        name: driverNames[driver - 1],
        totalTime: driverStints.reduce((sum, s) => sum + s.duration, 0),
        numStints: driverStints.length,
        jokerStints: driverStints.filter(s => s.isJoker).length,
        longStints: driverStints.filter(s => s.isLong).length,
      });
    }
    
    return stats;
  }, [stintAssignments, config.numDrivers, driverNames]);

  const formatTime = (minutes: number): string => {
    // Round to whole minutes so float-arithmetic drift (e.g. accumulating
    // pitDuration=2.5 across stints) doesn't surface as 30.000000000004m.
    const m = Math.round(minutes);
    const hours = Math.floor(m / 60);
    const mins = m % 60;
    return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
  };

  const formatSeconds = (seconds: number): string => {
    const total = Math.round(seconds);
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handleConfigChange = (field: keyof StintConfig, value: number) => {
    // Changing the config also rebuilds the stint table and can resize the
    // driver list, so all three become the user's to publish.
    markUserEdit('stint_planner_config', 'stint_assignments', 'driver_names');
    setConfig(prev => ({ ...prev, [field]: value }));
  };

  const handleDriverNameChange = (index: number, name: string) => {
    markUserEdit('driver_names');
    const newNames = [...driverNames];
    newNames[index] = name;
    setDriverNames(newNames);
  };

  const handleStintDurationChange = (stintIndex: number, duration: number) => {
    markUserEdit('stint_assignments');
    // Functional update: the drag fires this many times per second, so each
    // call must operate on the latest committed state, not the closure it was
    // created from (stale state here under/over-compensates the neighbours).
    setStintAssignments(prev => {
      const newAssignments = [...prev];
      const oldDuration = newAssignments[stintIndex]?.duration ?? 0;
      const timeDifference = duration - oldDuration;

      // Update the changed stint (new object so `prev` is never mutated).
      newAssignments[stintIndex] = {
        ...newAssignments[stintIndex],
        duration,
        isJoker: duration > 0 && duration >= config.minStintTime && duration <= config.minStintTime + 5,
        isLong: duration >= config.maxStintTime - 5 && duration <= config.maxStintTime,
      };

      // Compensate the following stints so the total still fits the race.
      const followingStints = newAssignments.filter((_, idx) => idx > stintIndex && newAssignments[idx].duration > 0);
      if (followingStints.length > 0 && timeDifference !== 0) {
        const compensationPerStint = -timeDifference / followingStints.length;
        newAssignments.forEach((stint, idx) => {
          if (idx > stintIndex && stint.duration > 0) {
            const newDuration = stint.duration + compensationPerStint;
            if (newDuration >= config.minStintTime && newDuration <= config.maxStintTime) {
              newAssignments[idx] = {
                ...stint,
                duration: Math.round(newDuration * 10) / 10,
                isJoker: newDuration >= config.minStintTime && newDuration <= config.minStintTime + 5,
                isLong: newDuration >= config.maxStintTime - 5 && newDuration <= config.maxStintTime,
              };
            }
          }
        });
      }

      // Recalculate start/end times.
      let currentTime = 0;
      for (let i = 0; i < newAssignments.length; i++) {
        newAssignments[i] = { ...newAssignments[i], startTime: currentTime };
        currentTime += newAssignments[i].duration;
        newAssignments[i] = { ...newAssignments[i], endTime: currentTime };
        if (i < newAssignments.length - 1) {
          currentTime += config.pitDuration;
        }
      }

      return newAssignments;
    });
  };

  const handleStintDriverChange = (stintIndex: number, driverNum: number) => {
    markUserEdit('stint_assignments');
    const newAssignments = [...stintAssignments];
    newAssignments[stintIndex].driver = driverNum;
    setStintAssignments(newAssignments);
  };

  // Preset handlers
  const handlePresetSelect = (presetId: string) => {
    markUserEdit('stint_planner_config', 'driver_names', 'stint_assignments');
    setSelectedPresetId(presetId);
    setPresetSaveState('idle');
    if (presetId && trackId !== undefined) {
      const preset = availablePresets.find(p => p.id === presetId);
      if (preset) {
        setConfig(preset.config);
        setActivePreset(trackId, presetId);

        // A preset carries its driver line-up and stint table too. Presets
        // saved before those existed fall through to the rebuild below.
        if (preset.driverNames && preset.driverNames.length > 0) {
          setDriverNames(preset.driverNames);
        }
        if (preset.stintAssignments && preset.stintAssignments.length > 0) {
          rememberPlan(preset.config, preset.stintAssignments);
          setStintAssignments(preset.stintAssignments);
          return;
        }

        // Legacy preset (config only): rebuild the stint table from it.
        const rebuilt = buildStintTable(preset.config);
        rememberPlan(preset.config, rebuilt);
        setStintAssignments(rebuilt);
      }
    }
  };

  /** The plan as it stands in the form — what a preset stores. */
  const currentPlan = () => ({
    config: { ...config },
    driverNames: [...driverNames],
    stintAssignments: stintAssignments.map(a => ({ ...a })),
  });

  const closeSaveDialog = () => {
    setShowSavePresetDialog(false);
    setNewPresetName('');
    setPresetNameError(null);
    setClashingPresetId(null);
  };

  /**
   * Write the current config into an existing preset, keeping its id and name.
   * This is the "overwrite" path — used by the Update button and by accepting
   * an overwrite when a typed name clashes.
   */
  const overwritePreset = (presetId: string) => {
    if (trackId === undefined || !trackName) return;
    const target = availablePresets.find(p => p.id === presetId);
    if (!target) return;

    const updated: StintPreset = { ...target, ...currentPlan() };
    markUserEdit('stint_planner_presets');
    saveTrackPreset(trackId, trackName, updated);
    setAvailablePresets(prev => prev.map(p => (p.id === presetId ? updated : p)));
    setSelectedPresetId(presetId);
    setActivePreset(trackId, presetId);
    setPresetSaveState('saved');
    closeSaveDialog();
  };

  const handleSavePreset = () => {
    const name = newPresetName.trim();
    if (!name || trackId === undefined || !trackName) return;

    // Preset names are unique per track. On a clash, don't create a second
    // preset with the same label — offer to overwrite the existing one.
    const clash = findPresetByName(availablePresets, name);
    if (clash) {
      setPresetNameError(`"${clash.name}" already exists for this track.`);
      setClashingPresetId(clash.id);
      return;
    }

    const presetId = `preset_${Date.now()}`;
    const newPreset: StintPreset = {
      id: presetId,
      name,
      ...currentPlan(),
    };

    markUserEdit('stint_planner_presets');
    saveTrackPreset(trackId, trackName, newPreset);
    setAvailablePresets(prev => [...prev, newPreset]);
    setSelectedPresetId(presetId);
    setActivePreset(trackId, presetId);
    setPresetSaveState('saved');
    closeSaveDialog();
  };

  const startRenamePreset = () => {
    if (!selectedPreset) return;
    setRenameValue(selectedPreset.name);
    setRenameError(null);
    setRenamingPreset(true);
  };

  const cancelRenamePreset = () => {
    setRenamingPreset(false);
    setRenameValue('');
    setRenameError(null);
  };

  /**
   * Rename the selected preset in place. Only the label changes — the plan
   * stays as it is — and the id is kept, so this updates the preset instead
   * of creating a second one under the new name.
   */
  const handleRenamePreset = () => {
    const name = renameValue.trim();
    if (!name || !selectedPreset || trackId === undefined || !trackName) return;

    // Names stay unique per track. Excluding this preset lets the user fix
    // the capitalisation or spacing of its own name.
    const clash = findPresetByName(availablePresets, name, selectedPreset.id);
    if (clash) {
      setRenameError(`"${clash.name}" already exists for this track.`);
      return;
    }

    const renamed: StintPreset = { ...selectedPreset, name };
    markUserEdit('stint_planner_presets');
    saveTrackPreset(trackId, trackName, renamed);
    setAvailablePresets(prev => prev.map(p => (p.id === renamed.id ? renamed : p)));
    setPresetSaveState('saved');
    cancelRenamePreset();
  };

  const handleDeletePreset = () => {
    if (!selectedPresetId || trackId === undefined) return;

    const target = availablePresets.find(p => p.id === selectedPresetId);
    if (!confirm(`Delete the preset "${target?.name ?? ''}"? This cannot be undone.`)) return;

    markUserEdit('stint_planner_presets');
    deleteTrackPreset(trackId, selectedPresetId);
    const updatedPresets = availablePresets.filter(p => p.id !== selectedPresetId);
    setAvailablePresets(updatedPresets);
    setSelectedPresetId(updatedPresets[0]?.id || '');
  };

  // How long the current table actually occupies, against the race length.
  const currentSpan = plannedSpan(stintAssignments, config);
  const scheduleFits = stintAssignments.length === 0 || Math.abs(currentSpan - config.totalRaceTime) < 0.05;

  const selectedPreset = availablePresets.find(p => p.id === selectedPresetId) || null;
  // The form has drifted from the stored preset, so auto-save has work to do.
  const isPresetDirty =
    !!selectedPreset &&
    !presetMatchesPlan(selectedPreset, { config, driverNames, stintAssignments });

  /**
   * Auto-save. With a preset selected, every edit to the config, the driver
   * names or the stint table is written into that preset after a short pause
   * — no save button. The preset list then mirrors to /api/me/prefs, so
   * everyone signed into the account converges on the same plan.
   *
   * Guarded on hasServerPrefsSynced so hydration (local, server, or a push
   * from another device) never echoes straight back as a write.
   */
  useEffect(() => {
    if (!isPresetDirty || !hasServerPrefsSynced) return;
    if (trackId === undefined || !trackName || !selectedPresetId) return;

    setPresetSaveState('saving');
    const timer = setTimeout(() => overwritePreset(selectedPresetId), 700);
    return () => clearTimeout(timer);
    // overwritePreset closes over the current plan; re-created every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPresetDirty, hasServerPrefsSynced, trackId, trackName, selectedPresetId,
      config, driverNames, stintAssignments]);

  // Let the "Saved" confirmation fade back to idle.
  useEffect(() => {
    if (presetSaveState !== 'saved') return;
    const timer = setTimeout(() => setPresetSaveState('idle'), 2500);
    return () => clearTimeout(timer);
  }, [presetSaveState]);

  // Drag-to-resize state for timeline blocks (pointer-captured on the handle).
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const resizeRef = useRef<{ index: number; startX: number; startDuration: number; minutesPerPixel: number } | null>(null);

  const onResizeStart = (e: React.PointerEvent, index: number) => {
    e.preventDefault();
    e.stopPropagation();
    const block = (e.currentTarget as HTMLElement).parentElement;
    const startDuration = stintAssignments[index]?.duration ?? 0;
    resizeRef.current = {
      index,
      startX: e.clientX,
      startDuration,
      minutesPerPixel: block && block.offsetWidth > 0 ? startDuration / block.offsetWidth : 0,
    };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onResizeMove = (e: React.PointerEvent) => {
    const r = resizeRef.current;
    if (!r || r.minutesPerPixel === 0) return;
    const delta = (e.clientX - r.startX) * r.minutesPerPixel;
    const next = r.startDuration + delta;
    const clamped = Math.max(1, Math.min(config.maxStintTime, Math.round(next * 10) / 10));
    handleStintDurationChange(r.index, clamped);
  };

  const onResizeEnd = () => {
    resizeRef.current = null;
  };

  return (
    <div className="p-6 bg-surface text-ink">
      <h2 className="text-2xl font-cond font-bold tracking-wide mb-6">Stint Planner</h2>

      {/* Preset Selector */}
      {trackName && (
        <div className={`mb-6 p-4 rounded-none border ${isDarkMode ? 'bg-surface-2 border-line' : 'bg-info/15 border-line'}`}>
          <div className="flex items-center gap-3 flex-wrap">
            <label htmlFor="stint-preset-select" className={`text-sm font-medium text-ink`}>
              {trackName} presets:
            </label>

            {renamingPreset ? (
              <input
                type="text"
                value={renameValue}
                aria-label="Preset name"
                aria-invalid={!!renameError}
                autoFocus
                onChange={(e) => {
                  setRenameValue(e.target.value);
                  setRenameError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleRenamePreset();
                  if (e.key === 'Escape') cancelRenamePreset();
                }}
                className={`flex-1 min-w-[200px] p-2 rounded-none border ${
                  renameError
                    ? 'border-alarm'
                    : 'border-line'
                } bg-surface text-ink`}
              />
            ) : (
              <select
                id="stint-preset-select"
                value={selectedPresetId}
                onChange={(e) => handlePresetSelect(e.target.value)}
                className="flex-1 min-w-[200px] p-2 rounded-none border bg-surface border-line text-ink"
                disabled={availablePresets.length === 0}
              >
                <option value="">-- No preset selected --</option>
                {availablePresets.map(preset => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
            )}

            {renamingPreset ? (
              <>
                <button
                  onClick={handleRenamePreset}
                  disabled={!renameValue.trim()}
                  className={`px-4 py-2 rounded-none ${
                    !renameValue.trim()
                      ? 'bg-line cursor-not-allowed text-ink'
                      : isDarkMode
                      ? 'bg-live hover:bg-live text-white'
                      : 'bg-live hover:bg-live text-white'
                  }`}
                >
                  Save name
                </button>
                <button
                  onClick={cancelRenamePreset}
                  className={`px-4 py-2 rounded-none ${
                    isDarkMode ? 'bg-line hover:bg-surface-2 text-ink' : 'bg-line hover:bg-line text-ink'
                  }`}
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                {selectedPreset && (
                  <button
                    onClick={startRenamePreset}
                    title={`Rename "${selectedPreset.name}" without creating a second preset`}
                    className={`px-4 py-2 rounded-none ${
                      isDarkMode ? 'bg-line hover:bg-surface-2 text-ink' : 'bg-line hover:bg-line text-ink'
                    }`}
                  >
                    Rename
                  </button>
                )}

                <button
                  onClick={() => (showSavePresetDialog ? closeSaveDialog() : setShowSavePresetDialog(true))}
                  className={`px-4 py-2 rounded-none ${
                    'bg-info hover:bg-info text-white'
                  }`}
                >
                  Save as new
                </button>

                {selectedPresetId && (
                  <button
                    onClick={handleDeletePreset}
                    className={`px-4 py-2 rounded-none ${
                      'bg-alarm hover:bg-alarm text-white'
                    }`}
                  >
                    Delete
                  </button>
                )}
              </>
            )}
          </div>

          {renameError && (
            <div role="alert" className={`mt-2 text-xs text-alarm`}>
              {renameError} Pick another name.
            </div>
          )}

          {/* Auto-save status for the selected preset. */}
          {selectedPreset && (
            <div
              role="status"
              className={`mt-2 text-xs ${
                presetSaveState === 'saving' || isPresetDirty
                  ? 'text-accent'
                  : presetSaveState === 'saved'
                  ? 'text-live'
                  : 'text-muted'
              }`}
            >
              {presetSaveState === 'saving' || isPresetDirty
                ? `Saving to "${selectedPreset.name}"…`
                : presetSaveState === 'saved'
                ? `Saved to "${selectedPreset.name}".`
                : `Changes save automatically to "${selectedPreset.name}" for everyone on this account.`}
            </div>
          )}

          {/* Save Preset Dialog */}
          {showSavePresetDialog && (
            <div className="mt-4 flex flex-col gap-2">
              <div className="flex items-center gap-3">
                <input
                  type="text"
                  value={newPresetName}
                  onChange={(e) => {
                    setNewPresetName(e.target.value);
                    setPresetNameError(null);
                    setClashingPresetId(null);
                  }}
                  placeholder="Preset name (e.g., 6 Hour Race)"
                  aria-label="New preset name"
                  aria-invalid={!!presetNameError}
                  className={`flex-1 p-2 rounded-none border ${
                    presetNameError
                      ? 'border-alarm'
                      : 'border-line'
                  } bg-surface text-ink`}
                  onKeyDown={(e) => e.key === 'Enter' && handleSavePreset()}
                />
                <button
                  onClick={handleSavePreset}
                  disabled={!newPresetName.trim()}
                  className={`px-4 py-2 rounded-none ${
                    !newPresetName.trim()
                      ? 'bg-line cursor-not-allowed text-ink'
                      : isDarkMode
                      ? 'bg-live hover:bg-live text-white'
                      : 'bg-live hover:bg-live text-white'
                  }`}
                >
                  Save
                </button>
                <button
                  onClick={closeSaveDialog}
                  className={`px-4 py-2 rounded-none ${
                    isDarkMode ? 'bg-line hover:bg-surface-2 text-ink' : 'bg-line hover:bg-line text-ink'
                  }`}
                >
                  Cancel
                </button>
              </div>

              {/* Name clash: names are unique per track, so offer the overwrite. */}
              {presetNameError && (
                <div role="alert" className={`flex items-center gap-3 flex-wrap text-xs text-alarm`}>
                  <span>{presetNameError}</span>
                  {clashingPresetId && (
                    <button
                      onClick={() => overwritePreset(clashingPresetId)}
                      className={`px-2 py-1 rounded-none font-semibold ${
                        'bg-accent hover:bg-accent text-white'
                      }`}
                    >
                      Overwrite it
                    </button>
                  )}
                  <span className={'text-muted'}>or pick another name.</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Active Stint Timer */}
      {activeStint && (
        <div 
          className={`mb-6 p-4 rounded-none border-2 border-live`}
          style={{
            backgroundColor: getDriverColor(activeStint.driverIndex),
            color: '#fff'
          }}
        >
          <h3 className="text-lg font-cond font-bold tracking-wide mb-2">Active Stint</h3>
          <div className="flex items-center gap-4">
            <span className="text-xl font-bold">
              {driverNames[activeStint.driverIndex]} - {formatSeconds(activeStint.elapsedTime)}
            </span>
            {activeStint.isPitStop && <span className="text-sm">(In Pit)</span>}
          </div>
        </div>
      )}

      {/* Stint timeline — the schedule at a glance. */}
      <div className="mb-6">
        <div className="flex items-baseline justify-between mb-2">
          <h3 className="font-cond font-bold text-lg tracking-wide">Schedule</h3>
          <span className="text-xs text-muted">{stintAssignments.length} stints · {formatTime(currentSpan)}</span>
        </div>
        <div ref={timelineRef} className="flex items-stretch h-16 w-full overflow-hidden rounded-none border border-line bg-canvas">
          {stintAssignments.map((a, i) => (
            <React.Fragment key={i}>
              {i > 0 && (
                <div className="shrink-0 bg-canvas border-x border-line/40" style={{ flexBasis: 12 }} title={`Pit stop ${i}`} aria-hidden />
              )}
              <div
                role="button"
                tabIndex={0}
                onClick={() => setSelectedStintIndex(i)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedStintIndex(i); } }}
                title={`Stint ${a.stint}: ${driverNames[a.driver - 1]}, ${a.duration} min — drag the right edge to resize`}
                style={{ flexGrow: Math.max(a.duration, 0.5), flexBasis: 0, backgroundColor: getDriverColor(a.driver - 1), color: '#fff' }}
                className={`relative flex flex-col items-center justify-center min-w-0 overflow-hidden cursor-pointer select-none hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                  selectedStintIndex === i ? 'ring-2 ring-accent z-10' : ''
                }`}
              >
                <span className="text-[10px] font-bold leading-none opacity-80">S{a.stint}</span>
                <span className="text-[11px] font-semibold leading-tight truncate max-w-full px-1">{driverNames[a.driver - 1]}</span>
                <span className="text-[10px] leading-none opacity-70">{a.duration}m</span>
                <span
                  role="separator"
                  aria-orientation="vertical"
                  aria-label={`Resize stint ${a.stint}`}
                  title="Drag to resize"
                  onClick={(e) => e.stopPropagation()}
                  onPointerDown={(e) => onResizeStart(e, i)}
                  onPointerMove={onResizeMove}
                  onPointerUp={onResizeEnd}
                  onPointerCancel={onResizeEnd}
                  className="absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize touch-none hover:bg-black/25 focus:outline-none"
                />
              </div>
            </React.Fragment>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span className="inline-flex items-center gap-1.5"><span className="w-3 h-3 bg-accent/40 border border-line" /> Joker ({config.minStintTime}–{config.minStintTime + 5}m)</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-3 h-3 bg-info/40 border border-line" /> Long ({config.maxStintTime - 5}–{config.maxStintTime}m)</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-2 bg-canvas border-x border-line/40" /> Pit</span>
        </div>
      </div>

      {/* Selected stint editor */}
      {selectedStintIndex !== null && stintAssignments[selectedStintIndex] && (
        <div className="mb-6 p-3 rounded-none border border-line bg-surface-2 flex items-center gap-3 flex-wrap">
          <span className="font-cond font-bold text-lg shrink-0">Stint {stintAssignments[selectedStintIndex].stint}</span>
          <label className="flex items-center gap-2 text-sm">
            Driver
            <select
              value={stintAssignments[selectedStintIndex].driver}
              onChange={(e) => handleStintDriverChange(selectedStintIndex, parseInt(e.target.value))}
              className="p-2 rounded-none border border-line bg-surface text-ink"
              style={{ backgroundColor: getDriverColor(stintAssignments[selectedStintIndex].driver - 1) }}
            >
              {driverNames.map((name, di) => (
                <option key={di} value={di + 1} style={{ backgroundColor: getDriverColor(di) }}>{name}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            Duration
            <input
              type="number"
              min="1"
              max="120"
              step="0.1"
              value={stintAssignments[selectedStintIndex].duration}
              onChange={(e) => handleStintDurationChange(selectedStintIndex, parseFloat(e.target.value) || 0)}
              className="w-24 p-2 rounded-none border border-line bg-surface text-ink text-center"
            />
          </label>
          <span className={`text-sm font-semibold ${stintAssignments[selectedStintIndex].isJoker ? 'text-accent' : stintAssignments[selectedStintIndex].isLong ? 'text-info' : 'text-muted'}`}>
            {stintAssignments[selectedStintIndex].isJoker ? 'JOKER' : stintAssignments[selectedStintIndex].isLong ? 'LONG' : 'Normal'}
          </span>
          <span className="text-sm text-muted ml-auto tabular">
            {formatTime(stintAssignments[selectedStintIndex].startTime)} – {formatTime(stintAssignments[selectedStintIndex].endTime)}
          </span>
        </div>
      )}

      <details className="mb-6 group">
        <summary className="cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden flex items-center gap-2 font-cond font-bold text-lg tracking-wide text-ink hover:text-accent transition-colors">
          <svg className="w-4 h-4 text-muted group-open:rotate-90 transition-transform" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
          Race Setup
        </summary>
        <div className="mt-3 space-y-4">

      {/* Current Driver Selection */}
      <div className="mb-6">
        <label className={`block text-sm font-medium mb-1 text-ink`}>
          Current Driver
        </label>
        <select
          value={currentDriverIndex}
          onChange={(e) => {
            markUserEdit('current_driver_index');
            setCurrentDriverIndex(parseInt(e.target.value));
          }}
          className={`w-full md:w-64 p-2 rounded-none border ${
            'border-line'
          }`}
          style={{
            backgroundColor: getDriverColor(currentDriverIndex),
            color: '#fff'
          }}
        >
          {driverNames.map((name, index) => (
            <option 
              key={index} 
              value={index}
              style={{
                backgroundColor: getDriverColor(index),
                color: '#fff'
              }}
            >
              {name}
            </option>
          ))}
        </select>
      </div>
      
      {/* Configuration Form */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        <div>
          <label htmlFor="stint-numStints" className={`block text-sm font-medium mb-1 text-ink`}>
            Number of Stints
          </label>
          <input
            id="stint-numStints"
            type="number"
            min="1"
            max="20"
            value={config.numStints}
            onChange={(e) => handleConfigChange('numStints', parseInt(e.target.value) || 1)}
            className={`w-full p-2 rounded-none border ${
              isDarkMode ? 'bg-surface-2 border-line' : 'bg-surface border-line'
            }`}
          />
        </div>

        <div>
          <label htmlFor="stint-minStintTime" className={`block text-sm font-medium mb-1 text-ink`}>
            Min Stint Time (minutes)
          </label>
          <input
            id="stint-minStintTime"
            type="number"
            min="1"
            max="120"
            value={config.minStintTime}
            onChange={(e) => handleConfigChange('minStintTime', parseInt(e.target.value) || 1)}
            className={`w-full p-2 rounded-none border ${
              isDarkMode ? 'bg-surface-2 border-line' : 'bg-surface border-line'
            }`}
          />
        </div>

        <div>
          <label htmlFor="stint-maxStintTime" className={`block text-sm font-medium mb-1 text-ink`}>
            Max Stint Time (minutes)
          </label>
          <input
            id="stint-maxStintTime"
            type="number"
            min="1"
            max="120"
            value={config.maxStintTime}
            onChange={(e) => handleConfigChange('maxStintTime', parseInt(e.target.value) || 1)}
            className={`w-full p-2 rounded-none border ${
              isDarkMode ? 'bg-surface-2 border-line' : 'bg-surface border-line'
            }`}
          />
        </div>

        <div>
          <label htmlFor="stint-pitDuration" className={`block text-sm font-medium mb-1 text-ink`}>
            Pit Duration (minutes)
          </label>
          <input
            id="stint-pitDuration"
            type="number"
            min="0.1"
            max="30"
            step="0.1"
            value={config.pitDuration}
            onChange={(e) => handleConfigChange('pitDuration', parseFloat(e.target.value) || 1)}
            className={`w-full p-2 rounded-none border ${
              isDarkMode ? 'bg-surface-2 border-line' : 'bg-surface border-line'
            }`}
          />
        </div>

        <div>
          <label htmlFor="stint-numDrivers" className={`block text-sm font-medium mb-1 text-ink`}>
            Number of Drivers
          </label>
          <input
            id="stint-numDrivers"
            type="number"
            min="1"
            max="10"
            value={config.numDrivers}
            onChange={(e) => handleConfigChange('numDrivers', parseInt(e.target.value) || 1)}
            className={`w-full p-2 rounded-none border ${
              isDarkMode ? 'bg-surface-2 border-line' : 'bg-surface border-line'
            }`}
          />
        </div>

        <div>
          <label htmlFor="stint-totalRaceTime" className={`block text-sm font-medium mb-1 text-ink`}>
            Total Race Time (minutes)
          </label>
          <input
            id="stint-totalRaceTime"
            type="number"
            min="30"
            max="1440"
            value={config.totalRaceTime}
            onChange={(e) => handleConfigChange('totalRaceTime', parseInt(e.target.value) || 30)}
            className={`w-full p-2 rounded-none border ${
              isDarkMode ? 'bg-surface-2 border-line' : 'bg-surface border-line'
            }`}
          />
        </div>
      </div>
        </div>
      </details>

      {/* Schedule summary — makes the plan/race mismatch visible rather than
          silent, and spells out stints vs pit stops. */}
      <div
        role="status"
        className={`mb-6 p-3 rounded-none text-sm flex flex-wrap items-center gap-x-6 gap-y-1 ${
          scheduleFits
            ? 'bg-surface-2'
            : 'bg-accent/15 border border-accent'
        }`}
      >
        <span>
          <span className="font-semibold">{config.numStints}</span> stints
          {' · '}
          <span className="font-semibold">{Math.max(0, config.numStints - 1)}</span> pit stops
        </span>
        <span>
          Driving <span className="font-semibold">{formatTime(drivingTime(config))}</span>
          {' · '}
          in pits <span className="font-semibold">{formatTime(config.pitDuration * Math.max(0, config.numStints - 1))}</span>
        </span>
        <span className={scheduleFits ? '' : 'text-accent'}>
          Planned <span className="font-semibold">{formatTime(currentSpan)}</span> of{' '}
          <span className="font-semibold">{formatTime(config.totalRaceTime)}</span>
          {!scheduleFits && (
            <span className="ml-1">
              ({currentSpan > config.totalRaceTime ? 'over' : 'short'} by {formatTime(Math.abs(currentSpan - config.totalRaceTime))})
            </span>
          )}
        </span>
      </div>

      {/* Available Special Stints (collapsed reference) */}
      <details className="mb-6 group">
        <summary className="cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden flex items-center gap-2 font-cond font-bold text-lg tracking-wide text-ink hover:text-accent transition-colors">
          <svg className="w-4 h-4 text-muted group-open:rotate-90 transition-transform" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
          Available Special Stints
        </summary>
        <div className="mt-3 p-4 rounded-none bg-surface-2">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <span className="font-medium">Max Joker Stints: </span>
              <span className="text-xl font-bold">{availableSpecialStints.maxJokers}</span>
            </div>
            <div>
              <span className="font-medium">Max Long Stints: </span>
              <span className="text-xl font-bold">{availableSpecialStints.maxLongs}</span>
            </div>
            <div>
              <span className="font-medium">Base Stint Time: </span>
              <span className="text-xl font-bold">{availableSpecialStints.baseStintTime}m</span>
            </div>
          </div>
          <div className="mt-2 text-sm opacity-75">
            Note: Time differences are automatically compensated across other stints
          </div>
        </div>
      </details>

      {/* Driver Names (core setup) */}
      <details className="mb-6 group">
        <summary className="cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden flex items-center gap-2 font-cond font-bold text-lg tracking-wide text-ink hover:text-accent transition-colors">
          <svg className="w-4 h-4 text-muted group-open:rotate-90 transition-transform" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
          Driver Names
        </summary>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {driverNames.map((name, index) => (
            <div key={index}>
              <label htmlFor={`stint-driver-name-${index}`} className={`block text-sm font-medium mb-1 text-ink`}>
                Driver {index + 1}
              </label>
              <input
                id={`stint-driver-name-${index}`}
                type="text"
                value={name}
                onChange={(e) => handleDriverNameChange(index, e.target.value)}
                className={`w-full p-2 rounded-none border transition-colors ${
                  'border-line'
                }`}
                style={{
                  backgroundColor: getDriverColor(index),
                  color: '#fff'
                }}
              />
            </div>
          ))}
        </div>
      </details>

      {/* Driver Statistics (collapsed reference) */}
      <details className="mb-6 group">
        <summary className="cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden flex items-center gap-2 font-cond font-bold text-lg tracking-wide text-ink hover:text-accent transition-colors">
          <svg className="w-4 h-4 text-muted group-open:rotate-90 transition-transform" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
          Driver Statistics
        </summary>
        <div className="mt-3 p-4 rounded-none bg-surface-2">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {driverStats.map((stat, index) => (
            <div 
              key={stat.driver} 
              className={`p-3 rounded-none border transition-colors ${
                'border-line'
              }`}
              style={{
                backgroundColor: getDriverColor(index),
                color: '#fff'
              }}
            >
              <h4 className="font-medium mb-2">{stat.name}</h4>
              <div className="text-sm space-y-1">
                <div>Total Time: {formatTime(stat.totalTime)}</div>
                <div>Stints: {stat.numStints}</div>
                <div>Jokers: {stat.jokerStints}</div>
                <div>Long: {stat.longStints}</div>
              </div>
            </div>
          ))}
        </div>
        </div>
      </details>

      {/* Stint History */}
      {stintHistory.length > 0 && (
        <div className="mt-6">
          <h3 className="text-lg font-cond font-bold tracking-wide mb-3">Completed Stints</h3>
          <div className="space-y-2">
            {stintHistory.map((stint, index) => (
              <div key={index} className={`p-2 rounded-none bg-surface-2`}>
                {driverNames[stint.driver - 1]} - {stint.duration} minutes
                <span className="text-sm ml-2 opacity-70">
                  ({stint.timestamp.toLocaleTimeString()})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
};

export default StintPlanner;