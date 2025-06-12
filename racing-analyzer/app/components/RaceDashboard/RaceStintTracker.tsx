import React, { useState, useEffect, useRef, useCallback } from 'react';

interface StintData {
  id: number;
  driver: string;
  startTime: Date;
  endTime?: Date;
  duration?: number;
  lapCount: number;
  status: 'active' | 'completed' | 'pit';
}

interface Driver {
  id: string;
  name: string;
  color: string;
}

interface Team {
  Kart: string;
  Team: string;
  Position: string;
  'Last Lap': string;
  'Best Lap': string;
  'Pit Stops': string;
  Gap: string;
  RunTime: string;
  Status?: string;
  lastPitCount?: number;
}

interface RaceStintTrackerProps {
  isDarkMode?: boolean;
  myTeam?: string;
  teams: Team[];
  isSimulating: boolean;
  sessionInfo?: {
    dyn1?: string;
    dyn2?: string;
    light?: string;
  };
}

const RaceStintTracker: React.FC<RaceStintTrackerProps> = ({ 
  isDarkMode = false, 
  myTeam,
  teams,
  isSimulating,
  sessionInfo
}) => {
  const [currentStint, setCurrentStint] = useState<StintData | null>(null);
  const [stintHistory, setStintHistory] = useState<StintData[]>([]);
  const [currentDriver, setCurrentDriver] = useState<string>('');
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [newDriverName, setNewDriverName] = useState<string>('');
  const [elapsedTime, setElapsedTime] = useState<number>(0);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [raceStarted, setRaceStarted] = useState<boolean>(false);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastStatusRef = useRef<string>('');
  const lastLightRef = useRef<string>('');

  // Predefined color palette for drivers
  const colorPalette = [
    '#3B82F6', // Blue
    '#10B981', // Emerald
    '#F59E0B', // Amber
    '#EF4444', // Red
    '#8B5CF6', // Violet
    '#EC4899', // Pink
    '#14B8A6', // Teal
    '#F97316', // Orange
  ];

  // Find my team data
  const myTeamData = teams.find(t => t.Kart === myTeam);
  const currentStatus = myTeamData?.Status || '';
  const sessionLight = sessionInfo?.light || '';

  // Define all callback functions first
  const handlePitIn = useCallback(() => {
    if (currentStint && currentStint.status === 'active') {
      // Complete current stint
      const completedStint: StintData = {
        ...currentStint,
        endTime: new Date(),
        duration: elapsedTime,
        status: 'completed'
      };
      setStintHistory(prev => [...prev, completedStint]);
      setCurrentStint({ ...completedStint, status: 'pit' });
      setElapsedTime(0);
    }
  }, [currentStint, elapsedTime]);

  const handlePitOut = useCallback(() => {
    if (!currentDriver) return;
    
    // Start new stint
    const newStint: StintData = {
      id: Date.now(),
      driver: currentDriver,
      startTime: new Date(),
      lapCount: 0,
      status: 'active'
    };
    setCurrentStint(newStint);
    setElapsedTime(0);
  }, [currentDriver]);

  const addDriver = () => {
    if (!newDriverName.trim()) return;
    
    const newDriver: Driver = {
      id: Date.now().toString(),
      name: newDriverName.trim(),
      color: colorPalette[drivers.length % colorPalette.length]
    };
    
    setDrivers([...drivers, newDriver]);
    setNewDriverName('');
    
    // If no current driver, set this as current
    if (!currentDriver && drivers.length === 0) {
      setCurrentDriver(newDriver.name);
    }
  };

  const removeDriver = (driverId: string) => {
    const driver = drivers.find(d => d.id === driverId);
    if (driver && currentDriver === driver.name) {
      setCurrentDriver('');
    }
    setDrivers(drivers.filter(d => d.id !== driverId));
  };

  const getDriverColor = (driverName: string): string => {
    const driver = drivers.find(d => d.name === driverName);
    return driver?.color || '#6B7280';
  };

  const handleManualStart = () => {
    if (!currentDriver) {
      alert('Please select a driver first');
      return;
    }

    const newStint: StintData = {
      id: Date.now(),
      driver: currentDriver,
      startTime: new Date(),
      lapCount: 0,
      status: 'active'
    };
    setCurrentStint(newStint);
    setElapsedTime(0);
    setIsPaused(false);
  };

  const handleManualStop = () => {
    if (currentStint && currentStint.status === 'active') {
      const completedStint: StintData = {
        ...currentStint,
        endTime: new Date(),
        duration: elapsedTime,
        status: 'completed'
      };
      setStintHistory(prev => [...prev, completedStint]);
      setCurrentStint(null);
      setElapsedTime(0);
    }
  };

  const handlePause = () => {
    setIsPaused(!isPaused);
  };

  const formatTime = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  };

  const getTotalDriverTime = (driver: string): number => {
    const driverStints = stintHistory.filter(s => s.driver === driver);
    const totalTime = driverStints.reduce((sum, stint) => sum + (stint.duration || 0), 0);
    
    // Add current stint if active
    if (currentStint?.driver === driver && currentStint.status === 'active') {
      return totalTime + elapsedTime;
    }
    
    return totalTime;
  };

  const getDriverStats = () => {
    return drivers.map(driver => ({
      driver: driver.name,
      color: driver.color,
      stints: stintHistory.filter(s => s.driver === driver.name).length + 
              (currentStint?.driver === driver.name ? 1 : 0),
      totalTime: getTotalDriverTime(driver.name)
    }));
  };

  // Now define all useEffect hooks
  // Auto-detect race start (green flag)
  useEffect(() => {
    if (!myTeam || !isSimulating || !currentDriver) return;

    // Check if light changed from non-green to green (race start)
    if (sessionLight === 'green' && lastLightRef.current !== 'green' && !raceStarted) {
      // Race just started - begin first stint
      setRaceStarted(true);
      const newStint: StintData = {
        id: Date.now(),
        driver: currentDriver,
        startTime: new Date(),
        lapCount: 0,
        status: 'active'
      };
      setCurrentStint(newStint);
      setElapsedTime(0);
      setIsPaused(false);
    }
    lastLightRef.current = sessionLight;
  }, [sessionLight, myTeam, isSimulating, currentDriver, raceStarted]);

  // Auto-detect pit stops
  useEffect(() => {
    if (!myTeam || !isSimulating) return;

    // Check if status changed
    if (currentStatus !== lastStatusRef.current) {
      if (currentStatus === 'Pit-in' && lastStatusRef.current !== 'Pit-in') {
        // Entered pit - stop current stint
        handlePitIn();
      } else if (currentStatus !== 'Pit-in' && lastStatusRef.current === 'Pit-in') {
        // Left pit - start new stint
        handlePitOut();
      }
      lastStatusRef.current = currentStatus;
    }
  }, [currentStatus, myTeam, isSimulating, handlePitIn, handlePitOut]);

  // Timer effect
  useEffect(() => {
    if (currentStint && currentStint.status === 'active' && !isPaused) {
      intervalRef.current = setInterval(() => {
        setElapsedTime(prev => prev + 1);
      }, 1000);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [currentStint, isPaused]);

  return (
    <div className={`p-6 ${isDarkMode ? 'bg-gray-800 text-white' : 'bg-white text-gray-900'}`}>
      <h2 className="text-2xl font-bold mb-6">Race Stint Tracker</h2>

      {/* Team Selection & Auto-tracking Status */}
      <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold">Auto-Tracking</h3>
            <p className="text-sm opacity-70">
              {myTeam ? `Tracking Team: ${myTeamData?.Team || 'Unknown'} (Kart #${myTeam})` : 'Select your team in main tab to enable auto-tracking'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* Session Light Status */}
            {sessionLight && (
              <span className={`px-3 py-1 rounded text-sm font-medium flex items-center gap-2 ${
                sessionLight === 'green' 
                  ? isDarkMode ? 'bg-green-900 text-green-200' : 'bg-green-100 text-green-800'
                  : sessionLight === 'yellow' 
                  ? isDarkMode ? 'bg-yellow-900 text-yellow-200' : 'bg-yellow-100 text-yellow-800'
                  : sessionLight === 'red'
                  ? isDarkMode ? 'bg-red-900 text-red-200' : 'bg-red-100 text-red-800'
                  : isDarkMode ? 'bg-gray-600 text-gray-200' : 'bg-gray-200 text-gray-800'
              }`}>
                <span className={`inline-block w-2 h-2 rounded-full ${
                  sessionLight === 'green' ? 'bg-green-500' : 
                  sessionLight === 'yellow' ? 'bg-yellow-400' : 
                  sessionLight === 'red' ? 'bg-red-500' : 'bg-gray-400'
                }`}></span>
                {sessionLight.toUpperCase()} FLAG
              </span>
            )}
            {myTeam && currentStatus && (
              <>
                <span className={`px-3 py-1 rounded text-sm font-medium ${
                  currentStatus === 'Pit-in' 
                    ? isDarkMode ? 'bg-red-900 text-red-200' : 'bg-red-100 text-red-800'
                    : isDarkMode ? 'bg-green-900 text-green-200' : 'bg-green-100 text-green-800'
                }`}>
                  {currentStatus === 'Pit-in' ? 'IN PIT' : 'ON TRACK'}
                </span>
                {isSimulating && (
                  <span className={`px-3 py-1 rounded text-sm ${
                    isDarkMode ? 'bg-blue-900 text-blue-200' : 'bg-blue-100 text-blue-800'
                  }`}>
                    AUTO
                  </span>
                )}
              </>
            )}
          </div>
        </div>

        {/* Driver Management */}
        <div className="space-y-4">
          {/* Add Driver */}
          <div>
            <label className={`block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              Add Driver
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newDriverName}
                onChange={(e) => setNewDriverName(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && addDriver()}
                placeholder="Enter driver name"
                className={`flex-1 p-2 rounded border ${
                  isDarkMode ? 'bg-gray-600 border-gray-500 text-white' : 'bg-white border-gray-300'
                }`}
              />
              <button
                onClick={addDriver}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
              >
                Add
              </button>
            </div>
          </div>

          {/* Driver List */}
          {drivers.length > 0 && (
            <div>
              <label className={`block text-sm font-medium mb-2 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Drivers
              </label>
              <div className="flex flex-wrap gap-2">
                {drivers.map(driver => (
                  <div
                    key={driver.id}
                    className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm ${
                      currentDriver === driver.name 
                        ? 'ring-2 ring-offset-2' 
                        : ''
                    }`}
                    style={{
                      backgroundColor: driver.color + '20',
                      borderColor: driver.color,
                      borderWidth: '2px',
                      borderStyle: 'solid',
                      ...(currentDriver === driver.name && {
                        boxShadow: `0 0 0 2px ${isDarkMode ? '#1f2937' : '#ffffff'}, 0 0 0 4px ${driver.color}`
                      })
                    }}
                  >
                    <button
                      onClick={() => setCurrentDriver(driver.name)}
                      className="font-medium"
                      style={{ color: driver.color }}
                    >
                      {driver.name}
                    </button>
                    <button
                      onClick={() => removeDriver(driver.id)}
                      className={`text-xs ${isDarkMode ? 'text-gray-400 hover:text-gray-200' : 'text-gray-600 hover:text-gray-800'}`}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Stint Controls */}
          <div className="flex gap-2 justify-end">
            {!currentStint || currentStint.status !== 'active' ? (
              <button
                onClick={handleManualStart}
                disabled={!currentDriver}
                className={`px-4 py-2 rounded transition-colors ${
                  currentDriver 
                    ? 'bg-green-600 text-white hover:bg-green-700' 
                    : 'bg-gray-400 text-gray-200 cursor-not-allowed'
                }`}
              >
                Start Stint
              </button>
            ) : (
              <>
                <button
                  onClick={handlePause}
                  className={`px-4 py-2 rounded transition-colors ${
                    isPaused 
                      ? 'bg-yellow-600 text-white hover:bg-yellow-700' 
                      : 'bg-blue-600 text-white hover:bg-blue-700'
                  }`}
                >
                  {isPaused ? 'Resume' : 'Pause'}
                </button>
                <button
                  onClick={handleManualStop}
                  className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
                >
                  End Stint
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Current Stint Timer or Waiting for Green Flag */}
      {currentStint ? (
        <div className={`mb-6 p-6 rounded-lg text-center ${
          currentStint.status === 'pit' 
            ? isDarkMode ? 'bg-yellow-900' : 'bg-yellow-100'
            : isDarkMode ? 'bg-gray-700' : 'bg-gray-100'
        }`}>
          <h3 className="text-xl font-semibold mb-2">
            {currentStint.status === 'pit' ? 'IN PIT' : 'Current Stint'}
          </h3>
          <div className="text-5xl font-mono font-bold mb-2">
            {formatTime(elapsedTime)}
          </div>
          <div className="text-lg flex items-center justify-center gap-2">
            <span
              className="inline-block w-4 h-4 rounded-full"
              style={{ backgroundColor: getDriverColor(currentStint.driver) }}
            ></span>
            {currentStint.driver}
          </div>
          {isPaused && currentStint.status === 'active' && (
            <div className="mt-2 text-yellow-500 font-medium">PAUSED</div>
          )}
        </div>
      ) : (
        isSimulating && myTeam && currentDriver && sessionLight !== 'green' && (
          <div className={`mb-6 p-6 rounded-lg text-center ${
            isDarkMode ? 'bg-gray-700' : 'bg-gray-100'
          }`}>
            <h3 className="text-xl font-semibold mb-2">Waiting for Race Start</h3>
            <div className="text-2xl mb-2">
              {sessionLight === 'red' ? '🔴 Red Flag' : 
               sessionLight === 'yellow' ? '🟡 Yellow Flag' : 
               '⏳ Ready'}
            </div>
            <div className="text-lg opacity-70">
              Stint timer will start automatically when green flag is shown
            </div>
            <div className="text-sm mt-2">
              Driver ready: {currentDriver}
            </div>
          </div>
        )
      )}

      {/* Driver Statistics */}
      <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
        <h3 className="text-lg font-semibold mb-3">Driver Statistics</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {getDriverStats().map(stat => (
            <div 
              key={stat.driver} 
              className={`p-3 rounded border-2 ${isDarkMode ? 'bg-gray-600' : 'bg-white'}`}
              style={{ borderColor: stat.color }}
            >
              <h4 className="font-medium mb-2 flex items-center gap-2">
                <span
                  className="inline-block w-3 h-3 rounded-full"
                  style={{ backgroundColor: stat.color }}
                ></span>
                {stat.driver}
              </h4>
              <div className="text-sm space-y-1">
                <div>Stints: {stat.stints}</div>
                <div>Total Time: {formatTime(stat.totalTime)}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Stint History */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Stint History</h3>
        <div className="overflow-x-auto">
          <table className={`w-full border-collapse ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
            <thead>
              <tr className={isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}>
                <th className={`border p-2 text-left ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  Stint #
                </th>
                <th className={`border p-2 text-left ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  Driver
                </th>
                <th className={`border p-2 text-left ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  Start Time
                </th>
                <th className={`border p-2 text-left ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  Duration
                </th>
                <th className={`border p-2 text-left ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {stintHistory.map((stint, index) => (
                <tr key={stint.id} className={isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'}>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    {index + 1}
                  </td>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block w-3 h-3 rounded-full"
                        style={{ backgroundColor: getDriverColor(stint.driver) }}
                      ></span>
                      {stint.driver}
                    </div>
                  </td>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    {stint.startTime.toLocaleTimeString()}
                  </td>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    {stint.duration ? formatTime(stint.duration) : '-'}
                  </td>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    <span className={`px-2 py-1 rounded text-xs ${
                      stint.status === 'completed'
                        ? isDarkMode ? 'bg-green-900 text-green-200' : 'bg-green-100 text-green-800'
                        : isDarkMode ? 'bg-gray-600 text-gray-200' : 'bg-gray-200 text-gray-800'
                    }`}>
                      {stint.status.toUpperCase()}
                    </span>
                  </td>
                </tr>
              ))}
              {currentStint && (
                <tr className={isDarkMode ? 'bg-gray-700' : 'bg-yellow-50'}>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    {stintHistory.length + 1}
                  </td>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block w-3 h-3 rounded-full"
                        style={{ backgroundColor: getDriverColor(currentStint.driver) }}
                      ></span>
                      {currentStint.driver}
                    </div>
                  </td>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    {currentStint.startTime.toLocaleTimeString()}
                  </td>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    {formatTime(elapsedTime)}
                  </td>
                  <td className={`border p-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                    <span className={`px-2 py-1 rounded text-xs ${
                      currentStint.status === 'active'
                        ? 'bg-blue-600 text-white animate-pulse'
                        : isDarkMode ? 'bg-yellow-900 text-yellow-200' : 'bg-yellow-100 text-yellow-800'
                    }`}>
                      {currentStint.status === 'pit' ? 'IN PIT' : 'ACTIVE'}
                    </span>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default RaceStintTracker;