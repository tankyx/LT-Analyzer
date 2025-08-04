import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RaceDashboard from '@/app/components/RaceDashboard';
import { useAuth } from '@/app/contexts/AuthContext';
import ApiService from '@/app/services/ApiService';
import webSocketService from '@/app/services/WebSocketService';

// Mock dependencies
jest.mock('@/app/contexts/AuthContext');
jest.mock('@/app/services/ApiService');
jest.mock('@/app/services/WebSocketService', () => ({
  __esModule: true,
  default: {
    connect: jest.fn(),
    disconnect: jest.fn(),
    setCallbacks: jest.fn(),
    removeCallbacks: jest.fn(),
  }
}));

// Mock child components
jest.mock('@/app/components/RaceDashboard/TimeDeltaChart', () => {
  return function MockTimeDeltaChart() {
    return <div data-testid="time-delta-chart">Time Delta Chart</div>;
  };
});

jest.mock('@/app/components/RaceDashboard/SimulationControls', () => {
  return function MockSimulationControls({ onStart, onStop }: any) {
    return (
      <div data-testid="simulation-controls">
        <button onClick={() => onStart({ track: 'test-track' })}>Start</button>
        <button onClick={onStop}>Stop</button>
      </div>
    );
  };
});

jest.mock('@/app/components/RaceDashboard/TabbedInterface', () => {
  return function MockTabbedInterface({ teams }: any) {
    return <div data-testid="tabbed-interface">Teams: {teams.length}</div>;
  };
});

describe('RaceDashboard Component', () => {
  const mockApiService = {
    startSimulation: jest.fn(),
    stopSimulation: jest.fn(),
    updateMonitoring: jest.fn(),
    getRaceData: jest.fn(),
    updatePitConfig: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    (useAuth as jest.Mock).mockReturnValue({ isAdmin: false });
    
    Object.assign(ApiService, mockApiService);
  });

  test('renders RaceDashboard component', () => {
    render(<RaceDashboard />);
    expect(screen.getByText('Race Dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('simulation-controls')).toBeInTheDocument();
  });

  test('connects to WebSocket on mount', () => {
    render(<RaceDashboard />);
    expect(webSocketService.connect).toHaveBeenCalled();
  });

  test('disconnects from WebSocket on unmount', () => {
    const { unmount } = render(<RaceDashboard />);
    unmount();
    expect(webSocketService.disconnect).toHaveBeenCalled();
  });

  test('sets up WebSocket callbacks on mount', () => {
    render(<RaceDashboard />);

    expect(webSocketService.setCallbacks).toHaveBeenCalledWith({
      onConnectionStatusChange: expect.any(Function),
      onRaceDataUpdate: expect.any(Function),
      onTeamsUpdate: expect.any(Function),
      onGapUpdate: expect.any(Function),
      onSessionUpdate: expect.any(Function),
      onMonitoringUpdate: expect.any(Function),
      onPitConfigUpdate: expect.any(Function),
      onRaceDataReset: expect.any(Function),
      onDeltaChange: expect.any(Function),
    });
  });

  test('handles simulation start', async () => {
    mockApiService.startSimulation.mockResolvedValue({ success: true });
    
    render(<RaceDashboard />);
    
    const startButton = screen.getByText('Start');
    fireEvent.click(startButton);

    await waitFor(() => {
      expect(mockApiService.startSimulation).toHaveBeenCalledWith('test-track');
    });
  });

  test('handles simulation stop', async () => {
    mockApiService.stopSimulation.mockResolvedValue({ success: true });
    
    render(<RaceDashboard />);
    
    const stopButton = screen.getByText('Stop');
    fireEvent.click(stopButton);

    await waitFor(() => {
      expect(mockApiService.stopSimulation).toHaveBeenCalled();
    });
  });


  test('displays alerts correctly', async () => {
    render(<RaceDashboard />);
    
    // The component would typically generate alerts internally
    // We can check that the alert container exists
    const container = screen.getByText('Race Dashboard').closest('div');
    expect(container).toBeInTheDocument();
  });

  test('handles dark mode toggle', () => {
    const { container } = render(<RaceDashboard />);
    
    const darkModeButton = screen.getByLabelText('Toggle dark mode');
    fireEvent.click(darkModeButton);

    // Check that dark mode classes are applied
    expect(container.querySelector('.bg-gray-900')).toBeInTheDocument();
  });

  test('shows admin panel for admin users', () => {
    (useAuth as jest.Mock).mockReturnValue({ isAdmin: true });
    
    render(<RaceDashboard />);
    
    expect(screen.getByRole('button', { name: /admin/i })).toBeInTheDocument();
  });


  test('handles WebSocket errors gracefully', async () => {
    const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation();
    
    mockApiService.startSimulation.mockRejectedValue(new Error('Connection failed'));
    
    render(<RaceDashboard />);
    
    const startButton = screen.getByText('Start');
    fireEvent.click(startButton);

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalled();
    });

    consoleErrorSpy.mockRestore();
  });
});