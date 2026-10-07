import React, { useState, useEffect, useMemo, useCallback, useRef  } from 'react';
import { useRouter } from 'next/navigation';
import TimeDeltaChart from './TimeDeltaChart';
import TabbedInterface from './TabbedInterface';
import ApiService from '../../services/ApiService';
import webSocketService, { RaceDataUpdate, TeamsUpdate, SessionUpdate, AllTracksStatusUpdate, TrackStatus, FleetKartState } from '../../services/WebSocketService';
import StatusPill from './StatusPill';
import ClassFilter from './ClassFilter';
import PitStopConfig from './PitStopConfig';
import StintPlanner from './StintPlanner';
import AdminPanel from './AdminPanel';
import AppBar from './AppBar';
import TrackRail, { RailTrack } from './TrackRail';
import MyTeamStrip from './MyTeamStrip';
import PitAlertTarget, {
  DeviceToken,
  PitAlertTargetValue,
  describeDelivery,
  loadPitAlertTarget,
  savePitAlertTarget,
  targetIdsFor,
} from './PitAlertTarget';
import AlertStack from './AlertStack';
import StandingsRow, { STANDINGS_GRID, PitAlertButton } from './StandingsRow';
import { getTeamClass, displayTeamName } from './lib/teamName';
import { useTheme } from '../../contexts/ThemeContext';
import { AlertTriangle, Car, Clock, Eye, Gauge, Info, LineChart, List, Settings, Star, X } from 'lucide-react';
import FleetTracker, { FleetKart } from './FleetTracker';
import PaceMonitor from './PaceMonitor';
import KartAssignmentEntry from './KartAssignmentEntry';
import { useAuth } from '../../contexts/AuthContext';
import { saveSelectedTrack, loadSelectedTrack } from '../../utils/persistence';
import {
  getPrefs as fetchPrefs,
  makePrefsDebouncer,
  readCache as readPrefsCache,
  defaultPrefs,
  getLastSeenUpdatedAt,
  UserTrackPrefs,
} from '../../services/UserPrefsService';
import {
  getSelectedTrack,
  putSelectedTrack,
} from '../../services/SelectedTrackService';
import { parseTimeToSeconds } from '../../../utils/raceMath';

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
  title?: string;
  title1?: string;
  title2?: string;
  [key: string]: string | undefined; // Allow other string fields from backend
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
    return <span className="text-muted">~</span>;
  }
  
  const getArrows = () => {
    const arrow = trend.value < 0 ? '↓' : '↑';
    return arrow.repeat(trend.arrow);
  };
  
  const getColor = () => {
    // Simplified logic based on trend direction
    return trend.value < 0 ? 'text-live' : 'text-alarm';
  };
  
  return (
    <span className={`font-bold ${getColor()}`}>
      {getArrows()}
    </span>
  );
};

// parseTimeToSeconds imported from utils/raceMath.ts (canonical implementation)

// Helper function to calculate gaps between teams
const calculateTeamGaps = (teams: Team[], myTeamKart: string, monitoredKarts: string[], pitStopTime: number, requiredPitStops: number, isQualification: boolean = false): Record<string, DeltaData> => {
  const myTeam = teams.find(t => t.Kart === myTeamKart);
  if (!myTeam) return {};

  const myPitStops = isQualification ? 0 : parseInt(myTeam['Pit Stops'] || '0');
  const myRemainingStops = isQualification ? 0 : Math.max(0, requiredPitStops - myPitStops);
  
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

    const monPitStops = isQualification ? 0 : parseInt(monitoredTeam['Pit Stops'] || '0');
    const monRemainingStops = isQualification ? 0 : Math.max(0, requiredPitStops - monPitStops);
    
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

    // Calculate gap based on session type
    let realGap: number;
    let adjustedGap: number;
    
    if (isQualification) {
      // In qualification mode, use best lap times for gap calculation
      const myBestLap = myTeam['Best Lap'] && myTeam['Best Lap'].includes(':') 
        ? parseTimeToSeconds(myTeam['Best Lap'])
        : Infinity;
      const monBestLap = monitoredTeam['Best Lap'] && monitoredTeam['Best Lap'].includes(':')
        ? parseTimeToSeconds(monitoredTeam['Best Lap'])
        : Infinity;
      
      // Gap is the difference in best lap times
      realGap = monBestLap - myBestLap;
      adjustedGap = realGap; // No pit stop adjustments in qualification
    } else {
      // Normal race mode - calculate with pit stops
      // Calculate real gap including pit stop compensation for completed stops
      // Using 150 second compensation as base (standard Apex Timing value)
      realGap = (monGapToLeader - myGapToLeader) + ((monPitStops - myPitStops) * 150);
      
      // Calculate adjusted gap accounting for remaining required pit stops
      adjustedGap = realGap + ((monRemainingStops - myRemainingStops) * pitStopTime);
    }

    deltas[kart] = {
      gap: Math.round(realGap * 1000) / 1000, // Round to 3 decimals
      adjusted_gap: Math.round(adjustedGap * 1000) / 1000,
      team_name: monitoredTeam.Team,
      position: parseInt(monitoredTeam.Position),
      last_lap: monitoredTeam['Last Lap'],
      best_lap: monitoredTeam['Best Lap'],
      pit_stops: monitoredTeam['Pit Stops'],
      remaining_stops: isQualification ? 0 : monRemainingStops,
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

// Gate for live /fleet/state polling. Exported for unit tests.
// Hidden browser tabs never poll; users without a fleet only poll while the
// Fleet tab is open; users WITH a fleet poll in the background so the
// "fast kart in the pits" alerts still fire from other tabs.
export const shouldPollFleet = (
  visibilityState: DocumentVisibilityState | undefined,
  activeTab: string,
  registrySize: number,
): boolean => {
  if (visibilityState === 'hidden') return false;
  return activeTab === 'fleet' || registrySize > 0;
};

const RaceDashboard = () => {
  const { user, logout, apiFetch } = useAuth();
  const router = useRouter();
  const [teams, setTeams] = useState<Team[]>([]);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo>({});
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const [myTeam, setMyTeam] = useState<string>('');
  const [monitoredTeams, setMonitoredTeams] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  // Datalogger boards registered to this account, and which one PIT NOW
  // targets. Loaded once per login; `online` refreshes after each alert.
  const [devices, setDevices] = useState<DeviceToken[]>([]);
  const [pitAlertTarget, setPitAlertTarget] = useState<PitAlertTargetValue>('all');
  const [deltaData, setDeltaData] = useState<Record<string, DeltaData>>({}); // eslint-disable-line @typescript-eslint/no-unused-vars
  const [gapHistory, setGapHistory] = useState<GapHistory>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null); // eslint-disable-line @typescript-eslint/no-unused-vars
  const { isDark: isDarkMode } = useTheme();
  const [trackSheetOpen, setTrackSheetOpen] = useState(false);
  const [teamColors, setTeamColors] = useState<Record<string, string>>({});
  const [hoveredTeam, setHoveredTeam] = useState<string | null>(null);
  const [selectedClass, setSelectedClass] = useState<string>('all');
  const [showAdjustedGap, setShowAdjustedGap] = useState(false);
  const [pitStopTime, setPitStopTime] = useState(158);
  const [alertedPitTeams, setAlertedPitTeams] = useState<Set<string>>(new Set());
  const [requiredPitStops, setRequiredPitStops] = useState(7);
  const [defaultLapTime, setDefaultLapTime] = useState(90);
  const [updatedRows, setUpdatedRows] = useState<Map<string, number>>(new Map()); // Track updated rows with timestamps
  // Initialise from the WebSocketService singleton in case the connection
  // already completed before this component mounted (refresh race).
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>(() => {
    if (typeof window !== 'undefined') {
      return webSocketService.getConnectionStatus();
    }
    return 'disconnected';
  });
  const [availableTracks, setAvailableTracks] = useState<Array<{id: number; track_name: string}>>([]);
  const [selectedTrackId, setSelectedTrackId] = useState<number>(1);
  const [sessionStatus, setSessionStatus] = useState<{active: boolean; message: string; trackName: string} | null>(null);
  const [allTracksStatus, setAllTracksStatus] = useState<TrackStatus[]>([]);
  // Fleet Tracker state (live endurance physical-machine tracking)
  const [fleetBoard, setFleetBoard] = useState<FleetKartState[]>([]);
  const [fleetRegistry, setFleetRegistry] = useState<FleetKart[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null);
  const [assignmentEntry, setAssignmentEntry] = useState<{
    open: boolean;
    prompt?: { teamNumber: string; teamName: string };
    defaultKartId?: number;
  } | null>(null);
  const [alertedFleetPits, setAlertedFleetPits] = useState<Set<number>>(new Set());
  const [activeTab, setActiveTab] = useState<string>('standings');
  // Bumped on every standings update so PaceMonitor can refetch (throttled).
  const [liveUpdateTick, setLiveUpdateTick] = useState(0);
  // Ref mirrors so callbacks can read current state without re-subscribing.
  const fleetRegistryRef = useRef<FleetKart[]>([]);
  useEffect(() => { fleetRegistryRef.current = fleetRegistry; }, [fleetRegistry]);
  const teamsRef = useRef<Team[]>([]);
  useEffect(() => { teamsRef.current = teams; }, [teams]);
  const updatedRowsRef = useRef<Map<string, number>>(new Map());
  useEffect(() => { updatedRowsRef.current = updatedRows; }, [updatedRows]);

  const refreshDevices = useCallback(async () => {
    try {
      const resp = await apiFetch('/api/device/tokens');
      if (!resp.ok) return;
      const body = await resp.json();
      setDevices(Array.isArray(body.tokens) ? body.tokens : []);
    } catch {
      /* boards are optional; the dashboard works without them */
    }
  }, [apiFetch]);

  useEffect(() => {
    if (!user) return;
    setPitAlertTarget(loadPitAlertTarget());
    void refreshDevices();
  }, [user, refreshDevices]);

  const activeBoards = useMemo(() => devices.filter((d) => !d.revoked), [devices]);

  const triggerPitAlert = useCallback(async (kartNum: string, teamName: string) => {
    try {
      // Use apiFetch (not raw fetch / not ApiService) so the CSRF token and
      // session cookie are sent — the endpoint is @login_required + CSRF-
      // protected; without these headers it returns 403. The per-user pit
      // alert routing on the server uses the session to figure out which
      // user_{id} room to emit on, so cookies must flow.
      const resp = await apiFetch('/api/trigger-pit-alert', {
        method: 'POST',
        body: JSON.stringify({
          track_id: selectedTrackId,
          team_name: teamName,
          alert_message: `PIT NOW! - ${teamName}`,
          target_device_ids: targetIdsFor(pitAlertTarget) ?? null,
        }),
      });
      if (!resp.ok) {
        throw new Error(`pit alert HTTP ${resp.status}`);
      }
      const response = await resp.json();
      if (response.status === 'success') {
        // Say what actually happened at the boards: a bare "sent" would hide
        // a board that is off, on another track, or following another team.
        const delivery = describeDelivery(response, activeBoards.length);
        setAlerts(prev => [...prev, {
          id: Date.now(),
          message: `🚨 PIT ALERT for ${teamName}: ${delivery.text}`,
          type: delivery.tone,
          teamKart: kartNum
        }]);
        if (activeBoards.length > 0) void refreshDevices();
      } else {
        throw new Error(response.message || 'Failed to send pit alert');
      }
    } catch (error) {
      console.error('Error triggering pit alert:', error);
      setAlerts(prev => [...prev, {
        id: Date.now(),
        message: `❌ Failed to send pit alert to ${teamName}: ${error instanceof Error ? error.message : 'Unknown error'}`,
        type: 'error',
        teamKart: kartNum
      }]);
    }
  }, [selectedTrackId, apiFetch, pitAlertTarget, activeBoards.length, refreshDevices]);

  const filteredTeams = useMemo(() => {
    if (selectedClass === 'all') return teams;
    
    return teams.filter(team => {
      const teamClass = getTeamClass(team.Team);
      return teamClass === selectedClass;
    });
  }, [teams, selectedClass]);

  // Sort once per data/filter change, not on every render inside the JSX.
  const sortedTeams = useMemo(
    () => [...filteredTeams].sort((a, b) => parseInt(a.Position) - parseInt(b.Position)),
    [filteredTeams],
  );

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
  // Check if this is a qualification/practice session
  const isQualificationMode = useMemo(() => {
    const sessionType = sessionInfo.title2 || sessionInfo.title1 || sessionInfo.title || '';
    return ['qualification', 'session', 'practice', 'qualify'].some(keyword => 
      sessionType.toLowerCase().includes(keyword)
    );
  }, [sessionInfo]);

  const frontendDeltaData = useMemo(() => {
    if (!myTeam || monitoredTeams.length === 0 || teams.length === 0) {
      return {};
    }
    return calculateTeamGaps(teams, myTeam, monitoredTeams, pitStopTime, requiredPitStops, isQualificationMode);
  }, [teams, myTeam, monitoredTeams, pitStopTime, requiredPitStops, isQualificationMode]);
    
  const handleTeamHover = (kartNum: string | null) => {
    setHoveredTeam(kartNum);
  };

  const handleColorAssignment = (colors: Record<string, string>) => {
    setTeamColors(colors);
  };
  
  // Phase 2.6: track the last server-known selected_track_id so we can tell
  // user-initiated changes apart from cross-device sync (where we apply a
  // server-pushed track without writing it back).
  const lastServerSelectedTrackRef = useRef<number | null>(null);

  // Phase 2: per-(user, track) prefs replace the old global update-monitoring
  // and update-pit-config endpoints. A debouncer coalesces rapid edits into
  // one PUT per ~500 ms so typing in a spinner doesn't fire 12 requests.
  const prefsDebouncerRef = useRef<ReturnType<typeof makePrefsDebouncer> | null>(null);
  useEffect(() => {
    if (!selectedTrackId) return;
    // Flush any pending PUT for the previous track before swapping.
    prefsDebouncerRef.current?.flush();
    prefsDebouncerRef.current = makePrefsDebouncer(selectedTrackId, 500);
    return () => {
      prefsDebouncerRef.current?.flush();
    };
  }, [selectedTrackId]);

  const schedulePrefs = useCallback((patch: Partial<UserTrackPrefs>) => {
    prefsDebouncerRef.current?.schedule(patch);
  }, []);

  const updateMonitoring = useCallback(async () => {
    schedulePrefs({ my_team: myTeam || null, monitored_teams: monitoredTeams });
  }, [myTeam, monitoredTeams, schedulePrefs]);

  // Phase 2: pit-stop config is per-(user, track). The PUT goes through the
  // debouncer so rapid spinner clicks coalesce into a single round-trip.
  const updatePitStopConfig = useCallback((newPitTime: number, newRequiredStops: number, newDefaultLapTime?: number) => {
    schedulePrefs({
      pit_stop_time: newPitTime,
      required_pit_stops: newRequiredStops,
      default_lap_time: newDefaultLapTime ?? defaultLapTime,
    });
  }, [defaultLapTime, schedulePrefs]);


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
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <StatusPill status="Pit-in" />
                  <span className="font-bold truncate">{team.Team} (#{team.Kart})</span>
                </div>
                <div className="text-xs text-muted">In the pits from P{team.Position}</div>
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

          // Fleet Tracker: a tracked team just pitted — prompt the crew to
          // record which physical kart they took (only if a fleet is set up).
          if (fleetRegistryRef.current.length > 0) {
            setAssignmentEntry({
              open: true,
              prompt: { teamNumber: team.Kart, teamName: team.Team },
            });
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

  // Fleet Tracker: raise a one-shot alert when a fast machine enters the pits
  // (so the operator can target it) and clear it when the kart leaves.
  const checkFleetPitAlerts = useCallback((fleet: FleetKartState[]) => {
    fleet.forEach(kart => {
      const isFastInPits = kart.location === 'in-pits' && kart.classification === 'fast';
      if (isFastInPits && !alertedFleetPits.has(kart.fleet_kart_id)) {
        setAlertedFleetPits(prev => new Set(prev).add(kart.fleet_kart_id));
        setAlerts(prev => [...prev, {
          id: Date.now(),
          message: `⚡ Fast kart ${kart.label} just entered the pits${kart.holder_team ? ` (was ${kart.holder_team})` : ''}`,
          type: 'warning',
        }]);
      } else if (!isFastInPits && alertedFleetPits.has(kart.fleet_kart_id)) {
        setAlertedFleetPits(prev => {
          const next = new Set(prev);
          next.delete(kart.fleet_kart_id);
          return next;
        });
      }
    });
  }, [alertedFleetPits]);

  // Fleet data is per-user, so there's no shared broadcast — each client pulls
  // its own board from /fleet/state. Throttle live refetches so a fast feed
  // doesn't hammer the endpoint, and skip polling entirely unless the user
  // actually uses the Fleet Tracker: hidden browser tabs never poll, and a
  // user with no fleet configured only polls while the Fleet tab is open.
  // (Users WITH a fleet keep polling in the background so the "fast kart in
  // the pits" alerts still fire while they watch another tab.)
  const lastFleetFetchRef = useRef(0);
  const activeTabRef = useRef(activeTab);
  useEffect(() => { activeTabRef.current = activeTab; }, [activeTab]);
  const refreshFleetState = useCallback(async () => {
    if (!selectedTrackId) return;
    try {
      const state = await ApiService.getFleetState(selectedTrackId);
      setFleetBoard(state.karts || []);
      if (state.session_id != null) setCurrentSessionId(state.session_id);
      checkFleetPitAlerts(state.karts || []);
    } catch (err) {
      console.warn('Failed to load fleet state', err);
    }
  }, [selectedTrackId, checkFleetPitAlerts]);

  const refreshFleetThrottled = useCallback(() => {
    const visibility = typeof document !== 'undefined' ? document.visibilityState : undefined;
    if (!shouldPollFleet(visibility, activeTabRef.current, fleetRegistryRef.current.length)) return;
    const now = Date.now();
    if (now - lastFleetFetchRef.current < 3000) return;
    lastFleetFetchRef.current = now;
    refreshFleetState();
  }, [refreshFleetState]);

  // Opening the Fleet tab refreshes the board immediately (the gate above
  // may have kept it stale while the tab was closed).
  useEffect(() => {
    if (activeTab === 'fleet' && selectedTrackId) {
      lastFleetFetchRef.current = Date.now();
      refreshFleetState();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, selectedTrackId]);

  // Re-fetch the user's fleet registry (after CRUD/auto-populate or track
  // change) and the board so a new roster shows immediately.
  const refreshRegistry = useCallback(async () => {
    if (!selectedTrackId) return;
    try {
      const res = await ApiService.getFleetKarts(selectedTrackId);
      setFleetRegistry(res.karts || []);
    } catch (err) {
      console.warn('Failed to load fleet registry', err);
    }
    refreshFleetState();
  }, [selectedTrackId, refreshFleetState]);

  // Record a team -> physical-kart assignment, then refresh this user's board.
  const recordAssignment = useCallback(async (args: {
    teamName: string; fleetKartId: number; stintIndex?: number;
  }) => {
    try {
      await ApiService.recordAssignment(
        selectedTrackId, currentSessionId, args.teamName, args.fleetKartId, args.stintIndex);
      setAssignmentEntry(null);
      setAlerts(prev => [...prev, {
        id: Date.now(), message: `✓ Recorded kart for ${args.teamName}`, type: 'info',
      }]);
      refreshFleetState();
    } catch (err) {
      setAlerts(prev => [...prev, {
        id: Date.now(),
        message: `Failed to record assignment: ${err instanceof Error ? err.message : 'error'}`,
        type: 'error',
      }]);
    }
  }, [selectedTrackId, currentSessionId, refreshFleetState]);

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
      const currentTeams = teamsRef.current;
      const currentUpdatedRows = updatedRowsRef.current;
      if (newTeams && currentTeams.length > 0) {
        const currentTime = Date.now();
        const newUpdatedRows = new Map(currentUpdatedRows);

        // Map lookup instead of a find() per team — the old O(teams²) scan
        // ran on every ~1s update.
        const oldByKart = new Map(currentTeams.map(t => [t.Kart, t]));
        newTeams.forEach((newTeam: Team) => {
          const oldTeam = oldByKart.get(newTeam.Kart);
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
        setLiveUpdateTick(t => t + 1);
        setSessionInfo(data.session_info || {});
        setLastUpdate(data.last_update || '');
        // Phase 2: my_team / monitored_teams / pit_config / delta_times /
        // gap_history are no longer on this payload — they're hydrated from
        // /api/me/prefs/<track_id> when the track selection changes.
        setIsLoading(false);
        setError(null);
        if (data.teams && data.teams.length > 0) {
          checkPitStops(data.teams);
        }
        refreshFleetThrottled();
      },

      onTeamsUpdate: (data: TeamsUpdate) => {
        console.log('Received teams update');
        detectChanges(data.teams);
        setTeams(data.teams || []);
        setLiveUpdateTick(t => t + 1);
        setLastUpdate(data.last_update || '');
        if (data.teams && data.teams.length > 0) {
          checkPitStops(data.teams);
        }
        refreshFleetThrottled();
      },
      
      // Phase 2: onGapUpdate / onMonitoringUpdate / onPitConfigUpdate are no
      // longer emitted by the backend. Deltas are computed client-side and
      // monitoring + pit config live behind /api/me/prefs.
      onSessionUpdate: (data: SessionUpdate) => {
        console.log('Received session update');
        setSessionInfo(data.session_info || {});
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
        setFleetBoard([]);
        setAlertedFleetPits(new Set());
        setIsLoading(true);
        setError(null);
        setAlerts(prev => [...prev, {
          id: Date.now(),
          message: 'Race data cleared - ready for new track',
          type: 'info'
        }]);
      },

      onSessionStatus: (data) => {
        console.log('Received session status:', data);
        setSessionStatus({
          active: data.active,
          message: data.message,
          trackName: data.track_name
        });

        // Show an alert when session becomes inactive
        if (!data.active) {
          setAlerts(prev => [...prev, {
            id: Date.now(),
            message: `${data.track_name}: No active session`,
            type: 'warning'
          }]);
        }
      },

      onAllTracksStatus: (data: AllTracksStatusUpdate) => {
        console.log('Received all tracks status:', data);
        setAllTracksStatus(data.tracks);
      }
    });

    return () => {
      // Clean up WebSocket callbacks on unmount
      webSocketService.removeCallbacks();
    };
    // checkPitStops + refreshFleetThrottled are stable; teams/updatedRows
    // are accessed via refs so the effect doesn't need to re-subscribe.
  }, [checkPitStops, refreshFleetThrottled]);

  // Load available tracks on mount and restore saved selections
  useEffect(() => {
    const loadTracks = async () => {
      try {
        const result = await ApiService.getTracks();
        if (result && result.tracks) {
          setAvailableTracks(result.tracks);

          // Try to load saved track selection (client-side only).
          // Phase 2: per-(user, track) prefs now live on the server; the
          // track-selection useEffect hydrates them.
          let trackToSelect = result.tracks[0].id; // Default to first track

          if (typeof window !== 'undefined') {
            const savedTrackId = loadSelectedTrack();
            if (savedTrackId && result.tracks.some((t: {id: number; track_name: string}) => t.id === savedTrackId)) {
              trackToSelect = savedTrackId;
            }
          }

          // Phase 2.6: server-side selected track overrides localStorage if set.
          try {
            const serverTrack = await getSelectedTrack();
            if (serverTrack && result.tracks.some((t: {id: number; track_name: string}) => t.id === serverTrack)) {
              trackToSelect = serverTrack;
            }
          } catch (e) {
            console.warn('Failed to fetch selected-track preference', e);
          }
          lastServerSelectedTrackRef.current = trackToSelect;

          // Join the selected track
          if (result.tracks.length > 0) {
            setSelectedTrackId(trackToSelect);
            webSocketService.joinTrack(trackToSelect);
          }

          // Join all_tracks room for multi-track status monitoring
          webSocketService.joinAllTracks();

          // Fetch initial tracks status via API as fallback (in case WebSocket hasn't delivered it yet)
          try {
            const statusResult = await ApiService.getTracksStatus();
            if (statusResult && statusResult.tracks) {
              setAllTracksStatus(statusResult.tracks);
            }
          } catch (statusError) {
            console.error('Error loading tracks status:', statusError);
            // Not critical - WebSocket will provide updates
          }
        }
      } catch (error) {
        console.error('Error loading tracks:', error);
      }
    };
    loadTracks();

    return () => {
      // Leave all_tracks room on unmount
      webSocketService.leaveAllTracks();
    };
  }, []);

  // Handle track selection changes
  useEffect(() => {
    if (selectedTrackId) {
      console.log(`Switching to track ${selectedTrackId}`);
      // Clear stale per-track state immediately. If the new track is broadcasting,
      // the next track_update will repopulate within ~1s. If it's idle, the user
      // sees an honest "no data" view instead of the previous track's standings.
      setTeams([]);
      setSessionInfo({});
      setLastUpdate('');
      setDeltaData({});
      setGapHistory({});
      setUpdatedRows(new Map());
      setAlertedPitTeams(new Set());
      setFleetBoard([]);
      setAlertedFleetPits(new Set());
      webSocketService.joinTrack(selectedTrackId);
      saveSelectedTrack(selectedTrackId);

      // Seed the fleet registry + board so the panel isn't empty before the
      // first fleet_update arrives on the track room.
      (async () => {
        try {
          const reg = await ApiService.getFleetKarts(selectedTrackId);
          setFleetRegistry(reg.karts || []);
          const state = await ApiService.getFleetState(selectedTrackId);
          setFleetBoard(state.karts || []);
          if (state.session_id != null) setCurrentSessionId(state.session_id);
        } catch (err) {
          console.warn('Failed to seed fleet state', err);
        }
      })();

      // Phase 2: hydrate per-(user, track) prefs from the server. We seed
      // from the localStorage cache immediately so the UI doesn't flash to
      // defaults, then refresh from the server in the background.
      const cached = readPrefsCache(selectedTrackId);
      const seed: UserTrackPrefs = cached || defaultPrefs(selectedTrackId);
      setMyTeam(seed.my_team || '');
      setMonitoredTeams(seed.monitored_teams || []);
      setPitStopTime(seed.pit_stop_time);
      setRequiredPitStops(seed.required_pit_stops);
      setDefaultLapTime(seed.default_lap_time);
      (async () => {
        try {
          const fresh = await fetchPrefs(selectedTrackId);
          setMyTeam(fresh.my_team || '');
          setMonitoredTeams(fresh.monitored_teams || []);
          setPitStopTime(fresh.pit_stop_time);
          setRequiredPitStops(fresh.required_pit_stops);
          setDefaultLapTime(fresh.default_lap_time);
        } catch (err) {
          console.warn('Failed to load prefs for track', selectedTrackId, err);
        }
      })();
    }
  }, [selectedTrackId]);

  // Phase 2.6: when selectedTrackId changes locally AND differs from what the
  // server last told us, PUT it back. The comparison skips the round-trip when
  // we're applying a server-pushed value (cross-device sync).
  useEffect(() => {
    if (!selectedTrackId) return;
    if (lastServerSelectedTrackRef.current === selectedTrackId) return;
    lastServerSelectedTrackRef.current = selectedTrackId;
    putSelectedTrack(selectedTrackId).catch((err) => {
      console.warn('Failed to persist selected-track', err);
    });
  }, [selectedTrackId]);

  // Phase 2.6: listen for selected_track_updated from other tabs/devices.
  useEffect(() => {
    const unsubscribe = webSocketService.addSelectedTrackListener((event) => {
      if (event.track_id === selectedTrackId) return; // already on it
      lastServerSelectedTrackRef.current = event.track_id;
      setSelectedTrackId(event.track_id);
    });
    return unsubscribe;
  }, [selectedTrackId]);

  // Phase 2.5 live-sync: re-fetch prefs when ANOTHER tab/device writes them.
  useEffect(() => {
    if (!selectedTrackId) return;
    const unsubscribe = webSocketService.addPrefsListener(async (event) => {
      if (event.track_id !== selectedTrackId) return;
      // Echo dedup: skip if this is our own write coming back.
      if (event.updated_at && event.updated_at === getLastSeenUpdatedAt(selectedTrackId)) {
        return;
      }
      try {
        // Flush our own pending PUTs first so the server has the latest of
        // what we know. Without this, an unrelated PUT (e.g. StintPlanner
        // saving a preset) would emit prefs_updated that causes us to
        // overwrite locally-staged-but-not-yet-pushed monitored_teams.
        await prefsDebouncerRef.current?.flush();
        const fresh = await fetchPrefs(selectedTrackId);
        setMyTeam(fresh.my_team || '');
        setMonitoredTeams(fresh.monitored_teams || []);
        setPitStopTime(fresh.pit_stop_time);
        setRequiredPitStops(fresh.required_pit_stops);
        setDefaultLapTime(fresh.default_lap_time);
      } catch (err) {
        console.warn('Live prefs refresh failed', err);
      }
    });
    return unsubscribe;
  }, [selectedTrackId]);

  // Stable identity so memoized StandingsRow props don't churn per render.
  const toggleTeamMonitoring = useCallback((kartNum: string) => {
    setIsUserUpdate(true);
    setMonitoredTeams(prev =>
      prev.includes(kartNum)
        ? prev.filter(k => k !== kartNum)
        : [...prev, kartNum]
    );
  }, []);

  const dismissAlert = (id: number) => {
    setAlerts(prev => prev.filter(alert => alert.id !== id));
  };

  if (isLoading && connectionStatus === 'disconnected') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-canvas text-ink">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-[3px] border-accent border-t-transparent rounded-full animate-spin" />
          <div className="text-sm text-muted">Connecting to the timing server…</div>
        </div>
      </div>
    );
  }

  const selectedTrackName = availableTracks.find(t => t.id === selectedTrackId)?.track_name || '';
  // The pace API keys on the team name as the feed spells it, not the kart number.
  const myTeamName = teams.find(t => t.Kart === myTeam)?.Team || '';
  const sessionLabel = sessionInfo.title2 || sessionInfo.title1 || sessionInfo.title || '';
  const sessionActive = sessionStatus ? sessionStatus.active : teams.length > 0;
  const railTracks: RailTrack[] = allTracksStatus.length > 0
    ? allTracksStatus
    : availableTracks.map(t => ({ track_id: t.id, track_name: t.track_name, active: false }));

  const locateTeam = (kart: string) => {
    document.getElementById(`team-${kart}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const StandingsTab = (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <ClassFilter
          selectedClass={selectedClass}
          onClassChange={setSelectedClass}
          teamCount={teamCounts}
        />
        {lastUpdate && (
          <span className="md:hidden text-[11px] text-muted">Updated {lastUpdate}</span>
        )}
      </div>

      <div className="rounded-xl border border-line bg-surface overflow-hidden panel" role="table" aria-label="Standings">
        <div
          role="row"
          className={`${STANDINGS_GRID} hidden md:grid h-9 px-4 text-[11px] font-bold tracking-[.08em] uppercase text-muted border-b border-line bg-surface-2`}
        >
          <div role="columnheader">Pos</div>
          <div role="columnheader">Team</div>
          <div role="columnheader" className="md:hidden" />
          <div role="columnheader">Status</div>
          <div role="columnheader">Last</div>
          <div role="columnheader">Best</div>
          <div role="columnheader" className="text-right">Gap</div>
          <div role="columnheader" className="text-right">{isQualificationMode ? 'Laps' : 'Stops'}</div>
          <div role="columnheader" className="text-center">Watch</div>
        </div>

        {filteredTeams.length > 0 ? (
          sortedTeams.map(team => (
            <StandingsRow
              key={team.Kart}
              team={team}
              isMyTeam={team.Kart === myTeam}
              isMonitored={monitoredTeams.includes(team.Kart)}
              teamColor={teamColors[team.Kart]}
              isUpdated={updatedRows.has(team.Kart)}
              selectedTrackId={selectedTrackId}
              onToggleMonitor={toggleTeamMonitoring}
              onTriggerAlert={triggerPitAlert}
            />
          ))
        ) : (
          <div className="px-4 py-12 flex flex-col items-center text-center text-muted">
            {teams.length === 0 ? (
              <>
                <Clock size={40} className="opacity-30 mb-3" />
                <p className="text-base font-semibold text-ink">No live data for {selectedTrackName || 'this track'}</p>
                <p className="text-sm mt-1">Standings appear here as soon as the timing feed sends a session.</p>
                <button
                  type="button"
                  onClick={() => setTrackSheetOpen(true)}
                  className="mt-4 h-10 px-4 rounded-lg border border-line bg-surface-2 text-sm font-semibold text-ink"
                >
                  Pick a live track
                </button>
              </>
            ) : (
              <>
                <p className="text-base font-semibold text-ink">No teams in this class</p>
                <button
                  type="button"
                  onClick={() => setSelectedClass('all')}
                  className="mt-4 h-10 px-4 rounded-lg border border-line bg-surface-2 text-sm font-semibold text-ink"
                >
                  Show all teams
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );

  const MonitoredTeamsTab = (
    <div className="flex flex-col gap-3">
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

      <div className="rounded-xl border border-line bg-surface overflow-hidden panel">
        <div className="flex items-center justify-between gap-3 px-4 h-12 border-b border-line bg-surface-2">
          <h2 className="font-cond font-bold text-lg tracking-wide flex items-center gap-2">
            <Eye size={18} className="text-accent" />
            MONITORED
            <span className="font-mono tabular text-xs px-1.5 py-px rounded-full bg-line text-muted">{monitoredTeams.length}</span>
          </h2>
          {!isQualificationMode && (
            <div className="inline-flex gap-1 p-[3px] rounded-lg bg-surface border border-line" role="group" aria-label="Gap mode">
              <button
                type="button"
                aria-pressed={!showAdjustedGap}
                onClick={() => setShowAdjustedGap(false)}
                className={`h-8 px-3 rounded-md text-xs font-semibold ${!showAdjustedGap ? 'bg-surface-2 text-ink' : 'text-muted'}`}
              >
                Raw
              </button>
              <button
                type="button"
                aria-pressed={showAdjustedGap}
                onClick={() => setShowAdjustedGap(true)}
                className={`h-8 px-3 rounded-md text-xs font-semibold ${showAdjustedGap ? 'bg-surface-2 text-ink' : 'text-muted'}`}
              >
                Adjusted
              </button>
            </div>
          )}
        </div>

        <div className="p-3 flex flex-col gap-2">
          {Object.entries(frontendDeltaData)
            .sort((a, b) => a[1].position - b[1].position)
            .map(([kart, data]) => {
              const team = teams.find(t => t.Kart === kart);
              const inPit = team?.Status === 'Pit-in';
              const gapValue = showAdjustedGap ? (data.adjusted_gap ?? data.gap) : data.gap;
              const trend = data.trends?.lap_1?.arrow ? data.trends.lap_1
                : data.trends?.lap_5?.arrow ? data.trends.lap_5
                : data.trends?.lap_10?.arrow ? data.trends.lap_10 : undefined;
              return (
                <div
                  key={kart}
                  className={`rounded-lg border p-3 flex flex-col gap-2 transition-colors ${
                    inPit ? 'border-alarm/50 bg-alarm/[.07]' : 'border-line bg-canvas'
                  } ${hoveredTeam === kart ? 'ring-2 ring-info/60' : ''}`}
                  style={{ boxShadow: teamColors[kart] ? `inset 3px 0 0 ${teamColors[kart]}` : undefined }}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-surface-2 font-cond font-bold text-base flex items-center justify-center shrink-0">
                      {data.position}
                    </div>
                    <div className="flex flex-col min-w-0 flex-1">
                      <span className="text-sm font-semibold truncate">{displayTeamName(data.team_name)}</span>
                      <div className="flex items-center gap-2">
                        <span className="font-mono tabular text-[11px] text-muted">#{kart}</span>
                        {team?.Status !== undefined && <StatusPill status={team.Status} variant="inline" />}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      {team && !['Pit-in', 'Finished', 'DNF', 'DSQ'].includes(team.Status || '') && (
                        <PitAlertButton kartNum={kart} teamName={team.Team} trackId={selectedTrackId} onTriggerAlert={triggerPitAlert} />
                      )}
                      <span className={`font-mono tabular text-lg font-semibold ${gapValue >= 0 ? 'text-live' : 'text-alarm'}`}>
                        {gapValue >= 0 ? '+' : '−'}{Math.abs(gapValue).toFixed(3)}
                      </span>
                      {trend ? <TrendArrows trend={showAdjustedGap ? (data.adjusted_trends?.lap_1 ?? trend) : trend} /> : null}
                      <button
                        type="button"
                        onClick={() => toggleTeamMonitoring(kart)}
                        aria-label={`Stop monitoring ${data.team_name}`}
                        className="w-9 h-9 rounded-lg flex items-center justify-center text-muted hover:text-ink hover:bg-surface-2"
                      >
                        <X size={16} />
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="flex flex-col">
                      <span className="text-[10px] font-bold tracking-[.08em] uppercase text-muted">Last</span>
                      <span className="font-mono tabular text-sm">{data.last_lap || '—'}</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] font-bold tracking-[.08em] uppercase text-muted">Best</span>
                      <span className="font-mono tabular text-sm">{data.best_lap || '—'}</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] font-bold tracking-[.08em] uppercase text-muted">{isQualificationMode ? 'Laps' : 'Stops'}</span>
                      <span className="font-mono tabular text-sm">
                        {data.pit_stops || '0'}
                        {!isQualificationMode && showAdjustedGap && data.remaining_stops !== undefined && (
                          <span className="text-muted"> · {data.remaining_stops > 0 ? `${data.remaining_stops} to go` : 'done'}</span>
                        )}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          {Object.keys(frontendDeltaData).length === 0 && (
            <div className="py-10 flex flex-col items-center text-center text-muted">
              <Star size={36} className="opacity-30 mb-3" />
              {!myTeam ? (
                <>
                  <p className="text-sm font-semibold text-ink">Pick your team first</p>
                  <p className="text-xs mt-1">Gaps are measured from your team, so choose it in the card above.</p>
                </>
              ) : (
                <>
                  <p className="text-sm font-semibold text-ink">No teams monitored yet</p>
                  <p className="text-xs mt-1">Tap the star on a standings row to track its gap to you.</p>
                </>
              )}
            </div>
          )}
        </div>

        {!isQualificationMode && showAdjustedGap && Object.keys(frontendDeltaData).length > 0 && (
          <div className="px-4 py-2 text-xs text-muted border-t border-line bg-surface-2 flex items-center gap-1.5">
            <Info size={14} className="text-info shrink-0" />
            Adjusted gap accounts for remaining pit stops ({Math.floor(pitStopTime / 60)}:{String(pitStopTime % 60).padStart(2, '0')} per stop). Positive = they are behind you.
          </div>
        )}
      </div>
    </div>
  );

  const ChartTab = (
    <div className="flex flex-col gap-3">
      <div className="rounded-xl border border-line bg-surface p-3 md:p-4 panel">
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
      </div>
      <div className="rounded-xl border border-line bg-surface p-4 text-xs text-muted">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="flex items-center gap-2">
            <span className="h-px w-5 bg-muted" /><span className="h-3 w-3 rounded-full bg-muted" />
            <span>Teams on track</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="h-px w-5 border-t border-dashed border-muted" /><span className="h-3 w-3 rounded-full bg-alarm" />
            <span>Teams in pits</span>
          </div>
          <div className="flex items-center gap-2"><span className="text-live">▼</span><span>Getting closer to you</span></div>
          <div className="flex items-center gap-2"><span className="text-alarm">▲</span><span>Falling behind you</span></div>
        </div>
      </div>
    </div>
  );

  const tabs = [
    { id: 'standings', label: 'Standings', icon: <List size={18} />, count: teams.length },
    { id: 'monitored', label: 'Monitored', icon: <Eye size={18} />, count: monitoredTeams.length },
    { id: 'pace', label: 'Pace', icon: <Gauge size={18} /> },
    { id: 'chart', label: 'Delta', icon: <LineChart size={18} /> },
    { id: 'stints', label: 'Stints', icon: <Clock size={18} /> },
    { id: 'fleet', label: 'Fleet', icon: <Car size={18} />, count: fleetBoard.length },
    ...(user?.role === 'admin' ? [{ id: 'admin', label: 'Admin', icon: <Settings size={18} /> }] : []),
  ];

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <AppBar
        trackName={selectedTrackName}
        sessionLabel={sessionLabel}
        sessionActive={sessionActive}
        flag={sessionInfo.light}
        timers={[sessionInfo.dyn1 || '', sessionInfo.dyn2 || '']}
        connectionStatus={connectionStatus}
        lastUpdate={lastUpdate}
        user={user ? { username: user.username, role: user.role } : null}
        onLogout={logout}
        onOpenTracks={() => setTrackSheetOpen(true)}
        onOpenStats={() => router.push('/data')}
        onOpenDevices={() => router.push('/devices')}
      />

      <div className="flex items-start">
        {/* Desktop track rail */}
        <aside className="hidden lg:block w-64 shrink-0 sticky top-14 h-[calc(100vh-56px)]">
          <TrackRail
            tracks={railTracks}
            selectedTrackId={selectedTrackId}
            onSelect={setSelectedTrackId}
            variant="rail"
            isAdmin={user?.role === 'admin'}
            onOpenAdmin={() => router.push('/admin')}
          />
        </aside>

        <main className="flex-1 min-w-0 p-3 md:p-5 pb-24 md:pb-8 flex flex-col gap-3 md:gap-4">
          {!sessionActive && sessionStatus && (
            <div className="rounded-lg border border-accent/50 bg-accent/10 px-3 py-2 text-sm flex items-center gap-2">
              <AlertTriangle size={16} className="text-accent shrink-0" />
              <span>{sessionStatus.trackName || selectedTrackName}: no active session right now.</span>
            </div>
          )}

          <MyTeamStrip
            teams={teams}
            myTeam={myTeam}
            onSelectMyTeam={(kart) => {
              setIsUserUpdate(true);
              setMyTeam(kart);
            }}
            isQualificationMode={isQualificationMode}
            requiredPitStops={requiredPitStops}
            onPitAlert={(kart, teamName) => triggerPitAlert(kart, teamName)}
            pitAlertTargetSlot={
              activeBoards.length > 0 ? (
                <PitAlertTarget
                  devices={activeBoards}
                  value={pitAlertTarget}
                  onChange={(v) => {
                    setPitAlertTarget(v);
                    savePitAlertTarget(v);
                  }}
                />
              ) : undefined
            }
          />

          <TabbedInterface tabs={tabs} defaultTab="standings" isDarkMode={isDarkMode} onTabChange={setActiveTab}>
            {StandingsTab}
            {MonitoredTeamsTab}
            <PaceMonitor
              trackId={selectedTrackId}
              teamName={myTeamName}
              sessionId={currentSessionId}
              updateTick={liveUpdateTick}
              isActive={activeTab === 'pace'}
            />
            {ChartTab}
            <div className="rounded-xl border border-line bg-surface overflow-hidden panel">
              <StintPlanner
                isDarkMode={isDarkMode}
                myTeam={myTeam}
                teams={teams}
                isSimulating={true}
                sessionInfo={sessionInfo}
                trackId={selectedTrackId}
                trackName={selectedTrackName}
              />
            </div>
            <div className="rounded-xl border border-line bg-surface overflow-hidden panel">
              <FleetTracker
                isDarkMode={isDarkMode}
                fleetBoard={fleetBoard}
                registry={fleetRegistry}
                trackId={selectedTrackId}
                sessionId={currentSessionId}
                isActive={activeTab === 'fleet'}
                canEditRegistry={!!user}
                onReassign={(kartId) => setAssignmentEntry({ open: true, defaultKartId: kartId })}
                onAddAssignment={() => setAssignmentEntry({ open: true })}
                onRegistryChange={refreshRegistry}
              />
            </div>
            {user?.role === 'admin' && (
              <div className="rounded-xl border border-line bg-surface overflow-hidden panel">
                <AdminPanel isDarkMode={isDarkMode} />
              </div>
            )}
          </TabbedInterface>
        </main>
      </div>

      {trackSheetOpen && (
        <TrackRail
          tracks={railTracks}
          selectedTrackId={selectedTrackId}
          onSelect={setSelectedTrackId}
          variant="sheet"
          onClose={() => setTrackSheetOpen(false)}
          isAdmin={user?.role === 'admin'}
          onOpenAdmin={() => router.push('/admin')}
        />
      )}

      <AlertStack alerts={alerts} onDismiss={dismissAlert} onLocate={locateTeam} />

      {assignmentEntry?.open && (
        <KartAssignmentEntry
          isDarkMode={isDarkMode}
          registry={fleetRegistry}
          teams={teams}
          prompt={assignmentEntry.prompt}
          defaultKartId={assignmentEntry.defaultKartId}
          onSubmit={recordAssignment}
          onCancel={() => setAssignmentEntry(null)}
        />
      )}
    </div>
  );
};

export default RaceDashboard;
