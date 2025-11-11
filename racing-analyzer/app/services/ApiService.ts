// racing-analyzer/app/services/ApiService.ts

import { API_BASE_URL } from '../../utils/config';

export const ApiService = {
  // Get race data
  getRaceData: async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/race-data`);
      if (!response.ok) {
        throw new Error('Failed to fetch race data');
      }
      return await response.json();
    } catch (error) {
      console.error('Error fetching race data:', error);
      throw error;
    }
  },

  // Update monitoring settings
  updateMonitoring: async (data: { myTeam: string; monitoredTeams: string[] }) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/update-monitoring`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });
      if (!response.ok) {
        throw new Error('Failed to update monitoring settings');
      }
      return await response.json();
    } catch (error) {
      console.error('Error updating monitoring:', error);
      throw error;
    }
  },

  // Start simulation
  startSimulation: async (isSimulationMode: boolean = false, timingUrl?: string, websocketUrl?: string, trackId?: number) => {
    try {
      console.log(`Calling ${API_BASE_URL}/api/start-simulation with mode:`, isSimulationMode, 'URL:', timingUrl, 'WS URL:', websocketUrl, 'Track ID:', trackId);
      const payload: { simulation: boolean; timingUrl?: string; websocketUrl?: string; trackId?: number } = { simulation: isSimulationMode };
      if (timingUrl) {
        payload.timingUrl = timingUrl;
      }
      if (websocketUrl) {
        payload.websocketUrl = websocketUrl;
      }
      if (trackId) {
        payload.trackId = trackId;
      }
      
      const response = await fetch(`${API_BASE_URL}/api/start-simulation`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error('Response not OK:', response.status, errorText);
        throw new Error(`Failed to start simulation: ${response.status} ${errorText}`);
      }
      
      const result = await response.json();
      console.log('Start simulation response:', result);
      return result;
    } catch (error) {
      console.error('Error starting simulation:', error);
      if (error instanceof TypeError && error.message.includes('fetch')) {
        throw new Error('Cannot connect to backend server at ' + API_BASE_URL);
      }
      throw error;
    }
  },

  // Stop simulation
  stopSimulation: async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/stop-simulation`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      if (!response.ok) {
        throw new Error('Failed to stop simulation');
      }
      return await response.json();
    } catch (error) {
      console.error('Error stopping simulation:', error);
      throw error;
    }
  },

  updatePitStopConfig: async (data: { pitStopTime: number; requiredPitStops: number; defaultLapTime?: number }) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/update-pit-config`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });
      if (!response.ok) {
        throw new Error('Failed to update pit stop configuration');
      }
      return await response.json();
    } catch (error) {
      console.error('Error updating pit stop config:', error);
      throw error;
    }
  },

  // Track management API methods
  getTracks: async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/tracks`);
      if (!response.ok) {
        throw new Error('Failed to fetch tracks');
      }
      return await response.json();
    } catch (error) {
      console.error('Error fetching tracks:', error);
      throw error;
    }
  },

  getTracksStatus: async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/tracks/status`);
      if (!response.ok) {
        throw new Error('Failed to fetch tracks status');
      }
      return await response.json();
    } catch (error) {
      console.error('Error fetching tracks status:', error);
      throw error;
    }
  },

  getTrack: async (id: number) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/tracks/${id}`);
      if (!response.ok) {
        throw new Error('Failed to fetch track');
      }
      return await response.json();
    } catch (error) {
      console.error('Error fetching track:', error);
      throw error;
    }
  },

  addTrack: async (data: { 
    track_name: string; 
    timing_url: string; 
    websocket_url?: string; 
    column_mappings?: {
      position?: number;
      kart?: number;
      team?: number;
      status?: number;
      lastLap?: number;
      bestLap?: number;
      gap?: number;
      pitStops?: number;
    } 
  }) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/tracks`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to add track');
      }
      return await response.json();
    } catch (error) {
      console.error('Error adding track:', error);
      throw error;
    }
  },

  updateTrack: async (id: number, data: { 
    track_name?: string; 
    timing_url?: string; 
    websocket_url?: string; 
    column_mappings?: {
      position?: number;
      kart?: number;
      team?: number;
      status?: number;
      lastLap?: number;
      bestLap?: number;
      gap?: number;
      pitStops?: number;
    }
  }) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/tracks/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to update track');
      }
      return await response.json();
    } catch (error) {
      console.error('Error updating track:', error);
      throw error;
    }
  },

  deleteTrack: async (id: number) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/tracks/${id}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to delete track');
      }
      return await response.json();
    } catch (error) {
      console.error('Error deleting track:', error);
      throw error;
    }
  },

  resetRaceData: async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/reset-race-data`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      if (!response.ok) {
        throw new Error('Failed to reset race data');
      }
      return await response.json();
    } catch (error) {
      console.error('Error resetting race data:', error);
      throw error;
    }
  },

  // Team data analysis API methods
  searchTeams: async (query: string, trackId: number = 1) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/team-data/search?q=${encodeURIComponent(query)}&track_id=${trackId}`);
      if (!response.ok) {
        throw new Error('Failed to search teams');
      }
      return await response.json();
    } catch (error) {
      console.error('Error searching teams:', error);
      throw error;
    }
  },

  getTopTeams: async (trackId: number = 1, limit: number = 10, sessionId?: number) => {
    try {
      let url = `${API_BASE_URL}/api/team-data/top-teams?track_id=${trackId}&limit=${limit}`;
      if (sessionId) {
        url += `&session_id=${sessionId}`;
      }
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error('Failed to get top teams');
      }
      return await response.json();
    } catch (error) {
      console.error('Error getting top teams:', error);
      throw error;
    }
  },

  getAllSessions: async (trackId: number = 1) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/team-data/sessions?track_id=${trackId}`);
      if (!response.ok) {
        throw new Error('Failed to get sessions');
      }
      return await response.json();
    } catch (error) {
      console.error('Error getting sessions:', error);
      throw error;
    }
  },

  getTeamStats: async (teamName: string, sessionId?: number, trackId: number = 1) => {
    try {
      let url = `${API_BASE_URL}/api/team-data/stats?team=${encodeURIComponent(teamName)}&track_id=${trackId}`;
      if (sessionId) {
        url += `&session_id=${sessionId}`;
      }
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error('Failed to get team stats');
      }
      return await response.json();
    } catch (error) {
      console.error('Error getting team stats:', error);
      throw error;
    }
  },

  compareTeams: async (teamNames: string[], sessionId?: number, trackId: number = 1) => {
    try {
      const body: { teams: string[]; session_id?: number; track_id: number } = {
        teams: teamNames,
        track_id: trackId
      };
      if (sessionId) {
        body.session_id = sessionId;
      }
      const response = await fetch(`${API_BASE_URL}/api/team-data/compare`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error('Failed to compare teams');
      }
      return await response.json();
    } catch (error) {
      console.error('Error comparing teams:', error);
      throw error;
    }
  },

  getCommonSessions: async (teamNames: string[], trackId: number = 1) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/team-data/common-sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ teams: teamNames, track_id: trackId }),
      });
      if (!response.ok) {
        throw new Error('Failed to get common sessions');
      }
      return await response.json();
    } catch (error) {
      console.error('Error getting common sessions:', error);
      throw error;
    }
  },

  getLapDetails: async (teamNames: string[], sessionId?: number, trackId: number = 1) => {
    try {
      const body: { teams: string[]; track_id: number; session_id?: number } = {
        teams: teamNames,
        track_id: trackId
      };
      if (sessionId !== undefined) {
        body.session_id = sessionId;
      }

      const response = await fetch(`${API_BASE_URL}/api/team-data/lap-details`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error('Failed to get lap details');
      }
      return await response.json();
    } catch (error) {
      console.error('Error getting lap details:', error);
      throw error;
    }
  },

  deleteBestLap: async (teamName: string, trackId: number, bestLapTime: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/team-data/delete-best-lap`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ team_name: teamName, track_id: trackId, best_lap_time: bestLapTime }),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to delete best lap');
      }
      return await response.json();
    } catch (error) {
      console.error('Error deleting best lap:', error);
      throw error;
    }
  },

  massDeleteLaps: async (trackId: number, thresholdSeconds: number, deleteType: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/team-data/mass-delete-laps`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          track_id: trackId,
          threshold_seconds: thresholdSeconds,
          delete_type: deleteType
        }),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to mass delete laps');
      }
      return await response.json();
    } catch (error) {
      console.error('Error mass deleting laps:', error);
      throw error;
    }
  },

  getAllLaps: async (teamName: string, trackId: number, sessionId?: number, limit: number = 50, offset: number = 0) => {
    try {
      const params = new URLSearchParams({
        team: teamName,
        track_id: trackId.toString(),
        limit: limit.toString(),
        offset: offset.toString()
      });

      if (sessionId) {
        params.append('session_id', sessionId.toString());
      }

      const response = await fetch(`${API_BASE_URL}/api/team-data/all-laps?${params.toString()}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to fetch all laps');
      }
      return await response.json();
    } catch (error) {
      console.error('Error fetching all laps:', error);
      throw error;
    }
  },

  getCrossTrackSessions: async (teamName: string) => {
    try {
      const params = new URLSearchParams({
        team: teamName
      });

      const response = await fetch(`${API_BASE_URL}/api/team-data/cross-track-sessions?${params.toString()}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to fetch cross-track sessions');
      }
      return await response.json();
    } catch (error) {
      console.error('Error fetching cross-track sessions:', error);
      throw error;
    }
  },

  getSessionLaps: async (teamName: string, trackId: number, sessionId: number) => {
    try {
      const params = new URLSearchParams({
        team: teamName,
        track_id: trackId.toString(),
        session_id: sessionId.toString()
      });

      const response = await fetch(`${API_BASE_URL}/api/team-data/session-laps?${params.toString()}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to fetch session laps');
      }
      return await response.json();
    } catch (error) {
      console.error('Error fetching session laps:', error);
      throw error;
    }
  }
};

export default ApiService;
