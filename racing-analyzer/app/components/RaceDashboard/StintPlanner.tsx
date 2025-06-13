import React, { useState, useEffect, useMemo, useRef } from 'react';

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
  sessionInfo
}) => {
  const [config, setConfig] = useState<StintConfig>({
    numStints: 8,
    minStintTime: 25,
    maxStintTime: 60,
    pitDuration: 5,
    numDrivers: 4,
    totalRaceTime: 360,
  });

  const [stintAssignments, setStintAssignments] = useState<StintAssignment[]>([]);
  const [driverNames, setDriverNames] = useState<string[]>(['Driver 1', 'Driver 2', 'Driver 3', 'Driver 4']);
  const [currentDriverIndex, setCurrentDriverIndex] = useState<number>(0);
  const [activeStint, setActiveStint] = useState<ActiveStint | null>(null);
  const [stintHistory, setStintHistory] = useState<{driver: number, duration: number, timestamp: Date}[]>([]);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastPitStatusRef = useRef<string>('');

  // Calculate available jokers and long stints
  const availableSpecialStints = useMemo(() => {
    const { numStints, minStintTime, maxStintTime, pitDuration, totalRaceTime } = config;
    
    // Calculate available race time (excluding pit stops)
    const totalPitTime = pitDuration * (numStints - 1);
    const availableRaceTime = totalRaceTime - totalPitTime;
    
    // Calculate base stint time
    const baseStintTime = availableRaceTime / numStints;
    
    // Goal: Maximize the number of special stints (jokers + longs)
    // Constraint: Total time must equal available race time
    
    let maxJokers = 0;
    let maxLongs = 0;
    let bestTimeDiff = Infinity;
    
    // Try different combinations, maximizing total special stints
    for (let jokers = 0; jokers <= numStints; jokers++) {
      for (let longs = 0; longs <= (numStints - jokers); longs++) {
        const normalStints = numStints - jokers - longs;
        
        // Calculate total race time with this combination
        const totalTime = (jokers * minStintTime) + 
                         (longs * maxStintTime) + 
                         (normalStints * baseStintTime);
        
        const timeDiff = Math.abs(totalTime - availableRaceTime);
        
        // Accept combinations within 2 minutes of target
        if (timeDiff <= 2) {
          // Prefer combinations with more special stints
          if ((jokers + longs) > (maxJokers + maxLongs) || 
              ((jokers + longs) === (maxJokers + maxLongs) && timeDiff < bestTimeDiff)) {
            maxJokers = jokers;
            maxLongs = longs;
            bestTimeDiff = timeDiff;
          }
        }
      }
    }
    
    // If we still didn't find any combination, relax the tolerance
    if (maxJokers === 0 && maxLongs === 0) {
      // Try with more relaxed tolerance (5 minutes)
      for (let jokers = 0; jokers <= numStints; jokers++) {
        for (let longs = 0; longs <= (numStints - jokers); longs++) {
          const normalStints = numStints - jokers - longs;
          
          const totalTime = (jokers * minStintTime) + 
                           (longs * maxStintTime) + 
                           (normalStints * baseStintTime);
          
          const timeDiff = Math.abs(totalTime - availableRaceTime);
          
          if (timeDiff <= 5) {
            if ((jokers + longs) > (maxJokers + maxLongs)) {
              maxJokers = jokers;
              maxLongs = longs;
              bestTimeDiff = timeDiff;
            }
          }
        }
      }
    }
    
    return {
      maxJokers: Math.max(0, maxJokers),
      maxLongs: Math.max(0, maxLongs),
      baseStintTime: Math.round(baseStintTime),
      jokerRange: `${minStintTime}-${minStintTime + 3}`,
      longRange: `${maxStintTime - 3}-${maxStintTime}`
    };
  }, [config]);

  // Initialize stints with 0 duration
  const initializeStints = useMemo(() => {
    const assignments: StintAssignment[] = [];
    let currentTime = 0;
    
    for (let stint = 1; stint <= config.numStints; stint++) {
      // Assign driver in rotation
      const driverIndex = (stint - 1) % config.numDrivers;
      
      assignments.push({
        driver: driverIndex + 1,
        stint,
        duration: 0, // Initialize with 0
        isJoker: false,
        isLong: false,
        startTime: currentTime,
        endTime: currentTime,
      });
      
      // Add pit stop time (except for last stint)
      if (stint < config.numStints) {
        currentTime += config.pitDuration;
      }
    }
    
    return assignments;
  }, [config]);

  useEffect(() => {
    setStintAssignments(initializeStints);
  }, [initializeStints]);

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
    const assignment = newAssignments[stintIndex];
    assignment.duration = duration;
    
    // Determine if it's a joker or long stint
    assignment.isJoker = duration > 0 && duration <= config.minStintTime;
    assignment.isLong = duration >= config.maxStintTime;
    
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

  return (
    <div className={`p-6 ${isDarkMode ? 'bg-gray-800 text-white' : 'bg-white text-gray-900'}`}>
      <h2 className="text-2xl font-bold mb-6">Stint Planner</h2>
      
      {/* Active Stint Timer */}
      {activeStint && (
        <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-green-900' : 'bg-green-100'}`}>
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
            isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
          }`}
        >
          {driverNames.map((name, index) => (
            <option key={index} value={index}>
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
                className={`w-full p-2 rounded border ${
                  isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
                }`}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Driver Statistics */}
      <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
        <h3 className="text-lg font-semibold mb-3">Driver Statistics</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {driverStats.map(stat => (
            <div key={stat.driver} className={`p-3 rounded ${isDarkMode ? 'bg-gray-600' : 'bg-white'}`}>
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
                      isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-300'
                    }`}
                  >
                    {driverNames.map((name, driverIndex) => (
                      <option key={driverIndex} value={driverIndex + 1}>
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
          <span>Joker Stint (≤ Min Time)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-4 h-4 ${isDarkMode ? 'bg-blue-900' : 'bg-blue-100'} border ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}></div>
          <span>Long Stint (≥ Max Time)</span>
        </div>
      </div>
    </div>
  );
};

export default StintPlanner;