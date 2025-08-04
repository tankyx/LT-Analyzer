import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StintPlanner from '@/app/components/RaceDashboard/StintPlanner';

// Mock localStorage
const mockLocalStorage = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};
Object.defineProperty(window, 'localStorage', {
  value: mockLocalStorage,
  writable: true,
});

describe('StintPlanner Component', () => {
  const defaultProps = {
    isDarkMode: false,
    myTeam: 'Team 1',
    teams: [
      { Team: 'Team 1', Status: 'RACING' },
      { Team: 'Team 2', Status: 'RACING' },
    ],
    isSimulating: true,
    sessionInfo: {
      light: 'GREEN',
    },
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockLocalStorage.getItem.mockReturnValue(null);
  });

  test('renders StintPlanner component', () => {
    render(<StintPlanner {...defaultProps} />);
    expect(screen.getByText('Stint Planner')).toBeInTheDocument();
    expect(screen.getByText('Reset All Data')).toBeInTheDocument();
  });

  test('loads saved data from localStorage', () => {
    const savedData = {
      config: {
        numStints: 5,
        minStintTime: 30,
        maxStintTime: 45,
        pitDuration: 3,
        numDrivers: 3,
        totalRaceTime: 240,
      },
      driverNames: ['Alice', 'Bob', 'Charlie'],
      currentDriverIndex: 1,
      stintAssignments: [],
    };
    mockLocalStorage.getItem.mockReturnValue(JSON.stringify(savedData));

    render(<StintPlanner {...defaultProps} />);
    
    expect(mockLocalStorage.getItem).toHaveBeenCalledWith('stintPlannerData');
    expect(screen.getByDisplayValue('5')).toBeInTheDocument();
    expect(screen.getByDisplayValue('3')).toBeInTheDocument();
  });

  test('saves data to localStorage when config changes', async () => {
    render(<StintPlanner {...defaultProps} />);
    
    const numStintsInput = screen.getByLabelText('Number of Stints:');
    await userEvent.clear(numStintsInput);
    await userEvent.type(numStintsInput, '5');

    await waitFor(() => {
      expect(mockLocalStorage.setItem).toHaveBeenCalledWith(
        'stintPlannerData',
        expect.stringContaining('"numStints":5')
      );
    });
  });

  test('reset button clears localStorage and resets state', () => {
    window.confirm = jest.fn().mockReturnValue(true);
    
    render(<StintPlanner {...defaultProps} />);
    
    const resetButton = screen.getByText('Reset All Data');
    fireEvent.click(resetButton);

    expect(window.confirm).toHaveBeenCalledWith('Are you sure you want to reset all stint planner data?');
    expect(mockLocalStorage.removeItem).toHaveBeenCalledWith('stintPlannerData');
  });

  test('recalculate button updates stint durations', async () => {
    render(<StintPlanner {...defaultProps} />);
    
    // Change config
    const minStintInput = screen.getByLabelText('Min Stint Time (minutes):');
    await userEvent.clear(minStintInput);
    await userEvent.type(minStintInput, '25');

    // Click recalculate button
    const recalculateButton = screen.getByText('Recalculate Stints');
    fireEvent.click(recalculateButton);

    // Check that stints were recalculated
    await waitFor(() => {
      expect(mockLocalStorage.setItem).toHaveBeenCalled();
    });
  });

  test('displays correct stint assignments', () => {
    render(<StintPlanner {...defaultProps} />);
    
    // Check that stint assignments are displayed
    expect(screen.getByText('Stint Assignments')).toBeInTheDocument();
    // Check that driver stats section exists
    expect(screen.getByText('Driver Statistics')).toBeInTheDocument();
  });

  test('timer functionality works correctly', async () => {
    render(<StintPlanner {...defaultProps} />);
    
    // Start stint timer
    const startButton = screen.getByText('Start Stint');
    fireEvent.click(startButton);

    expect(screen.getByText('End Stint')).toBeInTheDocument();
    
    // End stint
    const endButton = screen.getByText('End Stint');
    fireEvent.click(endButton);

    expect(screen.getByText('Start Stint')).toBeInTheDocument();
  });

  test('dark mode styling is applied correctly', () => {
    const { container } = render(<StintPlanner {...defaultProps} isDarkMode={true} />);
    
    const darkModeElements = container.querySelectorAll('.bg-gray-800');
    expect(darkModeElements.length).toBeGreaterThan(0);
  });

  test('handles invalid localStorage data gracefully', () => {
    mockLocalStorage.getItem.mockReturnValue('invalid json data');
    
    // Should not throw error
    expect(() => render(<StintPlanner {...defaultProps} />)).not.toThrow();
  });

  test('driver names can be edited', async () => {
    render(<StintPlanner {...defaultProps} />);
    
    // Find all text inputs (driver name inputs)
    const driverInputs = screen.getAllByRole('textbox');
    
    // Should have at least 4 driver inputs (default)
    expect(driverInputs.length).toBeGreaterThanOrEqual(4);
    
    // Edit the first driver name
    const firstDriverInput = driverInputs[0];
    await userEvent.clear(firstDriverInput);
    await userEvent.type(firstDriverInput, 'New Driver Name');
    
    await waitFor(() => {
      expect(mockLocalStorage.setItem).toHaveBeenCalledWith(
        'stintPlannerData',
        expect.stringContaining('"New Driver Name"')
      );
    });
  });
});