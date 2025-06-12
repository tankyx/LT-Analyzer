import React, { useState, useEffect, useMemo } from 'react';

interface StintPlannerProps {
  isDarkMode?: boolean;
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
  totalTime: number;
  numStints: number;
  jokerStints: number;
  longStints: number;
}

const StintPlanner: React.FC<StintPlannerProps> = ({ isDarkMode = false }) => {
  const [config, setConfig] = useState<StintConfig>({
    numStints: 8,
    minStintTime: 25,
    maxStintTime: 60,
    pitDuration: 5,
    numDrivers: 4,
    totalRaceTime: 360,
  });

  const [stintAssignments, setStintAssignments] = useState<StintAssignment[]>([]);

  const calculateStints = useMemo(() => {
    const assignments: StintAssignment[] = [];
    const { numStints, minStintTime, maxStintTime, pitDuration, numDrivers, totalRaceTime } = config;

    // Calculate available race time (excluding pit stops)
    const totalPitTime = pitDuration * (numStints - 1);
    const availableRaceTime = totalRaceTime - totalPitTime;

    // Calculate base stint time
    const baseStintTime = Math.floor(availableRaceTime / numStints);
    
    // Define joker stint (minimum time)
    const jokerTime = minStintTime;
    
    // Define long stint (maximum time)
    const longTime = Math.min(maxStintTime, baseStintTime + 10);

    // Calculate how many joker and long stints we can have
    const maxJokerStints = Math.floor(numDrivers / 2); // Each driver gets at most 1 joker
    const maxLongStints = Math.floor(numDrivers / 2); // Each driver gets at most 1 long

    // Initialize driver tracking
    const driverStints: { [key: number]: number } = {};
    const driverJokers: { [key: number]: number } = {};
    const driverLongs: { [key: number]: number } = {};
    const driverTotalTime: { [key: number]: number } = {};

    for (let i = 1; i <= numDrivers; i++) {
      driverStints[i] = 0;
      driverJokers[i] = 0;
      driverLongs[i] = 0;
      driverTotalTime[i] = 0;
    }

    let currentTime = 0;
    let remainingRaceTime = availableRaceTime;
    let jokerSintsUsed = 0;
    let longStintsUsed = 0;

    // Assign stints
    for (let stint = 1; stint <= numStints; stint++) {
      // Find driver with least total time
      let selectedDriver = 1;
      let minTime = driverTotalTime[1];
      
      for (let d = 2; d <= numDrivers; d++) {
        if (driverTotalTime[d] < minTime) {
          minTime = driverTotalTime[d];
          selectedDriver = d;
        }
      }

      // Determine stint type and duration
      let duration = baseStintTime;
      let isJoker = false;
      let isLong = false;

      // Assign joker stints early in the race
      if (stint <= maxJokerStints && jokerSintsUsed < maxJokerStints && driverJokers[selectedDriver] === 0) {
        duration = jokerTime;
        isJoker = true;
        jokerSintsUsed++;
        driverJokers[selectedDriver]++;
      }
      // Assign long stints in the middle
      else if (stint > maxJokerStints && stint <= numStints - maxJokerStints && 
               longStintsUsed < maxLongStints && driverLongs[selectedDriver] === 0) {
        duration = longTime;
        isLong = true;
        longStintsUsed++;
        driverLongs[selectedDriver]++;
      }
      // Last stint gets remaining time
      else if (stint === numStints) {
        duration = remainingRaceTime;
      }

      // Ensure duration is within bounds
      duration = Math.max(minStintTime, Math.min(maxStintTime, duration));
      
      // Update remaining time
      remainingRaceTime -= duration;

      assignments.push({
        driver: selectedDriver,
        stint,
        duration,
        isJoker,
        isLong,
        startTime: currentTime,
        endTime: currentTime + duration,
      });

      // Update tracking
      driverStints[selectedDriver]++;
      driverTotalTime[selectedDriver] += duration;
      
      // Add pit stop time (except for last stint)
      currentTime += duration;
      if (stint < numStints) {
        currentTime += pitDuration;
      }
    }

    return assignments;
  }, [config]);

  useEffect(() => {
    setStintAssignments(calculateStints);
  }, [calculateStints]);

  const driverStats = useMemo(() => {
    const stats: DriverStats[] = [];
    
    for (let driver = 1; driver <= config.numDrivers; driver++) {
      const driverStints = stintAssignments.filter(s => s.driver === driver);
      stats.push({
        driver,
        totalTime: driverStints.reduce((sum, s) => sum + s.duration, 0),
        numStints: driverStints.length,
        jokerStints: driverStints.filter(s => s.isJoker).length,
        longStints: driverStints.filter(s => s.isLong).length,
      });
    }
    
    return stats;
  }, [stintAssignments, config.numDrivers]);

  const formatTime = (minutes: number): string => {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
  };

  const handleConfigChange = (field: keyof StintConfig, value: number) => {
    setConfig(prev => ({ ...prev, [field]: value }));
  };

  return (
    <div className={`p-6 ${isDarkMode ? 'bg-gray-800 text-white' : 'bg-white text-gray-900'}`}>
      <h2 className="text-2xl font-bold mb-6">Stint Planner</h2>
      
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
            min="1"
            max="30"
            value={config.pitDuration}
            onChange={(e) => handleConfigChange('pitDuration', parseInt(e.target.value) || 1)}
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

      {/* Driver Statistics */}
      <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
        <h3 className="text-lg font-semibold mb-3">Driver Statistics</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {driverStats.map(stat => (
            <div key={stat.driver} className={`p-3 rounded ${isDarkMode ? 'bg-gray-600' : 'bg-white'}`}>
              <h4 className="font-medium mb-2">Driver {stat.driver}</h4>
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
              {Array.from({ length: config.numDrivers }, (_, i) => (
                <th key={i + 1} className={`border p-2 text-center ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  Driver {i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: config.numStints }, (_, stintIndex) => {
              const stint = stintIndex + 1;
              return (
                <tr key={stint} className={isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'}>
                  <td className={`border p-2 font-medium ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    {stint}
                  </td>
                  {Array.from({ length: config.numDrivers }, (_, driverIndex) => {
                    const driver = driverIndex + 1;
                    const assignment = stintAssignments.find(
                      a => a.stint === stint && a.driver === driver
                    );
                    
                    return (
                      <td
                        key={driver}
                        className={`border p-2 text-center ${isDarkMode ? 'border-gray-600' : 'border-gray-300'} ${
                          assignment
                            ? assignment.isJoker
                              ? isDarkMode ? 'bg-yellow-900' : 'bg-yellow-100'
                              : assignment.isLong
                              ? isDarkMode ? 'bg-blue-900' : 'bg-blue-100'
                              : ''
                            : ''
                        }`}
                      >
                        {assignment && (
                          <div>
                            <div className="font-medium">{assignment.duration}m</div>
                            <div className="text-xs opacity-70">
                              {formatTime(assignment.startTime)} - {formatTime(assignment.endTime)}
                            </div>
                            {assignment.isJoker && (
                              <div className="text-xs font-semibold">JOKER</div>
                            )}
                            {assignment.isLong && (
                              <div className="text-xs font-semibold">LONG</div>
                            )}
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-4 flex gap-4 text-sm">
        <div className="flex items-center gap-2">
          <div className={`w-4 h-4 ${isDarkMode ? 'bg-yellow-900' : 'bg-yellow-100'} border ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}></div>
          <span>Joker Stint (Minimum)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-4 h-4 ${isDarkMode ? 'bg-blue-900' : 'bg-blue-100'} border ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}></div>
          <span>Long Stint (Maximum)</span>
        </div>
      </div>
    </div>
  );
};

export default StintPlanner;