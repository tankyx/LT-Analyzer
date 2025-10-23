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
  getActivePreset
} from '../../utils/persistence';

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

interface StintConfig {
  numStints: number;
  minStintTime: number;
  maxStintTime: number;
  pitDuration: number;
  numDrivers: number;
  totalRaceTime: number;
}

interface StintAssignment {
  driver: number;
  stint: number;
  duration: number;
  isJoker: boolean;
  isLong: boolean;
  startTime: number;
  endTime: number;
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
  const [hasLoadedFromStorage, setHasLoadedFromStorage] = useState(false);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastPitStatusRef = useRef<string>('');

  // Preset management state
  const [availablePresets, setAvailablePresets] = useState<StintPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState<string>('');
  const [showSavePresetDialog, setShowSavePresetDialog] = useState(false);
  const [newPresetName, setNewPresetName] = useState('');

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

          // Reinitialize stints based on preset config
          const assignments: StintAssignment[] = [];
          let currentTime = 0;
          const totalPitTime = activePreset.config.pitDuration * (activePreset.config.numStints - 1);
          const availableRaceTime = activePreset.config.totalRaceTime - totalPitTime;
          const baseStintTime = Math.round(availableRaceTime / activePreset.config.numStints);

          for (let stint = 1; stint <= activePreset.config.numStints; stint++) {
            const driverIndex = (stint - 1) % activePreset.config.numDrivers;

            assignments.push({
              driver: driverIndex + 1,
              stint,
              duration: baseStintTime,
              isJoker: false,
              isLong: false,
              startTime: currentTime,
              endTime: currentTime + baseStintTime,
            });

            currentTime += baseStintTime;
            if (stint < activePreset.config.numStints) {
              currentTime += activePreset.config.pitDuration;
            }
          }

          setStintAssignments(assignments);
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
  const driverColors = useMemo(() => {
    const colors = [
      { light: 'rgb(255, 230, 230)', dark: 'rgb(60, 30, 30)' },    // Pastel Red
      { light: 'rgb(230, 255, 230)', dark: 'rgb(30, 60, 30)' },    // Pastel Green
      { light: 'rgb(230, 240, 255)', dark: 'rgb(30, 40, 60)' },    // Pastel Blue
      { light: 'rgb(255, 245, 230)', dark: 'rgb(60, 50, 30)' },    // Pastel Orange
      { light: 'rgb(255, 230, 255)', dark: 'rgb(60, 30, 60)' },    // Pastel Purple
      { light: 'rgb(230, 255, 255)', dark: 'rgb(30, 60, 60)' },    // Pastel Cyan
      { light: 'rgb(255, 255, 230)', dark: 'rgb(60, 60, 30)' },    // Pastel Yellow
      { light: 'rgb(240, 230, 255)', dark: 'rgb(40, 30, 60)' },    // Pastel Indigo
      { light: 'rgb(255, 240, 245)', dark: 'rgb(60, 40, 50)' },    // Pastel Pink
      { light: 'rgb(240, 255, 240)', dark: 'rgb(40, 60, 40)' },    // Pastel Mint
    ];
    return colors;
  }, []);

  const getDriverColor = (index: number) => {
    const colorIndex = index % driverColors.length;
    return isDarkMode ? driverColors[colorIndex].dark : driverColors[colorIndex].light;
  };

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

  // Initialize stints with base stint time duration
  const initializeStints = useMemo(() => {
    const assignments: StintAssignment[] = [];
    let currentTime = 0;
    
    // Calculate base stint time
    const totalPitTime = config.pitDuration * (config.numStints - 1);
    const availableRaceTime = config.totalRaceTime - totalPitTime;
    const baseStintTime = Math.round(availableRaceTime / config.numStints);
    
    for (let stint = 1; stint <= config.numStints; stint++) {
      // Assign driver in rotation
      const driverIndex = (stint - 1) % config.numDrivers;
      
      assignments.push({
        driver: driverIndex + 1,
        stint,
        duration: baseStintTime, // Initialize with base stint time
        isJoker: false,
        isLong: false,
        startTime: currentTime,
        endTime: currentTime + baseStintTime,
      });
      
      currentTime += baseStintTime;
      
      // Add pit stop time (except for last stint)
      if (stint < config.numStints) {
        currentTime += config.pitDuration;
      }
    }
    
    return assignments;
  }, [config]);

  // Reinitialize stints when config changes significantly (numStints or numDrivers)
  useEffect(() => {
    // Skip on initial mount before loading from storage
    if (!hasLoadedFromStorage) {
      return;
    }

    // Check if config has changed significantly
    const configStintsChanged = stintAssignments.length > 0 && stintAssignments.length !== config.numStints;

    if (configStintsChanged || stintAssignments.length === 0) {
      // Reinitialize stint assignments
      setStintAssignments(initializeStints);
    }
  }, [config.numStints, config.numDrivers, initializeStints, hasLoadedFromStorage, stintAssignments.length]);

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

  // Persist stint configuration to localStorage
  useEffect(() => {
    saveStintConfig(config);
  }, [config]);

  // Persist driver names to localStorage
  useEffect(() => {
    saveDriverNames(driverNames);
  }, [driverNames]);

  // Persist stint assignments to localStorage
  useEffect(() => {
    saveStintAssignments(stintAssignments);
  }, [stintAssignments]);

  // Persist current driver index to localStorage
  useEffect(() => {
    saveCurrentDriverIndex(currentDriverIndex);
  }, [currentDriverIndex]);

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
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
  };

  const formatSeconds = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handleConfigChange = (field: keyof StintConfig, value: number) => {
    setConfig(prev => ({ ...prev, [field]: value }));
  };

  const handleDriverNameChange = (index: number, name: string) => {
    const newNames = [...driverNames];
    newNames[index] = name;
    setDriverNames(newNames);
  };

  const handleStintDurationChange = (stintIndex: number, duration: number) => {
    const newAssignments = [...stintAssignments];
    const oldDuration = newAssignments[stintIndex].duration;
    const timeDifference = duration - oldDuration;
    
    // Update the changed stint
    newAssignments[stintIndex].duration = duration;
    
    // Determine if it's a joker or long stint
    newAssignments[stintIndex].isJoker = duration > 0 && duration >= config.minStintTime && duration <= config.minStintTime + 5;
    newAssignments[stintIndex].isLong = duration >= config.maxStintTime - 5 && duration <= config.maxStintTime;
    
    // Calculate how many following stints need to compensate
    const followingStints = newAssignments.filter((_, idx) => idx > stintIndex && newAssignments[idx].duration > 0);
    
    if (followingStints.length > 0 && timeDifference !== 0) {
      // Distribute the time difference equally among following stints
      const compensationPerStint = -timeDifference / followingStints.length;
      
      // Apply compensation only to following stints
      newAssignments.forEach((stint, idx) => {
        if (idx > stintIndex && stint.duration > 0) {
          const newDuration = stint.duration + compensationPerStint;
          // Ensure the compensated duration stays within bounds
          if (newDuration >= config.minStintTime && newDuration <= config.maxStintTime) {
            stint.duration = Math.round(newDuration * 10) / 10; // Round to 1 decimal
            
            // Re-evaluate if it's a joker or long stint
            stint.isJoker = stint.duration >= config.minStintTime && stint.duration <= config.minStintTime + 5;
            stint.isLong = stint.duration >= config.maxStintTime - 5 && stint.duration <= config.maxStintTime;
          }
        }
      });
    }
    
    // Recalculate times
    let currentTime = 0;
    for (let i = 0; i < newAssignments.length; i++) {
      newAssignments[i].startTime = currentTime;
      currentTime += newAssignments[i].duration;
      newAssignments[i].endTime = currentTime;
      
      if (i < newAssignments.length - 1) {
        currentTime += config.pitDuration;
      }
    }
    
    setStintAssignments(newAssignments);
  };

  const handleStintDriverChange = (stintIndex: number, driverNum: number) => {
    const newAssignments = [...stintAssignments];
    newAssignments[stintIndex].driver = driverNum;
    setStintAssignments(newAssignments);
  };

  // Preset handlers
  const handlePresetSelect = (presetId: string) => {
    setSelectedPresetId(presetId);
    if (presetId && trackId !== undefined) {
      const preset = availablePresets.find(p => p.id === presetId);
      if (preset) {
        setConfig(preset.config);
        setActivePreset(trackId, presetId);

        // Force recalculate stints based on new config
        const assignments: StintAssignment[] = [];
        let currentTime = 0;
        const totalPitTime = preset.config.pitDuration * (preset.config.numStints - 1);
        const availableRaceTime = preset.config.totalRaceTime - totalPitTime;
        const baseStintTime = Math.round(availableRaceTime / preset.config.numStints);

        for (let stint = 1; stint <= preset.config.numStints; stint++) {
          const driverIndex = (stint - 1) % preset.config.numDrivers;

          assignments.push({
            driver: driverIndex + 1,
            stint,
            duration: baseStintTime,
            isJoker: false,
            isLong: false,
            startTime: currentTime,
            endTime: currentTime + baseStintTime,
          });

          currentTime += baseStintTime;
          if (stint < preset.config.numStints) {
            currentTime += preset.config.pitDuration;
          }
        }

        setStintAssignments(assignments);
      }
    }
  };

  const handleSavePreset = () => {
    if (!newPresetName.trim() || trackId === undefined || !trackName) return;

    const presetId = `preset_${Date.now()}`;
    const newPreset: StintPreset = {
      id: presetId,
      name: newPresetName.trim(),
      config: { ...config }
    };

    saveTrackPreset(trackId, trackName, newPreset);
    setAvailablePresets(prev => [...prev, newPreset]);
    setSelectedPresetId(presetId);
    setActivePreset(trackId, presetId);
    setNewPresetName('');
    setShowSavePresetDialog(false);
  };

  const handleDeletePreset = () => {
    if (!selectedPresetId || trackId === undefined) return;

    if (confirm('Are you sure you want to delete this preset?')) {
      deleteTrackPreset(trackId, selectedPresetId);
      const updatedPresets = availablePresets.filter(p => p.id !== selectedPresetId);
      setAvailablePresets(updatedPresets);
      setSelectedPresetId(updatedPresets[0]?.id || '');
    }
  };

  return (
    <div className={`p-6 ${isDarkMode ? 'bg-gray-800 text-white' : 'bg-white text-gray-900'}`}>
      <h2 className="text-2xl font-bold mb-6">Stint Planner</h2>

      {/* Preset Selector */}
      {trackName && (
        <div className={`mb-6 p-4 rounded-lg border ${isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-blue-50 border-gray-300'}`}>
          <div className="flex items-center gap-3 flex-wrap">
            <label className={`text-sm font-medium ${isDarkMode ? 'text-gray-200' : 'text-gray-700'}`}>
              {trackName} Presets:
            </label>

            <select
              value={selectedPresetId}
              onChange={(e) => handlePresetSelect(e.target.value)}
              className={`flex-1 min-w-[200px] p-2 rounded border ${
                isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'
              }`}
              disabled={availablePresets.length === 0}
            >
              <option value="">-- No preset selected --</option>
              {availablePresets.map(preset => (
                <option key={preset.id} value={preset.id}>
                  {preset.name}
                </option>
              ))}
            </select>

            <button
              onClick={() => setShowSavePresetDialog(!showSavePresetDialog)}
              className={`px-4 py-2 rounded ${
                isDarkMode ? 'bg-blue-600 hover:bg-blue-700 text-white' : 'bg-blue-500 hover:bg-blue-600 text-white'
              }`}
            >
              Save Preset
            </button>

            {selectedPresetId && (
              <button
                onClick={handleDeletePreset}
                className={`px-4 py-2 rounded ${
                  isDarkMode ? 'bg-red-600 hover:bg-red-700 text-white' : 'bg-red-500 hover:bg-red-600 text-white'
                }`}
              >
                Delete
              </button>
            )}
          </div>

          {/* Save Preset Dialog */}
          {showSavePresetDialog && (
            <div className="mt-4 flex items-center gap-3">
              <input
                type="text"
                value={newPresetName}
                onChange={(e) => setNewPresetName(e.target.value)}
                placeholder="Preset name (e.g., 6 Hour Race)"
                className={`flex-1 p-2 rounded border ${
                  isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'
                }`}
                onKeyPress={(e) => e.key === 'Enter' && handleSavePreset()}
              />
              <button
                onClick={handleSavePreset}
                disabled={!newPresetName.trim()}
                className={`px-4 py-2 rounded ${
                  !newPresetName.trim()
                    ? 'bg-gray-400 cursor-not-allowed text-gray-200'
                    : isDarkMode
                    ? 'bg-green-600 hover:bg-green-700 text-white'
                    : 'bg-green-500 hover:bg-green-600 text-white'
                }`}
              >
                Save
              </button>
              <button
                onClick={() => {
                  setShowSavePresetDialog(false);
                  setNewPresetName('');
                }}
                className={`px-4 py-2 rounded ${
                  isDarkMode ? 'bg-gray-600 hover:bg-gray-700 text-white' : 'bg-gray-300 hover:bg-gray-400 text-gray-900'
                }`}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}

      {/* Active Stint Timer */}
      {activeStint && (
        <div 
          className={`mb-6 p-4 rounded-lg border-2 ${isDarkMode ? 'border-green-700' : 'border-green-300'}`}
          style={{
            backgroundColor: getDriverColor(activeStint.driverIndex),
            color: isDarkMode ? '#ffffff' : '#000000'
          }}
        >
          <h3 className="text-lg font-semibold mb-2">Active Stint</h3>
          <div className="flex items-center gap-4">
            <span className="text-xl font-bold">
              {driverNames[activeStint.driverIndex]} - {formatSeconds(activeStint.elapsedTime)}
            </span>
            {activeStint.isPitStop && <span className="text-sm">(In Pit)</span>}
          </div>
        </div>
      )}

      {/* Current Driver Selection */}
      <div className="mb-6">
        <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
          Current Driver
        </label>
        <select
          value={currentDriverIndex}
          onChange={(e) => setCurrentDriverIndex(parseInt(e.target.value))}
          className={`w-full md:w-64 p-2 rounded border ${
            isDarkMode ? 'border-gray-600' : 'border-gray-300'
          }`}
          style={{
            backgroundColor: getDriverColor(currentDriverIndex),
            color: isDarkMode ? '#ffffff' : '#000000'
          }}
        >
          {driverNames.map((name, index) => (
            <option 
              key={index} 
              value={index}
              style={{
                backgroundColor: getDriverColor(index),
                color: isDarkMode ? '#ffffff' : '#000000'
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
          <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
            Number of Stints
          </label>
          <input
            type="number"
            min="1"
            max="20"
            value={config.numStints}
            onChange={(e) => handleConfigChange('numStints', parseInt(e.target.value) || 1)}
            className={`w-full p-2 rounded border ${
              isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
            }`}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
            Min Stint Time (minutes)
          </label>
          <input
            type="number"
            min="1"
            max="120"
            value={config.minStintTime}
            onChange={(e) => handleConfigChange('minStintTime', parseInt(e.target.value) || 1)}
            className={`w-full p-2 rounded border ${
              isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
            }`}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
            Max Stint Time (minutes)
          </label>
          <input
            type="number"
            min="1"
            max="120"
            value={config.maxStintTime}
            onChange={(e) => handleConfigChange('maxStintTime', parseInt(e.target.value) || 1)}
            className={`w-full p-2 rounded border ${
              isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
            }`}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
            Pit Duration (minutes)
          </label>
          <input
            type="number"
            min="0.1"
            max="30"
            step="0.1"
            value={config.pitDuration}
            onChange={(e) => handleConfigChange('pitDuration', parseFloat(e.target.value) || 1)}
            className={`w-full p-2 rounded border ${
              isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
            }`}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
            Number of Drivers
          </label>
          <input
            type="number"
            min="1"
            max="10"
            value={config.numDrivers}
            onChange={(e) => handleConfigChange('numDrivers', parseInt(e.target.value) || 1)}
            className={`w-full p-2 rounded border ${
              isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
            }`}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
            Total Race Time (minutes)
          </label>
          <input
            type="number"
            min="30"
            max="1440"
            value={config.totalRaceTime}
            onChange={(e) => handleConfigChange('totalRaceTime', parseInt(e.target.value) || 30)}
            className={`w-full p-2 rounded border ${
              isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
            }`}
          />
        </div>
      </div>

      {/* Available Special Stints */}
      <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
        <h3 className="text-lg font-semibold mb-3">Available Special Stints</h3>
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

      {/* Driver Names */}
      <div className="mb-6">
        <h3 className="text-lg font-semibold mb-3">Driver Names</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {driverNames.map((name, index) => (
            <div key={index}>
              <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Driver {index + 1}
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => handleDriverNameChange(index, e.target.value)}
                className={`w-full p-2 rounded border transition-colors ${
                  isDarkMode ? 'border-gray-600' : 'border-gray-300'
                }`}
                style={{
                  backgroundColor: getDriverColor(index),
                  color: isDarkMode ? '#ffffff' : '#000000'
                }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Driver Statistics */}
      <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
        <h3 className="text-lg font-semibold mb-3">Driver Statistics</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {driverStats.map((stat, index) => (
            <div 
              key={stat.driver} 
              className={`p-3 rounded border transition-colors ${
                isDarkMode ? 'border-gray-600' : 'border-gray-300'
              }`}
              style={{
                backgroundColor: getDriverColor(index),
                color: isDarkMode ? '#ffffff' : '#000000'
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

      {/* Stint Table */}
      <div className="overflow-x-auto">
        <table className={`w-full border-collapse ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
          <thead>
            <tr className={isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}>
              <th className={`border p-2 text-left ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                Stint
              </th>
              <th className={`border p-2 text-center ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                Driver
              </th>
              <th className={`border p-2 text-center ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                Duration (min)
              </th>
              <th className={`border p-2 text-center ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                Type
              </th>
              <th className={`border p-2 text-center ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                Time Range
              </th>
            </tr>
          </thead>
          <tbody>
            {stintAssignments.map((assignment, index) => (
              <tr key={index} className={isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'}>
                <td className={`border p-2 font-medium ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  {assignment.stint}
                </td>
                <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  <select
                    value={assignment.driver}
                    onChange={(e) => handleStintDriverChange(index, parseInt(e.target.value))}
                    className={`w-full p-1 rounded border ${
                      isDarkMode ? 'border-gray-600' : 'border-gray-300'
                    }`}
                    style={{
                      backgroundColor: getDriverColor(assignment.driver - 1),
                      color: isDarkMode ? '#ffffff' : '#000000'
                    }}
                  >
                    {driverNames.map((name, driverIndex) => (
                      <option 
                        key={driverIndex} 
                        value={driverIndex + 1}
                        style={{
                          backgroundColor: getDriverColor(driverIndex),
                          color: isDarkMode ? '#ffffff' : '#000000'
                        }}
                      >
                        {name}
                      </option>
                    ))}
                  </select>
                </td>
                <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  <input
                    type="number"
                    min="0"
                    max="120"
                    value={assignment.duration}
                    onChange={(e) => handleStintDurationChange(index, parseInt(e.target.value) || 0)}
                    className={`w-full p-1 rounded border text-center ${
                      isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
                    } ${
                      assignment.isJoker
                        ? isDarkMode ? 'bg-yellow-900' : 'bg-yellow-100'
                        : assignment.isLong
                        ? isDarkMode ? 'bg-blue-900' : 'bg-blue-100'
                        : ''
                    }`}
                  />
                </td>
                <td className={`border p-2 text-center ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  {assignment.isJoker && <span className="font-semibold text-yellow-600">JOKER</span>}
                  {assignment.isLong && <span className="font-semibold text-blue-600">LONG</span>}
                  {!assignment.isJoker && !assignment.isLong && assignment.duration > 0 && <span>Normal</span>}
                </td>
                <td className={`border p-2 text-center text-sm ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  {assignment.duration > 0 && (
                    <span>{formatTime(assignment.startTime)} - {formatTime(assignment.endTime)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Stint History */}
      {stintHistory.length > 0 && (
        <div className="mt-6">
          <h3 className="text-lg font-semibold mb-3">Completed Stints</h3>
          <div className="space-y-2">
            {stintHistory.map((stint, index) => (
              <div key={index} className={`p-2 rounded ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
                {driverNames[stint.driver - 1]} - {stint.duration} minutes
                <span className="text-sm ml-2 opacity-70">
                  ({stint.timestamp.toLocaleTimeString()})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="mt-4 flex gap-4 text-sm">
        <div className="flex items-center gap-2">
          <div className={`w-4 h-4 ${isDarkMode ? 'bg-yellow-900' : 'bg-yellow-100'} border ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}></div>
          <span>Joker Stint ({config.minStintTime} - {config.minStintTime + 5} min)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-4 h-4 ${isDarkMode ? 'bg-blue-900' : 'bg-blue-100'} border ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}></div>
          <span>Long Stint ({config.maxStintTime - 5} - {config.maxStintTime} min)</span>
        </div>
      </div>
    </div>
  );
};

export default StintPlanner;