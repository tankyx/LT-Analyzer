// racing-analyzer/app/components/RaceDashboard/index.tsx
import React, { useState, useEffect } from 'react';
import TimeDeltaChart from './TimeDeltaChart';
import SimulationControls from './SimulationControls';

// Types
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

interface SessionInfo {
  dyn1?: string;
  dyn2?: string;
  light?: string;
}

interface Alert {
  id: number;
  message: string;
  type?: 'info' | 'warning' | 'success' | 'error';
  customContent?: React.ReactNode;
}

interface Trend {
  value: number;
  arrow: number;
}

interface DeltaData {
  gap: number;
  team_name: string;
  position: number;
  last_lap: string;
  best_lap: string;
  pit_stops: string;
  trends: {
    lap_1: Trend;
    lap_5: Trend;
    lap_10: Trend;
  };
}

interface GapHistory {
  [kart: string]: {
    gaps: number[];
    last_update: string;
  };
}

const TrendArrows = ({ trend }: { trend: Trend | undefined }) => {
  if (!trend || trend.arrow === 0) {
    return <span className="text-gray-400">~</span>;
  }
  
  const getArrows = () => {
    const arrow = trend.value < 0 ? '↓' : '↑';  // Down arrow if catching up
    return arrow.repeat(trend.arrow);
  };
  
  const getColor = () => {
    return trend.value < 0 ? 'text-green-600' : 'text-red-600';
  };
  
  return (
    <span className={`font-bold ${getColor()}`}>
      {getArrows()}
    </span>
  );
};

// Star icon component with improved hover effect
const StarIcon = ({ filled, onClick }: { filled: boolean; onClick?: () => void }) => (
  <button 
    onClick={onClick}
    className={`transition-all duration-200 ease-in-out transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-blue-300 rounded-full p-1 min-w-6 ${filled ? 'text-yellow-400 hover:text-yellow-500' : 'text-gray-400 hover:text-gray-600'}`}
  >
    <svg 
      viewBox="0 0 24 24" 
      width="20" 
      height="20" 
      stroke="currentColor" 
      fill={filled ? "currentColor" : "none"}
      strokeWidth="2"
    >
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  </button>
);

// Import the new StatusImageIndicator component
import StatusImageIndicator from './StatusImageIndicator';

const RaceDashboard = () => {
  const [teams, setTeams] = useState<Team[]>([]);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo>({});
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const [myTeam, setMyTeam] = useState<string>('');
  const [monitoredTeams, setMonitoredTeams] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [deltaData, setDeltaData] = useState<Record<string, DeltaData>>({});
  const [gapHistory, setGapHistory] = useState<GapHistory>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);

  const updateMonitoring = async () => {
    try {
      await fetch('http://localhost:5000/api/update-monitoring', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          myTeam,
          monitoredTeams,
        }),
      });
    } catch (error) {
      console.error('Error updating monitoring:', error);
    }
  };

  const startSimulation = async () => {
    try {
      const response = await fetch('http://localhost:5000/api/start-simulation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error('Failed to start simulation');
      }
      
      setSimulating(true);
      setAlerts([...alerts, {
        id: Date.now(),
        message: 'Simulation started successfully',
        type: 'success'
      }]);
      return await response.json();
    } catch (error) {
      console.error('Error starting simulation:', error);
      setAlerts([...alerts, {
        id: Date.now(),
        message: `Failed to start simulation: ${error instanceof Error ? error.message : 'Unknown error'}`,
        type: 'error'
      }]);
      throw error;
    }
  };

  const stopSimulation = async () => {
    try {
      const response = await fetch('http://localhost:5000/api/stop-simulation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error('Failed to stop simulation');
      }
      
      setSimulating(false);
      setAlerts([...alerts, {
        id: Date.now(),
        message: 'Simulation stopped successfully',
        type: 'info'
      }]);
      return await response.json();
    } catch (error) {
      console.error('Error stopping simulation:', error);
      setAlerts([...alerts, {
        id: Date.now(),
        message: `Failed to stop simulation: ${error instanceof Error ? error.message : 'Unknown error'}`,
        type: 'error'
      }]);
      throw error;
    }
  };
  
  const toggleDarkMode = () => {
    setIsDarkMode(!isDarkMode);
  };

  useEffect(() => {
    updateMonitoring();
  }, [myTeam, monitoredTeams]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('http://localhost:5000/api/race-data');
        if (!response.ok) {
          throw new Error('Failed to fetch race data');
        }
        const data = await response.json();
        setTeams(data.teams);
        setSessionInfo(data.session_info);
        setLastUpdate(data.last_update);
        setDeltaData(data.delta_times || {});
        setGapHistory(data.gap_history || {});
        setIsLoading(false);
        checkPitStops(data.teams);
      } catch (error) {
        setError(error instanceof Error ? error.message : 'An error occurred');
        setIsLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 2000); // Shorter interval for simulation
    return () => clearInterval(interval);
  }, []);

  const checkPitStops = (currentTeams: Team[]) => {
    monitoredTeams.forEach(kartNum => {
      const team = currentTeams.find(t => t.Kart === kartNum);
      
      // Check if pit count has increased
      if (team && parseInt(team['Pit Stops']) > (team.lastPitCount || 0)) {
        setAlerts(prev => [...prev, {
          id: Date.now(),
          message: `${team.Team} has entered the pits!`,
          type: 'warning'
        }]);
        team.lastPitCount = parseInt(team['Pit Stops']);
      }
      
      // Check if status has changed to Pit-in
      if (team && team.Status === 'Pit-in') {
        // Create a unique ID for this pit alert
        const pitAlertId = `pit-${team.Kart}-${Date.now()}`;
        
        // Check if we already have an active alert for this team's pit status
        const existingPitAlert = alerts.find(
          alert => alert.message.includes(team.Team) && alert.message.includes('in the pits')
        );
        
        // Only add a new alert if we don't have one for this team already
        if (!existingPitAlert) {
          // Create a more prominent pit alert with custom styling and action buttons
          setAlerts(prev => [...prev, {
            id: Date.now(),
            message: `🔴 ALERT: ${team.Team} is in the pits!`,
            type: 'error', // Use error type for more visibility
            // Adding extra data for styled rendering
            customContent: (
              <div className="flex flex-col">
                <div className="flex items-center">
                  <img 
                    src="https://www.apex-timing.com/live-timing/commonv2/images/st_in.png" 
                    alt="Pit In" 
                    className="w-5 h-5 mr-2" 
                  />
                  <span className="font-bold">{team.Team} (Kart #{team.Kart})</span>
                </div>
                <div className="text-sm mt-1">Currently in the pits - Position: {team.Position}</div>
              </div>
            )
          }]);
          
          // Play a sound alert if browser supports it
          try {
            const audio = new Audio('/notification.mp3');
            audio.play().catch(e => console.log('Audio play prevented by browser', e));
          } catch (e) {
            console.log('Audio not supported', e);
          }
        }
      }
    });
  };

  const toggleTeamMonitoring = (kartNum: string) => {
    setMonitoredTeams(prev => 
      prev.includes(kartNum)
        ? prev.filter(k => k !== kartNum)
        : [...prev, kartNum]
    );
  };

  const dismissAlert = (id: number) => {
    setAlerts(prev => prev.filter(alert => alert.id !== id));
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-lg flex flex-col items-center">
          <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
          Loading race data...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="bg-white rounded-lg shadow-lg p-6 max-w-md">
          <div className="text-red-600 text-xl mb-2">Error</div>
          <p className="text-gray-700">{error}</p>
          <button 
            onClick={() => window.location.reload()}
            className="mt-4 bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`min-h-screen p-4 md:p-6 transition-colors duration-300 ${isDarkMode ? 'bg-gray-900 text-white' : 'bg-gray-50 text-gray-900'}`}>
      <div className={`max-w-7xl mx-auto rounded-xl shadow-lg p-4 md:p-6 transition-colors duration-300 ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}>
        {/* Header */}
        <div className="flex justify-between items-center mb-6 border-b pb-4">
          <h1 className="text-2xl font-bold flex items-center">
            <svg className="w-8 h-8 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <polyline points="8 12 10 14 16 8" />
            </svg>
            Race Analysis Dashboard
          </h1>
          
          <div className="flex items-center gap-4">
            <div className="text-sm flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-500 inline-block animate-pulse"></span>
              Last Update: {lastUpdate || 'N/A'}
            </div>
            <button 
              onClick={toggleDarkMode}
              className={`p-2 rounded-full transition-colors ${isDarkMode ? 'bg-gray-700 text-yellow-300' : 'bg-gray-100 text-gray-600'}`}
              aria-label="Toggle dark mode"
            >
              {isDarkMode ? (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {/* Simulation Controls */}
        <SimulationControls
          onStart={startSimulation}
          onStop={stopSimulation}
          isSimulating={simulating}
          isDarkMode={isDarkMode}
        />

        {/* Team Selection */}
        <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-gray-700' : 'bg-blue-50'}`}>
          <label className={`block text-sm font-medium mb-2 ${isDarkMode ? 'text-gray-200' : 'text-gray-700'}`}>
            My Team
          </label>
          <div className="flex flex-col md:flex-row gap-4 items-start md:items-center">
            <select 
              value={myTeam}
              onChange={(e) => setMyTeam(e.target.value)}
              className={`w-full md:w-1/2 p-2 border rounded-lg ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'}`}
            >
              <option value="">Select Your Team</option>
              {teams.map(team => (
                <option key={team.Kart} value={team.Kart}>
                  {team.Team} (Kart #{team.Kart})
                </option>
              ))}
            </select>
            
            {myTeam && (
              <div className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                {teams.find(t => t.Kart === myTeam)?.Team} - Position: {teams.find(t => t.Kart === myTeam)?.Position || 'N/A'}
              </div>
            )}
          </div>
        </div>

        {/* Session Info */}
        <div className={`rounded-lg p-4 mb-6 ${isDarkMode ? 'bg-gray-700' : 'bg-indigo-50'}`}>
          <div className="flex items-center gap-2 mb-2">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <h2 className="font-semibold">Session Information</h2>
          </div>
          <div className={`text-lg font-medium ${isDarkMode ? 'text-white' : 'text-blue-800'}`}>
            {sessionInfo.dyn1 || 'No session information available'}
          </div>
          {sessionInfo.dyn2 && (
            <div className={`mt-1 ${isDarkMode ? 'text-gray-300' : 'text-blue-600'}`}>
              {sessionInfo.dyn2}
            </div>
          )}
          {sessionInfo.light && (
            <div className="flex items-center mt-2 gap-2">
              <span className={`inline-block w-3 h-3 rounded-full ${sessionInfo.light === 'green' ? 'bg-green-500' : sessionInfo.light === 'red' ? 'bg-red-500' : sessionInfo.light === 'yellow' ? 'bg-yellow-400' : 'bg-gray-400'}`}></span>
              <span className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                {sessionInfo.light.charAt(0).toUpperCase() + sessionInfo.light.slice(1)} flag
              </span>
            </div>
          )}
        </div>

        {/* Alerts */}
        {alerts.length > 0 && (
          <div className="mb-6 space-y-2">
            {alerts.map(alert => {
              const bgColor = alert.type === 'error' ? (isDarkMode ? 'bg-red-900' : 'bg-red-50') :
                             alert.type === 'warning' ? (isDarkMode ? 'bg-yellow-900' : 'bg-yellow-50') : 
                             alert.type === 'success' ? (isDarkMode ? 'bg-green-900' : 'bg-green-50') :
                             (isDarkMode ? 'bg-blue-900' : 'bg-blue-50');
                             
              const textColor = alert.type === 'error' ? (isDarkMode ? 'text-red-200' : 'text-red-700') :
                               alert.type === 'warning' ? (isDarkMode ? 'text-yellow-200' : 'text-yellow-700') : 
                               alert.type === 'success' ? (isDarkMode ? 'text-green-200' : 'text-green-700') :
                               (isDarkMode ? 'text-blue-200' : 'text-blue-700');
              
              return (
                <div key={alert.id} className={`${bgColor} ${textColor} p-4 rounded-lg flex justify-between items-center shadow-sm ${alert.message.includes('in the pits') ? 'pit-alert' : ''}`}>
                  <div className="flex items-center">
                    {alert.type === 'error' && !alert.customContent && (
                      <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                    {alert.type === 'warning' && !alert.customContent && (
                      <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                    )}
                    {alert.type === 'success' && !alert.customContent && (
                      <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                    {alert.type === 'info' && !alert.customContent && (
                      <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                    {alert.customContent || alert.message}
                  </div>
                  <div className="flex items-center gap-2">
                    {alert.message.includes('in the pits') && (
                      <button 
                        onClick={() => {
                          // Scroll to the team in the standings
                          const kartNumber = alert.message.match(/Kart #(\d+)/)?.[1];
                          if (kartNumber) {
                            document.getElementById(`team-${kartNumber}`)?.scrollIntoView({ 
                              behavior: 'smooth',
                              block: 'center'
                            });
                          }
                        }}
                        className={`px-2 py-1 rounded text-xs font-medium ${isDarkMode ? 'bg-gray-700 hover:bg-gray-600 text-white' : 'bg-gray-200 hover:bg-gray-300 text-gray-800'}`}
                      >
                        Locate
                      </button>
                    )}
                    <button 
                      onClick={() => dismissAlert(alert.id)}
                      className={`${isDarkMode ? 'text-gray-400 hover:text-gray-200' : 'text-gray-500 hover:text-gray-700'} transition-colors`}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                      </svg>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Main Data Display */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Left Side - Time Delta Chart and Monitored Teams */}
          <div className="lg:col-span-2 space-y-6">
            {/* Time Delta Chart */}
            <TimeDeltaChart 
              gapHistory={gapHistory} 
              teams={teams} 
              monitoredTeams={monitoredTeams}
              isDarkMode={isDarkMode}
            />
            
            {/* Monitored Teams Panel */}
            <div className={`rounded-lg shadow overflow-hidden transition-colors duration-300 ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}>
              <div className={`px-4 py-3 border-b ${isDarkMode ? 'border-gray-700 bg-gray-700' : 'border-gray-200 bg-gray-50'}`}>
                <h2 className="font-bold text-lg flex items-center gap-2">
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                  </svg>
                  Monitored Teams
                </h2>
              </div>
              
              <div className="p-4">
                {Object.entries(deltaData)
                  .sort((a, b) => a[1].position - b[1].position)
                  .map(([kart, data]) => (
                  <div key={kart} className={`p-3 rounded-lg mb-3 transition-colors ${
                    teams.find(t => t.Kart === kart)?.Status === 'Pit-in' 
                      ? (isDarkMode ? 'bg-red-900/50 hover:bg-red-800/50 border border-red-700' : 'bg-red-50 hover:bg-red-100 border border-red-200')
                      : (isDarkMode ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-50 hover:bg-gray-100')
                  }`}>
                    <div className="flex justify-between items-center mb-1">
                      <div className="flex items-center gap-2">
                        <div className={`text-center min-w-6 rounded-md py-1 ${isDarkMode ? 'bg-gray-600' : 'bg-gray-200'}`}>
                          <span className="font-bold text-sm">P{data.position}</span>
                        </div>
                        <span className="font-bold truncate max-w-[160px]">{data.team_name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`font-bold ${data.gap >= 0 ? 'text-red-600' : 'text-green-600'} flex items-center`}>
                          <span className="w-16 text-right">{data.gap.toFixed(3)}s</span>
                          <div className="ml-1">
                            {data.trends?.lap_1?.arrow > 0 ? (
                              <TrendArrows trend={data.trends.lap_1} />
                            ) : data.trends?.lap_5?.arrow > 0 ? (
                              <TrendArrows trend={data.trends.lap_5} />
                            ) : data.trends?.lap_10?.arrow > 0 ? (
                              <TrendArrows trend={data.trends.lap_10} />
                            ) : (
                              <span className="text-gray-400">~</span>
                            )}
                          </div>
                        </span>
                        <button 
                          onClick={() => toggleTeamMonitoring(kart)}
                          className="p-1 hover:bg-gray-200 rounded-full"
                        >
                          <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    </div>
                    
                    {/* Status indicator for monitored team */}
                    {teams.find(t => t.Kart === kart)?.Status && (
                      <div className="mb-2">
                        <StatusImageIndicator status={teams.find(t => t.Kart === kart)?.Status} />
                      </div>
                    )}
                    
                    <div className={`text-sm grid grid-cols-3 gap-2 mt-2 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                      <div className="flex flex-col">
                        <span className="text-xs opacity-70">Last Lap</span>
                        <span className="font-medium">{data.last_lap}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-xs opacity-70">Best Lap</span>
                        <span className="font-medium">{data.best_lap}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-xs opacity-70">Pit Stops</span>
                        <span className="font-medium">{data.pit_stops}</span>
                      </div>
                    </div>
                  </div>
                ))}
                {Object.keys(deltaData).length === 0 && (
                  <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                    <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                    </svg>
                    <p>No teams monitored yet</p>
                    <p className="text-sm mt-2">Click the star icon next to a team in the standings table to monitor them</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Right Side - Standings Table */}
          <div className={`lg:col-span-3 rounded-lg shadow overflow-hidden transition-colors duration-300 ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}>
            <div className={`px-4 py-3 border-b ${isDarkMode ? 'border-gray-700 bg-gray-700' : 'border-gray-200 bg-gray-50'}`}>
              <h2 className="font-bold text-lg flex items-center gap-2">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                Current Standings
              </h2>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full table-fixed">
                <thead className={`${isDarkMode ? 'bg-gray-700' : 'bg-gray-50'}`}>
                  <tr>
                    <th className="px-4 py-2 text-left w-16">Pos</th>
                    <th className="px-4 py-2 text-left">Team</th>
                    <th className="px-4 py-2 text-left w-28">Last Lap</th>
                    <th className="px-4 py-2 text-left w-28">Best Lap</th>
                    <th className="px-4 py-2 text-right w-20">Gap</th>
                    <th className="px-4 py-2 text-center w-20">Monitor</th>
                  </tr>
                </thead>
                <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
                  {[...teams]
                    .sort((a, b) => parseInt(a.Position) - parseInt(b.Position))
                    .map(team => (
                    <tr 
                      id={`team-${team.Kart}`}
                      key={team.Kart} 
                      className={`
                        transition-colors
                        ${isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'} 
                        ${team.Kart === myTeam ? (isDarkMode ? 'bg-blue-900 hover:bg-blue-800' : 'bg-blue-50 hover:bg-blue-100') : ''}
                        ${team.Status === 'Pit-in' ? (isDarkMode ? 'bg-red-900/40 hover:bg-red-800/40' : 'bg-red-50 hover:bg-red-100') : ''}
                        ${monitoredTeams.includes(team.Kart) && team.Status === 'Pit-in' ? 'pit-alert' : ''}
                      `}
                    >
                      <td className="px-4 py-3">
                        <div className={`font-medium text-center rounded-full w-8 h-8 flex items-center justify-center ${parseInt(team.Position) <= 3 ? (isDarkMode ? 'bg-yellow-700 text-yellow-100' : 'bg-yellow-100 text-yellow-800') : (isDarkMode ? 'bg-gray-700 text-gray-200' : 'bg-gray-100 text-gray-800')}`}>
                          {team.Position}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col">
                          <div className="font-medium truncate max-w-[200px]">{team.Team}</div>
                          <div className="flex items-center gap-2">
                            <span className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>Kart #{team.Kart}</span>
                            {team.Status && <StatusImageIndicator status={team.Status} size="sm" />}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">{team['Last Lap']}</td>
                      <td className="px-4 py-3">{team['Best Lap']}</td>
                      <td className="px-4 py-3 text-right">{team.Gap}</td>
                      <td className="px-4 py-3 text-center">
                        <StarIcon 
                          filled={monitoredTeams.includes(team.Kart)} 
                          onClick={() => toggleTeamMonitoring(team.Kart)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RaceDashboard;
