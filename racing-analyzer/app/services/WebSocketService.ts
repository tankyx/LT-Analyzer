// racing-analyzer/app/services/WebSocketService.ts
import { io, Socket } from 'socket.io-client';

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
}

class WebSocketService {
  private socket: Socket | null = null;
  private callbacks: WebSocketCallbacks = {};
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000; // Start with 1 second
  private maxReconnectDelay = 30000; // Max 30 seconds
  private connectionStatus: ConnectionStatus = 'disconnected';

  constructor() {
    // Only connect on client side
    if (typeof window !== 'undefined') {
      this.connect();
    }
  }

  private getSocketUrl(): string {
    // Use the same logic as ApiService for determining the base URL
    if (typeof window === 'undefined') {
      return 'http://localhost:5000'; // Default for SSR
    }
    
    // In development, use localhost
    if (process.env.NODE_ENV === 'development') {
      return 'http://localhost:5000';
    }
    
    // In production, use the same origin as the page (nginx will proxy /socket.io/)
    return window.location.origin;
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
}

// Create singleton instance
const webSocketService = new WebSocketService();

export default webSocketService;