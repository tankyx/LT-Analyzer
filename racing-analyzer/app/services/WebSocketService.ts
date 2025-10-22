// racing-analyzer/app/services/WebSocketService.ts
import { io, Socket } from 'socket.io-client';
import { API_BASE_URL } from '../../utils/config';

// Import types from RaceDashboard
interface Team {
  Kart: string;
  Team: string;
  Position: string;
  'Last Lap': string;
  'Best Lap': string;
  Gap: string;
  RunTime: string;
  'Pit Stops': string;
  Status: string;
  Class?: string;
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

interface GapData {
  gaps: number[];
  last_update: string;
}

type GapHistory = Record<string, GapData>;

export interface RaceDataUpdate {
  teams: Team[];
  session_info: SessionInfo;
  last_update: string;
  delta_times: Record<string, DeltaData>;
  gap_history: GapHistory;
  simulation_mode: boolean;
  timing_url?: string;
  is_running: boolean;
  my_team: string | null;
  monitored_teams: string[];
  pit_config: {
    required_stops: number;
    pit_time: number;
    default_lap_time?: number;
  };
}

export interface TeamsUpdate {
  teams: Team[];
  last_update: string;
}

export interface GapUpdate {
  delta_times: Record<string, DeltaData>;
  gap_history: GapHistory;
}

export interface SessionUpdate {
  session_info: SessionInfo;
}

export interface MonitoringUpdate {
  my_team: string | null;
  monitored_teams: string[];
}

export interface PitConfigUpdate {
  required_stops: number;
  pit_time: number;
  default_lap_time?: number;
}

export interface DeltaChange {
  kart: string;
  team_name: string;
  gap: number;
  adjusted_gap: number;
  gap_change: number;
  adj_gap_change: number;
  position: number;
  trends: {
    lap_1: Trend;
    lap_5: Trend;
    lap_10: Trend;
  };
}

export interface DeltaChangeUpdate {
  changed_deltas: Record<string, DeltaChange>;
  timestamp: string;
}

export interface TrackUpdate {
  track_id: number;
  track_name: string;
  teams: Team[];
  session_id: number;
  timestamp: string;
}

export interface SessionStatus {
  track_id: number;
  track_name: string;
  active: boolean;
  message: string;
  timestamp: string;
}

export interface TrackStatus {
  track_id: number;
  track_name: string;
  active: boolean;
  last_update?: string;
  teams_count?: number;
  is_connected?: boolean;
}

export interface AllTracksStatusUpdate {
  tracks: TrackStatus[];
  timestamp: string;
}

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface WebSocketCallbacks {
  onRaceDataUpdate?: (data: RaceDataUpdate) => void;
  onTeamsUpdate?: (data: TeamsUpdate) => void;
  onGapUpdate?: (data: GapUpdate) => void;
  onSessionUpdate?: (data: SessionUpdate) => void;
  onMonitoringUpdate?: (data: MonitoringUpdate) => void;
  onPitConfigUpdate?: (data: PitConfigUpdate) => void;
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
  onRaceDataReset?: () => void;
  onDeltaChange?: (data: DeltaChangeUpdate) => void;
  onSessionStatus?: (data: SessionStatus) => void;
  onAllTracksStatus?: (data: AllTracksStatusUpdate) => void;
}

class WebSocketService {
  private socket: Socket | null = null;
  private callbacks: WebSocketCallbacks = {};
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000; // Start with 1 second
  private maxReconnectDelay = 30000; // Max 30 seconds
  private connectionStatus: ConnectionStatus = 'disconnected';
  private currentTrackId: number | null = null;

  constructor() {
    // Only connect on client side
    if (typeof window !== 'undefined') {
      this.connect();
    }
  }

  private getSocketUrl(): string {
    // Use the configured API URL
    return API_BASE_URL;
  }

  connect(): void {
    if (this.socket?.connected) {
      console.log('WebSocket already connected');
      return;
    }

    this.updateConnectionStatus('connecting');
    
    const socketUrl = this.getSocketUrl();
    console.log('Connecting to WebSocket at:', socketUrl);
    
    this.socket = io(socketUrl, {
      reconnection: true,
      reconnectionAttempts: this.maxReconnectAttempts,
      reconnectionDelay: this.reconnectDelay,
      reconnectionDelayMax: this.maxReconnectDelay,
      transports: ['polling', 'websocket'], // Start with polling, upgrade to websocket
      path: '/socket.io/',
      withCredentials: false,
      timeout: 20000, // 20 second timeout
    });

    this.setupEventListeners();
  }

  private setupEventListeners(): void {
    if (!this.socket) return;

    // Connection events
    this.socket.on('connect', () => {
      console.log('WebSocket connected');
      this.reconnectAttempts = 0;
      this.updateConnectionStatus('connected');
    });

    this.socket.on('disconnect', (reason) => {
      console.log('WebSocket disconnected:', reason);
      this.updateConnectionStatus('disconnected');
    });

    this.socket.on('connect_error', (error) => {
      console.error('WebSocket connection error:', error);
      this.updateConnectionStatus('error');
    });

    // Race data events
    this.socket.on('race_data_update', (data: RaceDataUpdate) => {
      this.callbacks.onRaceDataUpdate?.(data);
    });

    // Track-specific update events
    this.socket.on('track_update', (data: TrackUpdate) => {
      console.log(`Received track_update for track ${data.track_id}:`, data.track_name);
      // Convert track update to race data format
      if (this.callbacks.onTeamsUpdate && data.teams) {
        this.callbacks.onTeamsUpdate({
          teams: data.teams,
          last_update: data.timestamp
        });
      }
    });

    this.socket.on('teams_update', (data: TeamsUpdate) => {
      this.callbacks.onTeamsUpdate?.(data);
    });

    this.socket.on('gap_update', (data: GapUpdate) => {
      this.callbacks.onGapUpdate?.(data);
    });

    this.socket.on('session_update', (data: SessionUpdate) => {
      this.callbacks.onSessionUpdate?.(data);
    });

    this.socket.on('monitoring_update', (data: MonitoringUpdate) => {
      this.callbacks.onMonitoringUpdate?.(data);
    });

    this.socket.on('pit_config_update', (data: PitConfigUpdate) => {
      this.callbacks.onPitConfigUpdate?.(data);
    });

    // Handle race data reset
    this.socket.on('race_data_reset', () => {
      this.callbacks.onRaceDataReset?.();
    });

    // Handle delta change events
    this.socket.on('delta_change', (data: DeltaChangeUpdate) => {
      this.callbacks.onDeltaChange?.(data);
    });

    // Handle session status events (active/inactive sessions)
    this.socket.on('session_status', (data: SessionStatus) => {
      console.log(`Session status for track ${data.track_id} (${data.track_name}): ${data.active ? 'active' : 'inactive'}`);
      this.callbacks.onSessionStatus?.(data);
    });

    // Handle all tracks status events
    this.socket.on('all_tracks_status', (data: AllTracksStatusUpdate) => {
      console.log(`Received status for ${data.tracks.length} tracks`);
      this.callbacks.onAllTracksStatus?.(data);
    });
  }

  private updateConnectionStatus(status: ConnectionStatus): void {
    this.connectionStatus = status;
    this.callbacks.onConnectionStatusChange?.(status);
  }

  disconnect(): void {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
      this.updateConnectionStatus('disconnected');
    }
  }

  setCallbacks(callbacks: WebSocketCallbacks): void {
    this.callbacks = { ...this.callbacks, ...callbacks };
  }

  removeCallbacks(): void {
    this.callbacks = {};
  }

  getConnectionStatus(): ConnectionStatus {
    return this.connectionStatus;
  }

  isConnected(): boolean {
    return this.socket?.connected ?? false;
  }

  // Send a custom event to the server
  emit(event: string, data: unknown): void {
    if (this.socket?.connected) {
      this.socket.emit(event, data);
    } else {
      console.warn('Cannot emit event - WebSocket not connected');
    }
  }

  // Join a track-specific room
  joinTrack(trackId: number): void {
    if (this.currentTrackId === trackId) {
      console.log(`Already subscribed to track ${trackId}`);
      return;
    }

    // Leave current track if any
    if (this.currentTrackId !== null) {
      this.leaveTrack(this.currentTrackId);
    }

    if (this.socket?.connected) {
      console.log(`Joining track ${trackId} room`);
      this.socket.emit('join_track', { track_id: trackId });
      this.currentTrackId = trackId;
    } else {
      console.warn('Cannot join track - WebSocket not connected');
    }
  }

  // Leave a track-specific room
  leaveTrack(trackId: number): void {
    if (this.socket?.connected) {
      console.log(`Leaving track ${trackId} room`);
      this.socket.emit('leave_track', { track_id: trackId });
      if (this.currentTrackId === trackId) {
        this.currentTrackId = null;
      }
    }
  }

  // Get current track ID
  getCurrentTrackId(): number | null {
    return this.currentTrackId;
  }

  // Join the all_tracks room for multi-track status updates
  joinAllTracks(): void {
    if (this.socket?.connected) {
      console.log('Joining all_tracks room');
      this.socket.emit('join_all_tracks');
    } else {
      console.warn('Cannot join all_tracks room - WebSocket not connected');
    }
  }

  // Leave the all_tracks room
  leaveAllTracks(): void {
    if (this.socket?.connected) {
      console.log('Leaving all_tracks room');
      this.socket.emit('leave_all_tracks');
    }
  }
}

// Create singleton instance
const webSocketService = new WebSocketService();

export default webSocketService;