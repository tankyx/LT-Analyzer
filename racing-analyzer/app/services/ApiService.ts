// racing-analyzer/app/services/ApiService.ts

export const ApiService = {
  // Get race data
  getRaceData: async () => {
    try {
      const response = await fetch(`/api/race-data`);
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
      const response = await fetch(`/api/update-monitoring`, {
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
  startSimulation: async () => {
    try {
      const response = await fetch(`/api/start-simulation`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      if (!response.ok) {
        throw new Error('Failed to start simulation');
      }
      return await response.json();
    } catch (error) {
      console.error('Error starting simulation:', error);
      throw error;
    }
  },

  // Stop simulation
  stopSimulation: async () => {
    try {
      const response = await fetch(`/api/stop-simulation`, {
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

  updatePitStopConfig: async (data: { pitStopTime: number; requiredPitStops: number }) => {
    try {
      const response = await fetch(`/api/update-pit-config`, {
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
  }
};

export default ApiService;
