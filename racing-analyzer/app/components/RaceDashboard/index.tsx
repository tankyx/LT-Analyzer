import React, { useState, useEffect, useMemo, useCallback  } from 'react';
import TimeDeltaChart from './TimeDeltaChart';
import SimulationControls from './SimulationControls';
import TabbedInterface from './TabbedInterface';
import ApiService from '../../services/ApiService';
import webSocketService, { RaceDataUpdate, TeamsUpdate, GapUpdate, SessionUpdate, MonitoringUpdate, PitConfigUpdate } from '../../services/WebSocketService';
import StatusImageIndicator from './StatusImageIndicator';
import ClassFilter from './ClassFilter';
import PitStopConfig from './PitStopConfig';
import StintPlanner from './StintPlanner';
import AdminPanel from './AdminPanel';
import { useAuth } from '../../contexts/AuthContext';

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
  teamKart?: string; // Add team identifier for pit alerts
}

interface Trend {
  value: number;
  arrow: number;
}

interface DeltaData {
  gap: number;
  adjusted_gap?: number;
  team_name: string;
  position: number;
  last_lap: string;
  best_lap: string;
  pit_stops: string;
  remaining_stops?: number;
  trends: {
    lap_1: Trend;
    lap_5: Trend;
    lap_10: Trend;
  };
  adjusted_trends?: {
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
    const arrow = trend.value < 0 ? '↓' : '↑';
    return arrow.repeat(trend.arrow);
  };
  
  const getColor = () => {
    // Simplified logic based on trend direction
    return trend.value < 0 ? 'text-green-600' : 'text-red-600';
  };
  
  return (
    <span className={`font-bold ${getColor()}`}>
      {getArrows()}
    </span>
  );
};

// Helper function to parse time string to seconds
const parseTimeToSeconds = (timeStr: string): number => {
  // Handle MM:SS.sss or MM:SS:sss format
  if (timeStr.includes(':')) {
    const parts = timeStr.split(':');
    if (parts.length === 2) {
      const minutes = parseInt(parts[0]);
      const seconds = parseFloat(parts[1].replace(',', '.'));
      return minutes * 60 + seconds;
    } else if (parts.length === 3) {
      // Handle MM:SS:sss format (sometimes used)
      const minutes = parseInt(parts[0]);
      const seconds = parseInt(parts[1]);
      const milliseconds = parseInt(parts[2]) / 1000;
      return minutes * 60 + seconds + milliseconds;
    }
  }
  // Just seconds
  return parseFloat(timeStr.replace(',', '.'));
};

// Helper function to calculate gaps between teams
const calculateTeamGaps = (teams: Team[], myTeamKart: string, monitoredKarts: string[], pitStopTime: number, requiredPitStops: number): Record<string, DeltaData> => {
  const myTeam = teams.find(t => t.Kart === myTeamKart);
  if (!myTeam) return {};

  const myPitStops = parseInt(myTeam['Pit Stops'] || '0');
  const myRemainingStops = Math.max(0, requiredPitStops - myPitStops);
  
  // Parse my team's gap
  let myGapToLeader = 0;
  let myLapsBehind = 0;
  if (myTeam.Position !== '1') {
    const gapStr = myTeam.Gap;
    // Handle lapped teams
    if (gapStr.includes('Tour')) {
      myLapsBehind = parseInt(gapStr.split(' ')[0]);
      // Use my last lap time or default
      const avgLapTime = myTeam['Last Lap'] && myTeam['Last Lap'].includes(':') 
        ? parseTimeToSeconds(myTeam['Last Lap'])
        : 90;
      myGapToLeader = myLapsBehind * avgLapTime;
    } else {
      try {
        myGapToLeader = parseTimeToSeconds(gapStr);
      } catch {
        myGapToLeader = 0;
      }
    }
  }
  
  // Count laps difference between positions
  const countLapDifference = (myPos: number, monPos: number): number => {
    if (myPos === monPos) return 0;
    
    const startPos = Math.min(myPos, monPos);
    const endPos = Math.max(myPos, monPos);
    let lapDiff = 0;
    
    // Check all teams between the two positions
    teams.forEach(t => {
      const teamPos = parseInt(t.Position);
      if (startPos < teamPos && teamPos < endPos) {
        if (t.Gap.includes('Tour')) {
          lapDiff += parseInt(t.Gap.split(' ')[0]);
        }
      }
    });
    
    return lapDiff;
  };
  
  const myPosition = parseInt(myTeam.Position);

  const deltas: Record<string, DeltaData> = {};

  monitoredKarts.forEach(kart => {
    const monitoredTeam = teams.find(t => t.Kart === kart);
    if (!monitoredTeam) return;

    const monPitStops = parseInt(monitoredTeam['Pit Stops'] || '0');
    const monRemainingStops = Math.max(0, requiredPitStops - monPitStops);
    
    const monPosition = parseInt(monitoredTeam.Position);
    
    // Parse monitored team's gap
    let monGapToLeader = 0;
    let monLapsBehind = 0;
    if (monPosition !== 1) {
      const gapStr = monitoredTeam.Gap;
      // Handle lapped teams and special cases
      if (gapStr.includes('Tour')) {
        // Check if this is P1 showing total laps (e.g., "Tour 56")
        if (monPosition === 1) {
          // This is the winner showing total laps completed
          monGapToLeader = 0; // Leader has no gap
          monLapsBehind = 0;
        } else {
          // This is laps behind the leader (e.g., "1 Tour", "2 Tours")
          monLapsBehind = parseInt(gapStr.split(' ')[0]);
          
          // Check if there are lapped teams between us
          const lapsBetween = countLapDifference(myPosition, monPosition);
          
          // Calculate actual lap difference
          let actualLapDiff = 0;
          if (myPosition < monPosition) {
            // Monitored team is behind us
            actualLapDiff = monLapsBehind - myLapsBehind - lapsBetween;
          } else {
            // Monitored team is ahead of us
            actualLapDiff = monLapsBehind - myLapsBehind + lapsBetween;
          }
          
          // If actual lap diff is 0, we're on the same lap
          if (actualLapDiff === 0) {
            // We're on the same lap, calculate based on position
            // This will be handled by the normal gap calculation below
            monGapToLeader = myGapToLeader; // Start with same base
          } else {
            // Different laps, calculate based on lap difference using best lap time
            const bestLapTime = monitoredTeam['Best Lap'] && monitoredTeam['Best Lap'].includes(':') 
              ? parseTimeToSeconds(monitoredTeam['Best Lap'])
              : 90;
            monGapToLeader = myGapToLeader + (actualLapDiff * bestLapTime);
          }
        }
      } else {
        // Gap is in seconds (time format)
        try {
          monGapToLeader = parseTimeToSeconds(gapStr);
          
          // Check if there are lapped teams between us
          const lapsBetween = countLapDifference(myPosition, monPosition);
          
          // If there are lapped teams between us, we need to account for the lap difference
          if (lapsBetween > 0) {
            const bestLapTime = monitoredTeam['Best Lap'] && monitoredTeam['Best Lap'].includes(':') 
              ? parseTimeToSeconds(monitoredTeam['Best Lap'])
              : 90;
            
            if (myPosition < monPosition) {
              // Monitored team is behind us but with lapped teams in between
              monGapToLeader += lapsBetween * bestLapTime;
            } else {
              // Monitored team is ahead of us but with lapped teams in between
              monGapToLeader -= lapsBetween * bestLapTime;
            }
          }
          // If no lapped teams between us, we're on the same lap and can use the gap as is
        } catch {
          monGapToLeader = 0;
        }
      }
    }

    // Calculate real gap including pit stop compensation for completed stops
    // Using 150 second compensation as base (standard Apex Timing value)
    const realGap = (monGapToLeader - myGapToLeader) + ((monPitStops - myPitStops) * 150);
    
    // Calculate adjusted gap accounting for remaining required pit stops
    const adjustedGap = realGap + ((monRemainingStops - myRemainingStops) * pitStopTime);

    deltas[kart] = {
      gap: Math.round(realGap * 1000) / 1000, // Round to 3 decimals
      adjusted_gap: Math.round(adjustedGap * 1000) / 1000,
      team_name: monitoredTeam.Team,
      position: parseInt(monitoredTeam.Position),
      last_lap: monitoredTeam['Last Lap'],
      best_lap: monitoredTeam['Best Lap'],
      pit_stops: monitoredTeam['Pit Stops'],
      remaining_stops: monRemainingStops,
      trends: {
        lap_1: { value: 0, arrow: 0 },
        lap_5: { value: 0, arrow: 0 },
        lap_10: { value: 0, arrow: 0 }
      },
      adjusted_trends: {
        lap_1: { value: 0, arrow: 0 },
        lap_5: { value: 0, arrow: 0 },
        lap_10: { value: 0, arrow: 0 }
      }
    };
  });

  return deltas;
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

const RaceDashboard = () => {
  const { user, logout } = useAuth();
  const [teams, setTeams] = useState<Team[]>([]);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo>({});
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const [myTeam, setMyTeam] = useState<string>('');
  const [monitoredTeams, setMonitoredTeams] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [deltaData, setDeltaData] = useState<Record<string, DeltaData>>({});
  const [gapHistory, setGapHistory] = useState<GapHistory>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null); // eslint-disable-line @typescript-eslint/no-unused-vars
  const [simulating, setSimulating] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [teamColors, setTeamColors] = useState<Record<string, string>>({});
  const [hoveredTeam, setHoveredTeam] = useState<string | null>(null);
  const [selectedClass, setSelectedClass] = useState<string>('all');
  const [showAdjustedGap, setShowAdjustedGap] = useState(false);
  const [pitStopTime, setPitStopTime] = useState(158);
  const [alertedPitTeams, setAlertedPitTeams] = useState<Set<string>>(new Set());
  const [requiredPitStops, setRequiredPitStops] = useState(7);
  const [defaultLapTime, setDefaultLapTime] = useState(90);
  const [isSimulationMode, setIsSimulationMode] = useState(false);
  const [raceData, setRaceData] = useState<{
    timing_url?: string;
    [key: string]: unknown;
  } | null>(null);
  const [updatedRows, setUpdatedRows] = useState<Map<string, number>>(new Map()); // Track updated rows with timestamps
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');

  const updatePitStopConfig = useCallback(async (newPitTime: number, newRequiredStops: number, newDefaultLapTime?: number) => {
    try {
      await ApiService.updatePitStopConfig({
        pitStopTime: newPitTime,
        requiredPitStops: newRequiredStops,
        defaultLapTime: newDefaultLapTime ?? defaultLapTime
      });
      
      setAlerts(prev => [...prev, {
        id: Date.now(),
        message: 'Pit stop settings updated successfully',
        type: 'success'
      }]);
    } catch (error) {
      console.error('Error updating pit stop config:', error);
      setAlerts(prev => [...prev, {
        id: Date.now(),
        message: `Failed to update pit stop settings: ${error instanceof Error ? error.message : 'Unknown error'}`,
        type: 'error'
      }]);
    }
  }, [defaultLapTime]);

  const getTeamClass = (teamName: string): string | null => {
    if (teamName.startsWith('1 - ')) return '1';
    if (teamName.startsWith('2 - ')) return '2';
    return null; // No class prefix - could consider this as a default class if needed
  };

  const filteredTeams = useMemo(() => {
    if (selectedClass === 'all') return teams;
    
    return teams.filter(team => {
      const teamClass = getTeamClass(team.Team);
      return teamClass === selectedClass;
    });
  }, [teams, selectedClass]);

  const teamCounts = useMemo(() => {
    const counts = {
      all: teams.length,
      '1': 0,
      '2': 0
    };
    
    teams.forEach(team => {
      const teamClass = getTeamClass(team.Team);
      if (teamClass === '1') counts['1']++;
      if (teamClass === '2') counts['2']++;
    });
    
    return counts;
  }, [teams]);

  // Calculate gaps locally in the frontend
  const frontendDeltaData = useMemo(() => {
    if (!myTeam || monitoredTeams.length === 0 || teams.length === 0) {
      return {};
    }
    return calculateTeamGaps(teams, myTeam, monitoredTeams, pitStopTime, requiredPitStops);
  }, [teams, myTeam, monitoredTeams, pitStopTime, requiredPitStops]);
    
  const handleTeamHover = (kartNum: string | null) => {
    setHoveredTeam(kartNum);
  };

  const handleColorAssignment = (colors: Record<string, string>) => {
    setTeamColors(colors);
  };
  
  const updateMonitoring = useCallback(async () => {
    try {
      await ApiService.updateMonitoring({
        myTeam,
        monitoredTeams,
      });
    } catch (error) {
      console.error('Error updating monitoring:', error);
    }
  }, [myTeam, monitoredTeams]);

  const startSimulation = async (isSimulationMode: boolean = false, timingUrl?: string, websocketUrl?: string, trackId?: number) => {
    try {
      const response = await ApiService.startSimulation(isSimulationMode, timingUrl, websocketUrl, trackId);
    
      setSimulating(true);
      setAlerts([...alerts, {
        id: Date.now(),
        message: isSimulationMode ? 'Simulation mode started successfully' : 'Real data collection started successfully',
        type: 'success'
      }]);
      return response;
    } catch (error) {
      console.error('Error starting:', error);
      setAlerts([...alerts, {
        id: Date.now(),
        message: `Failed to start: ${error instanceof Error ? error.message : 'Unknown error'}`,
        type: 'error'
      }]);
      throw error;
    }
  };

  const stopSimulation = async () => {
    try {
      const response = await ApiService.stopSimulation();
    
      setSimulating(false);
      setAlerts([...alerts, {
        id: Date.now(),
        message: 'Simulation stopped successfully',
        type: 'info'
      }]);
      return response;
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

  const checkPitStops = useCallback((currentTeams: Team[]) => {
    monitoredTeams.forEach(kartNum => {
      const team = currentTeams.find(t => t.Kart === kartNum);
      
      // Check if status has changed to Pit-in
      if (team && team.Status === 'Pit-in') {
        // Check if we already alerted for this team
        if (!alertedPitTeams.has(team.Kart)) {
          // Mark this team as alerted
          setAlertedPitTeams(prev => new Set(prev).add(team.Kart));
          
          // Create a more prominent pit alert with custom styling and action buttons
          setAlerts(prev => [...prev, {
            id: Date.now(),
            message: `🔴 ALERT: ${team.Team} is in the pits!`,
            type: 'error', // Use error type for more visibility
            teamKart: team.Kart, // Add team identifier
            // Adding extra data for styled rendering
            customContent: (
              <div className="flex flex-col">
                <div className="flex items-center">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
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
      } else if (team && team.Status !== 'Pit-in') {
        // Team is no longer in pit, remove from alerted set
        setAlertedPitTeams(prev => {
          const newSet = new Set(prev);
          newSet.delete(team.Kart);
          return newSet;
        });
        
        // Remove the pit alert for this team
        setAlerts(prev => prev.filter(alert => alert.teamKart !== team.Kart));
      }
    });
  }, [monitoredTeams, alertedPitTeams]);

  // Auto-dismiss alerts after 5 seconds
  useEffect(() => {
    if (alerts.length > 0) {
      const timer = setTimeout(() => {
        setAlerts(prev => prev.slice(1)); // Remove oldest alert
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [alerts]);

  // Update monitoring via API only when user changes it locally
  const [isUserUpdate, setIsUserUpdate] = useState(false);
  
  useEffect(() => {
    // Only call API if this is a user-initiated change and we're connected
    if (isUserUpdate && connectionStatus === 'connected') {
      updateMonitoring();
      setIsUserUpdate(false);
    }
  }, [myTeam, monitoredTeams, updateMonitoring, connectionStatus, isUserUpdate]);

  // WebSocket connection and data handling
  useEffect(() => {
    // Helper function to detect changes and update rows
    const detectChanges = (newTeams: Team[]) => {
      if (newTeams && teams.length > 0) {
        const currentTime = Date.now();
        const newUpdatedRows = new Map(updatedRows);
        
        newTeams.forEach((newTeam: Team) => {
          const oldTeam = teams.find(t => t.Kart === newTeam.Kart);
          if (oldTeam) {
            // Check if any critical fields have changed
            const hasChanged = 
              oldTeam.Position !== newTeam.Position ||
              oldTeam['Last Lap'] !== newTeam['Last Lap'] ||
              oldTeam['Best Lap'] !== newTeam['Best Lap'] ||
              oldTeam.Gap !== newTeam.Gap ||
              oldTeam['Pit Stops'] !== newTeam['Pit Stops'] ||
              oldTeam.Status !== newTeam.Status;
            
            if (hasChanged) {
              console.log(`Row updated: Kart ${newTeam.Kart} - Position: ${oldTeam.Position} -> ${newTeam.Position}, Last Lap: ${oldTeam['Last Lap']} -> ${newTeam['Last Lap']}`);
              newUpdatedRows.set(newTeam.Kart, currentTime);
            }
          }
        });
        
        // Clean up old entries (older than 5 seconds)
        newUpdatedRows.forEach((timestamp, kart) => {
          if (currentTime - timestamp > 5000) {
            newUpdatedRows.delete(kart);
          }
        });
        
        setUpdatedRows(newUpdatedRows);
      }
    };

    // Set up WebSocket callbacks
    webSocketService.setCallbacks({
      onConnectionStatusChange: (status) => {
        setConnectionStatus(status);
        console.log('WebSocket connection status:', status);
      },
      
      onRaceDataUpdate: (data: RaceDataUpdate) => {
        console.log('Received full race data update');
        detectChanges(data.teams);
        setTeams(data.teams || []);
        setSessionInfo(data.session_info || {});
        setLastUpdate(data.last_update || '');
        setDeltaData(data.delta_times || {});
        setGapHistory(data.gap_history || {});
        setIsSimulationMode(data.simulation_mode || false);
        setMyTeam(data.my_team || '');
        setMonitoredTeams(data.monitored_teams || []);
        setPitStopTime(data.pit_config?.pit_time || 158);
        setRequiredPitStops(data.pit_config?.required_stops || 7);
        setDefaultLapTime(data.pit_config?.default_lap_time || 90);
        setRaceData({
          ...data,
          timing_url: data.timing_url || undefined
        });
        setIsLoading(false);
        setError(null);
        if (data.teams && data.teams.length > 0) {
          checkPitStops(data.teams);
        }
      },
      
      onTeamsUpdate: (data: TeamsUpdate) => {
        console.log('Received teams update');
        detectChanges(data.teams);
        setTeams(data.teams || []);
        setLastUpdate(data.last_update || '');
        if (data.teams && data.teams.length > 0) {
          checkPitStops(data.teams);
        }
      },
      
      onGapUpdate: (data: GapUpdate) => {
        console.log('Received gap update');
        setDeltaData(data.delta_times || {});
        setGapHistory(data.gap_history || {});
      },
      
      onSessionUpdate: (data: SessionUpdate) => {
        console.log('Received session update');
        setSessionInfo(data.session_info || {});
      },
      
      onMonitoringUpdate: (data: MonitoringUpdate) => {
        console.log('Received monitoring update');
        setMyTeam(data.my_team || '');
        setMonitoredTeams(data.monitored_teams || []);
      },
      
      onPitConfigUpdate: (data: PitConfigUpdate) => {
        console.log('Received pit config update');
        setPitStopTime(data.pit_time || 158);
        setRequiredPitStops(data.required_stops || 7);
        if (data.default_lap_time !== undefined) {
          setDefaultLapTime(data.default_lap_time);
        }
      },
      
      onRaceDataReset: () => {
        console.log('Received race data reset');
        // Reset all race-related state
        setTeams([]);
        setSessionInfo({});
        setLastUpdate('');
        setDeltaData({});
        setGapHistory({});
        setAlertedPitTeams(new Set());
        setUpdatedRows(new Map());
        setRaceData(null);
        setIsLoading(true);
        setError(null);
        setAlerts(prev => [...prev, {
          id: Date.now(),
          message: 'Race data cleared - ready for new track',
          type: 'info'
        }]);
      }
    });

    return () => {
      // Clean up WebSocket callbacks on unmount
      webSocketService.removeCallbacks();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkPitStops]); // Only run on mount, teams and updatedRows changes are handled internally

  const toggleTeamMonitoring = (kartNum: string) => {
    setIsUserUpdate(true);
    setMonitoredTeams(prev => 
      prev.includes(kartNum)
        ? prev.filter(k => k !== kartNum)
        : [...prev, kartNum]
    );
  };

  const dismissAlert = (id: number) => {
    setAlerts(prev => prev.filter(alert => alert.id !== id));
  };

  if (isLoading && connectionStatus === 'disconnected') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-lg flex flex-col items-center">
          <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
          Connecting to race data server...
        </div>
      </div>
    );
  }

  // Don't show error screen - we'll handle empty data gracefully in the UI
  // if (error) { ... }

  const StandingsTab = (
    <div className="p-4">
      {/* Add class filter at the top */}
      <ClassFilter
        selectedClass={selectedClass}
        onClassChange={setSelectedClass}
        isDarkMode={isDarkMode}
        teamCount={teamCounts}
      />
      
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
          {/* Use filteredTeams instead of teams */}
          {filteredTeams.length > 0 ? (
            [...filteredTeams]
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
                    ${updatedRows.has(team.Kart) ? 'row-updated' : ''}
                  `}
                  style={monitoredTeams.includes(team.Kart) ? { 
                    borderLeft: `4px solid ${teamColors[team.Kart] || 'transparent'}`
                  } : {}}
                >
                  <td className="px-4 py-3">
                    <div className={`font-medium text-center rounded-full w-8 h-8 flex items-center justify-center ${parseInt(team.Position) <= 3 ? (isDarkMode ? 'bg-yellow-700 text-yellow-100' : 'bg-yellow-100 text-yellow-800') : (isDarkMode ? 'bg-gray-700 text-gray-200' : 'bg-gray-100 text-gray-800')}`}>
                      {team.Position}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col">
                      <div className="font-medium truncate max-w-[200px] flex items-center">
                        {monitoredTeams.includes(team.Kart) && (
                          <div 
                            className="w-3 h-3 rounded-full mr-2 flex-shrink-0" 
                            style={{ backgroundColor: teamColors[team.Kart] || 'transparent' }}
                          ></div>
                        )}
                        {team.Team}
                        
                        {/* Add class badge if we can determine the class */}
                        {getTeamClass(team.Team) && (
                          <span 
                            className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
                              getTeamClass(team.Team) === '1' 
                                ? (isDarkMode ? 'bg-purple-900 text-purple-100' : 'bg-purple-100 text-purple-800')
                                : (isDarkMode ? 'bg-green-900 text-green-100' : 'bg-green-100 text-green-800')
                            }`}
                          >
                            Class {getTeamClass(team.Team)}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>Kart #{team.Kart}</span>
                        {team.Status !== undefined && <StatusImageIndicator status={team.Status} size="sm" />}
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
              ))
          ) : (
            <tr className={`${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              <td colSpan={6} className="px-4 py-8 text-center">
                <div className="flex flex-col items-center">
                  {teams.length === 0 ? (
                    // No data at all
                    <>
                      <svg className="w-16 h-16 mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <p className="text-lg font-medium mb-2">No race data available</p>
                      <p className="text-sm mb-4">Click &quot;Start Simulation&quot; to begin loading race data</p>
                      {!simulating && (
                        <button 
                          onClick={() => startSimulation(false, undefined, 'hybrid')}
                          className={`px-6 py-2 rounded-md transition-colors font-medium ${isDarkMode ? 'bg-blue-600 hover:bg-blue-700 text-white' : 'bg-blue-500 hover:bg-blue-600 text-white'}`}
                        >
                          Start Simulation
                        </button>
                      )}
                    </>
                  ) : (
                    // No teams in selected class
                    <>
                      <svg className="w-12 h-12 mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                      </svg>
                      <p className="text-lg font-medium">No teams found in this class</p>
                      <button 
                        onClick={() => setSelectedClass('all')}
                        className={`mt-4 px-4 py-2 rounded-md transition-colors ${isDarkMode ? 'bg-gray-700 hover:bg-gray-600 text-gray-200' : 'bg-gray-100 hover:bg-gray-200 text-gray-800'}`}
                      >
                        Show all teams
                      </button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );

  const MonitoredTeamsTab = (
    <div className="p-4">
      <div className={`rounded-lg border overflow-hidden transition-colors duration-300 ${isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'}`}>
        <div className={`px-4 py-3 border-b ${isDarkMode ? 'border-gray-700 bg-gray-700' : 'border-gray-200 bg-gray-50'}`}>
          <div className="flex justify-between items-center">
            <h2 className="font-bold text-lg flex items-center gap-2">
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
              </svg>
              Monitored Teams
            </h2>
            
            {/* Add gap mode toggle for monitored teams */}
            <div className="flex items-center space-x-2">
              <span className={`text-xs ${showAdjustedGap ? (isDarkMode ? 'text-gray-400' : 'text-gray-500') : (isDarkMode ? 'text-blue-300' : 'text-blue-600')}`}>
                Regular
              </span>
              <button 
                onClick={() => setShowAdjustedGap(!showAdjustedGap)}
                className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors ${showAdjustedGap ? (isDarkMode ? 'bg-blue-600' : 'bg-blue-500') : (isDarkMode ? 'bg-gray-600' : 'bg-gray-300')}`}
              >
                <span 
                  className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${showAdjustedGap ? 'translate-x-5' : 'translate-x-1'}`} 
                />
              </button>
              <span className={`text-xs ${showAdjustedGap ? (isDarkMode ? 'text-blue-300' : 'text-blue-600') : (isDarkMode ? 'text-gray-400' : 'text-gray-500')}`}>
                Adjusted
              </span>
            </div>
          </div>
        </div>
        
        <div className="p-4">
          {Object.entries(frontendDeltaData)
            .sort((a, b) => a[1].position - b[1].position)
            .map(([kart, data]) => (
            <div key={kart} className={`p-3 rounded-lg mb-3 transition-colors ${
              teams.find(t => t.Kart === kart)?.Status === 'Pit-in' 
                ? (isDarkMode ? 'bg-red-900/50 hover:bg-red-800/50 border border-red-700' : 'bg-red-50 hover:bg-red-100 border border-red-200')
                : (isDarkMode ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-50 hover:bg-gray-100')
              } ${hoveredTeam === kart ? 'ring-2 ring-blue-500' : ''}`}
              style={{
                borderLeft: `4px solid ${teamColors[kart] || 'transparent'}`
              }}
            >
              <div className="flex justify-between items-center mb-1">
                <div className="flex items-center gap-2">
                  <div className={`text-center min-w-6 rounded-md px-2 py-1 ${isDarkMode ? 'bg-gray-600' : 'bg-gray-200'}`}>
                    <span className="font-bold text-sm">P{data.position}</span>
                  </div>
                  <span className="font-bold truncate max-w-[160px]">{data.team_name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`font-bold ${(showAdjustedGap ? (data.adjusted_gap ?? data.gap) : data.gap) >= 0 ? 'text-red-600' : 'text-green-600'} flex items-center`}>
                    <span className="w-16 text-right">
                      {(showAdjustedGap ? (data.adjusted_gap ?? data.gap) : data.gap).toFixed(3)}s
                      {showAdjustedGap && (
                        <span className="ml-1 text-xs text-blue-500">*</span>
                      )}
                    </span>
                    <div className="ml-1">
                      {data.trends?.lap_1?.arrow > 0 ? (
                        <TrendArrows trend={showAdjustedGap ? data.adjusted_trends?.lap_1 : data.trends.lap_1} />
                      ) : data.trends?.lap_5?.arrow > 0 ? (
                        <TrendArrows trend={showAdjustedGap ? data.adjusted_trends?.lap_5 : data.trends.lap_5} />
                      ) : data.trends?.lap_10?.arrow > 0 ? (
                        <TrendArrows trend={showAdjustedGap ? data.adjusted_trends?.lap_10 : data.trends.lap_10} />
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
              <div className="flex justify-between items-center">
                <div>
                  {teams.find(t => t.Kart === kart)?.Status !== undefined && (
                    <StatusImageIndicator status={teams.find(t => t.Kart === kart)?.Status} />
                  )}
                </div>
                
                {/* Add pit stop indicator */}
                {showAdjustedGap && data.remaining_stops !== undefined && (
                  <div className={`text-xs rounded-full px-2 py-1 ${isDarkMode ? 'bg-blue-900 text-blue-100' : 'bg-blue-50 text-blue-800'}`}>
                    {data.remaining_stops > 0 ? (
                      <>Remaining stops: <span className="font-bold">{data.remaining_stops}</span></>
                    ) : (
                      <>All pit stops completed</>
                    )}
                  </div>
                )}
              </div>
              
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
          {Object.keys(frontendDeltaData).length === 0 && (
            <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
              </svg>
              <p>No teams monitored yet</p>
              <p className="text-sm mt-2">Click the star icon next to a team in the standings table to monitor them</p>
            </div>
          )}
        </div>
        
        {/* Add explanation for adjusted gap */}
        {showAdjustedGap && Object.keys(deltaData).length > 0 && (
          <div className={`px-4 py-2 text-xs border-t ${isDarkMode ? 'border-gray-700 bg-gray-700/50 text-gray-300' : 'border-gray-200 bg-gray-50 text-gray-600'}`}>
            <div className="flex items-center">
              <svg className="w-4 h-4 mr-1 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Adjusted gap accounts for remaining pit stops (2:38 per stop)
            </div>
          </div>
        )}
      </div>
    </div>
  );

  const ChartTab = (
    <div className="p-4">
      {/* Time Delta Chart */}
      <TimeDeltaChart 
        gapHistory={gapHistory} 
        teams={teams} 
        monitoredTeams={monitoredTeams}
        isDarkMode={isDarkMode}
        onColorAssignment={handleColorAssignment}
        onTeamHover={handleTeamHover}
        pitStopTime={pitStopTime}
        requiredPitStops={requiredPitStops}
      />
      
      {/* Quick guide section for the chart */}
      <div className={`mt-4 p-4 rounded-lg border ${isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-gray-50 border-gray-200'}`}>
        <h3 className={`text-sm font-medium mb-2 ${isDarkMode ? 'text-gray-200' : 'text-gray-700'}`}>
          Chart Guide
        </h3>
        <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="flex items-center gap-2">
              <div className="flex items-center">
                <div className="h-px w-5 bg-gray-400"></div>
                <div className="h-3 w-3 rounded-full bg-gray-400"></div>
              </div>
              <span>Teams on track</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center">
                <div className="h-px w-5 bg-gray-400 dashed-line"></div>
                <div className="h-3 w-3 rounded-full bg-red-400"></div>
              </div>
              <span>Teams in pits</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-green-500">▼</span>
              <span>Getting closer to you</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-red-500">▲</span>
              <span>Falling behind you</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

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
            {user && (
              <div className="flex items-center gap-4">
                <span className="text-sm text-gray-500">
                  {user.username}
                  {user.role === 'admin' && (
                    <span className="ml-2 px-2 py-1 text-xs bg-purple-600 text-white rounded">Admin</span>
                  )}
                </span>
                <button
                  onClick={logout}
                  className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
                >
                  Logout
                </button>
              </div>
            )}
            <div className="text-sm flex items-center gap-1">
              {teams.length > 0 ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-green-500 inline-block animate-pulse"></span>
                  Last Update: {lastUpdate || 'N/A'}
                </>
              ) : (
                <span className="text-gray-500">No active session</span>
              )}
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
          isSimulationMode={isSimulationMode}
          currentTimingUrl={raceData?.timing_url as string | undefined}
        />
        
        {/* Pit Stop Config */}
        {monitoredTeams.length > 0 && (
          <PitStopConfig
            pitStopTime={pitStopTime}
            setPitStopTime={(newTime) => {
              setPitStopTime(newTime);
              updatePitStopConfig(newTime, requiredPitStops, defaultLapTime);
            }}
            requiredPitStops={requiredPitStops}
            setRequiredPitStops={(newStops) => {
              setRequiredPitStops(newStops);
              updatePitStopConfig(pitStopTime, newStops, defaultLapTime);
            }}
            defaultLapTime={defaultLapTime}
            setDefaultLapTime={(newTime) => {
              setDefaultLapTime(newTime);
              updatePitStopConfig(pitStopTime, requiredPitStops, newTime);
            }}
            isDarkMode={isDarkMode}
          />
        )}

        {/* Team Selection */}
        <div className={`mb-6 p-4 rounded-lg ${isDarkMode ? 'bg-gray-700' : 'bg-blue-50'}`}>
          <label className={`block text-sm font-medium mb-2 ${isDarkMode ? 'text-gray-200' : 'text-gray-700'}`}>
            My Team
          </label>
          <div className="flex flex-col md:flex-row gap-4 items-start md:items-center">
            <select 
              value={myTeam}
              onChange={(e) => {
                setIsUserUpdate(true);
                setMyTeam(e.target.value);
              }}
              className={`w-full md:w-1/2 p-2 border rounded-lg ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'}`}
            >
              <option value="">Select Your Team</option>
              {teams.length > 0 ? (
                teams.map(team => (
                  <option key={team.Kart} value={team.Kart}>
                    {team.Team} (Kart #{team.Kart})
                  </option>
                ))
              ) : (
                <option value="" disabled>No teams available - Start simulation to load data</option>
              )}
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
            {sessionInfo.dyn1 || (teams.length === 0 ? 'No active session - Start simulation to begin' : 'No session information available')}
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

        {/* Connection Status */}
        <div className="mb-4">
          <div className={`inline-flex items-center px-3 py-1 rounded-full text-sm ${
            connectionStatus === 'connected' 
              ? isDarkMode ? 'bg-green-900 text-green-200' : 'bg-green-100 text-green-700'
              : connectionStatus === 'connecting'
              ? isDarkMode ? 'bg-yellow-900 text-yellow-200' : 'bg-yellow-100 text-yellow-700'
              : isDarkMode ? 'bg-red-900 text-red-200' : 'bg-red-100 text-red-700'
          }`}>
            <div className={`w-2 h-2 rounded-full mr-2 ${
              connectionStatus === 'connected' ? 'bg-green-500' :
              connectionStatus === 'connecting' ? 'bg-yellow-500 animate-pulse' :
              'bg-red-500'
            }`} />
            {connectionStatus === 'connected' ? 'Connected' :
             connectionStatus === 'connecting' ? 'Connecting...' :
             connectionStatus === 'error' ? 'Connection Error' :
             'Disconnected'}
          </div>
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

        {/* Main Content with Tabs */}
        <TabbedInterface 
          tabs={[
            { 
              id: 'standings', 
              label: 'Standings', 
              icon: (
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              ),
              count: teams.length 
            },
            { 
              id: 'monitored', 
              label: 'Monitored Teams', 
              icon: (
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                </svg>
              ),
              count: monitoredTeams.length 
            },
            { 
              id: 'chart', 
              label: 'Race Delta Analysis', 
              icon: (
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M8 13v-1m4 1v-3m4 3V8M12 21l9-9-9-9-9 9 9 9z" />
                </svg>
              )
            },
            {
              id: 'stints',
              label: 'Stint Planner',
              icon: (
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              )
            },
            ...(user?.role === 'admin' ? [{
              id: 'admin',
              label: 'Admin',
              icon: (
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              )
            }] : [])
          ]}
          defaultTab="standings"
          isDarkMode={isDarkMode}
        >
          {StandingsTab}
          {MonitoredTeamsTab}
          {ChartTab}
          <StintPlanner 
            isDarkMode={isDarkMode} 
            myTeam={myTeam}
            teams={teams}
            isSimulating={simulating}
            sessionInfo={sessionInfo}
          />
          {user?.role === 'admin' && (
            <AdminPanel isDarkMode={isDarkMode} />
          )}
        </TabbedInterface>
      </div>
    </div>
  );
};

export default RaceDashboard;
