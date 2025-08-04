import { io } from 'socket.io-client';
import webSocketService from '@/app/services/WebSocketService';

// Mock socket.io-client
jest.mock('socket.io-client');
const mockSocket = {
  connect: jest.fn(),
  disconnect: jest.fn(),
  on: jest.fn(),
  off: jest.fn(),
  emit: jest.fn(),
  removeAllListeners: jest.fn(),
  connected: false,
};

// Add mock for setCallbacks if it doesn't exist
if (!webSocketService.setCallbacks) {
  webSocketService.setCallbacks = jest.fn();
}

describe('WebSocketService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (io as jest.Mock).mockReturnValue(mockSocket);
    // Reset the service's socket property
    (webSocketService as any).socket = null;
  });

  afterEach(() => {
    webSocketService.disconnect();
  });

  describe('Connection Management', () => {
    test('connects to WebSocket server', () => {
      webSocketService.connect();
      
      expect(io).toHaveBeenCalledWith(expect.any(String), {
        reconnection: false,
        transports: ['websocket', 'polling'],
        path: '/socket.io/',
        withCredentials: false,
        timeout: 20000,
        forceNew: true,
      });
    });

    test('disconnects from WebSocket server', () => {
      webSocketService.connect();
      webSocketService.disconnect();
      
      expect(mockSocket.disconnect).toHaveBeenCalled();
    });

    test('prevents multiple connections', () => {
      // First connection
      webSocketService.connect();
      expect(io).toHaveBeenCalledTimes(1);
      
      // Try to connect again - should not create new connection
      webSocketService.connect();
      
      // Still should have been called only once
      expect(io).toHaveBeenCalledTimes(1);
    });
  });

  describe('Event Handlers', () => {
    beforeEach(() => {
      webSocketService.connect();
    });

    test('subscribes to race data updates', () => {
      const callback = jest.fn();
      webSocketService.setCallbacks({ onRaceDataUpdate: callback });
      
      // Get the handler that was registered
      const calls = mockSocket.on.mock.calls;
      const raceDataCall = calls.find(call => call[0] === 'race_data_update');
      expect(raceDataCall).toBeDefined();
      
      // Simulate receiving data
      const testData = { teams: [], sessionInfo: {} };
      if (raceDataCall) {
        raceDataCall[1](testData);
        expect(callback).toHaveBeenCalledWith(testData);
      }
    });

    test('subscribes to teams updates', () => {
      const callback = jest.fn();
      webSocketService.setCallbacks({ onTeamsUpdate: callback });
      
      const calls = mockSocket.on.mock.calls;
      const teamsCall = calls.find(call => call[0] === 'teams_update');
      expect(teamsCall).toBeDefined();
      
      const testData = { teams: [{ Team: 'Team 1', Position: '1' }], last_update: '' };
      if (teamsCall) {
        teamsCall[1](testData);
        expect(callback).toHaveBeenCalledWith(testData);
      }
    });

    test('subscribes to gap updates', () => {
      const callback = jest.fn();
      webSocketService.setCallbacks({ onGapUpdate: callback });
      
      const calls = mockSocket.on.mock.calls;
      const gapCall = calls.find(call => call[0] === 'gap_update');
      expect(gapCall).toBeDefined();
      
      const testData = { delta_times: {}, gap_history: {} };
      if (gapCall) {
        gapCall[1](testData);
        expect(callback).toHaveBeenCalledWith(testData);
      }
    });

    test('subscribes to session updates', () => {
      const callback = jest.fn();
      webSocketService.setCallbacks({ onSessionUpdate: callback });
      
      const calls = mockSocket.on.mock.calls;
      const sessionCall = calls.find(call => call[0] === 'session_update');
      expect(sessionCall).toBeDefined();
      
      const testData = { light: 'GREEN', title: 'Race' };
      if (sessionCall) {
        sessionCall[1](testData);
        expect(callback).toHaveBeenCalledWith(testData);
      }
    });

    test('subscribes to monitoring updates', () => {
      const callback = jest.fn();
      webSocketService.setCallbacks({ onMonitoringUpdate: callback });
      
      const calls = mockSocket.on.mock.calls;
      const monitoringCall = calls.find(call => call[0] === 'monitoring_update');
      expect(monitoringCall).toBeDefined();
      
      const testData = { myTeam: 'Team 1', topTeam: 'Team 2' };
      if (monitoringCall) {
        monitoringCall[1](testData);
        expect(callback).toHaveBeenCalledWith(testData);
      }
    });

    test('subscribes to pit config updates', () => {
      const callback = jest.fn();
      webSocketService.setCallbacks({ onPitConfigUpdate: callback });
      
      const calls = mockSocket.on.mock.calls;
      const pitConfigCall = calls.find(call => call[0] === 'pit_config_update');
      expect(pitConfigCall).toBeDefined();
      
      const testData = { enabled: true, lapTimeThreshold: 150, minPitDuration: 20 };
      if (pitConfigCall) {
        pitConfigCall[1](testData);
        expect(callback).toHaveBeenCalledWith(testData);
      }
    });
  });

  describe('Cleanup', () => {
    test('removes all event listeners on disconnect', () => {
      webSocketService.connect();
      webSocketService.disconnect();
      
      expect(mockSocket.removeAllListeners).toHaveBeenCalled();
    });

    test('cleanup works when socket is null', () => {
      // Disconnect first to ensure socket is null
      webSocketService.disconnect();
      
      // Should not throw
      expect(() => webSocketService.disconnect()).not.toThrow();
    });
  });

  describe('Error Handling', () => {
    test('handles connection errors', () => {
      const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation();
      webSocketService.connect();
      
      const calls = mockSocket.on.mock.calls;
      const errorCall = calls.find(call => call[0] === 'connect_error');
      expect(errorCall).toBeDefined();
      
      const error = new Error('Connection failed');
      if (errorCall) {
        errorCall[1](error);
        expect(consoleErrorSpy).toHaveBeenCalledWith('WebSocket connection error:', 'Connection failed');
      }
      consoleErrorSpy.mockRestore();
    });

    test('handles disconnection', () => {
      const consoleLogSpy = jest.spyOn(console, 'log').mockImplementation();
      webSocketService.connect();
      
      const calls = mockSocket.on.mock.calls;
      const disconnectCall = calls.find(call => call[0] === 'disconnect');
      expect(disconnectCall).toBeDefined();
      
      disconnectCall[1]('io server disconnect');
      
      expect(consoleLogSpy).toHaveBeenCalledWith('WebSocket disconnected:', 'io server disconnect');
      consoleLogSpy.mockRestore();
    });
  });

});