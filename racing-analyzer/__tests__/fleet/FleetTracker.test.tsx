import '@testing-library/jest-dom';
import { render, screen, within, waitFor } from '@testing-library/react';

jest.mock('@/app/services/ApiService', () => ({
  __esModule: true,
  default: {
    createFleetKart: jest.fn().mockResolvedValue({}),
    deleteFleetKart: jest.fn().mockResolvedValue({}),
    autoPopulateFleet: jest.fn().mockResolvedValue({ created_karts: [{ id: 1, label: '7' }] }),
  },
}));

import ApiService from '@/app/services/ApiService';

import FleetTracker, { FleetKart } from '@/app/components/RaceDashboard/FleetTracker';
import { FleetKartState } from '@/app/services/WebSocketService';

const kart = (over: Partial<FleetKartState>): FleetKartState => ({
  fleet_kart_id: 1,
  label: 'K1',
  holder_team: null,
  holder_kart_number: null,
  holder_position: null,
  location: 'available',
  stint_index: null,
  mean_residual: null,
  pace_delta_vs_fleet: null,
  uncertainty: null,
  sample_laps: 0,
  n_stints: 0,
  classification: 'insufficient',
  rank: null,
  alerts: [],
  ...over,
});

const baseProps = {
  isDarkMode: false,
  registry: [{ id: 1, label: 'K1', is_active: true }] as FleetKart[],
  trackId: 1,
  canEditRegistry: false,
  onReassign: jest.fn(),
  onAddAssignment: jest.fn(),
  onRegistryChange: jest.fn(),
};

describe('FleetTracker', () => {
  test('ranks karts fastest (most negative delta) first', () => {
    const board = [
      kart({ fleet_kart_id: 1, label: 'Slow', pace_delta_vs_fleet: 0.8, classification: 'slow', rank: 3, sample_laps: 10, n_stints: 2 }),
      kart({ fleet_kart_id: 2, label: 'Fast', pace_delta_vs_fleet: -0.9, classification: 'fast', rank: 1, sample_laps: 10, n_stints: 2 }),
      kart({ fleet_kart_id: 3, label: 'Mid', pace_delta_vs_fleet: 0.0, classification: 'neutral', rank: 2, sample_laps: 10, n_stints: 2 }),
    ];
    render(<FleetTracker {...baseProps} fleetBoard={board} registry={[]} />);
    const cards = screen.getAllByTestId('fleet-kart-card');
    const order = cards.map(c => within(c).getByText(/Fast|Slow|Mid/).textContent);
    expect(order).toEqual(['Fast', 'Mid', 'Slow']);
  });

  test('pace chip reflects classification', () => {
    const board = [
      kart({ fleet_kart_id: 2, label: 'Fast', pace_delta_vs_fleet: -0.6, classification: 'fast', rank: 1, sample_laps: 8, n_stints: 2 }),
      kart({ fleet_kart_id: 9, label: 'New', classification: 'insufficient' }),
    ];
    render(<FleetTracker {...baseProps} fleetBoard={board} registry={[]} />);
    const fastCard = screen.getAllByTestId('fleet-kart-card')[0];
    const chip = within(fastCard).getByTestId('pace-chip');
    expect(chip).toHaveTextContent('-0.6s');
    expect(chip.className).toMatch(/green/);

    const newCard = screen.getByText('New').closest('[data-testid="fleet-kart-card"]')!;
    expect(within(newCard as HTMLElement).getByTestId('pace-chip')).toHaveTextContent('low data');
  });

  test('renders location badges', () => {
    const board = [
      kart({ fleet_kart_id: 1, label: 'P', location: 'in-pits', classification: 'fast', pace_delta_vs_fleet: -0.5, rank: 1, sample_laps: 6, n_stints: 1, holder_team: 'Alpha' }),
    ];
    render(<FleetTracker {...baseProps} fleetBoard={board} registry={[]} />);
    expect(screen.getByTestId('location-chip')).toHaveTextContent('In pits');
  });

  test('empty registry shows setup hint', () => {
    render(<FleetTracker {...baseProps} fleetBoard={[]} registry={[]} />);
    expect(screen.getByText(/No physical karts registered/i)).toBeInTheDocument();
  });

  test('registry manager hidden for non-admins', () => {
    render(<FleetTracker {...baseProps} fleetBoard={[]} canEditRegistry={false} />);
    expect(screen.queryByText(/Manage fleet/i)).not.toBeInTheDocument();
  });

  test('registry manager available to admins', () => {
    render(<FleetTracker {...baseProps} fleetBoard={[]} canEditRegistry={true} />);
    expect(screen.getByText(/Manage fleet/i)).toBeInTheDocument();
  });

  test('auto-populates when tab is opened on an empty fleet with a live session', async () => {
    (ApiService.autoPopulateFleet as jest.Mock).mockClear();
    render(
      <FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry
        isActive sessionId={42} />,
    );
    await waitFor(() => expect(ApiService.autoPopulateFleet).toHaveBeenCalledWith(1));
  });

  test('does NOT auto-populate when the tab is not active', () => {
    (ApiService.autoPopulateFleet as jest.Mock).mockClear();
    render(
      <FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry
        isActive={false} sessionId={42} />,
    );
    expect(ApiService.autoPopulateFleet).not.toHaveBeenCalled();
  });

  test('does NOT auto-populate without a live session', () => {
    (ApiService.autoPopulateFleet as jest.Mock).mockClear();
    render(
      <FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry
        isActive sessionId={null} />,
    );
    expect(ApiService.autoPopulateFleet).not.toHaveBeenCalled();
  });

  test('does NOT auto-populate for non-admins', () => {
    (ApiService.autoPopulateFleet as jest.Mock).mockClear();
    render(
      <FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry={false}
        isActive sessionId={42} />,
    );
    expect(ApiService.autoPopulateFleet).not.toHaveBeenCalled();
  });
});
