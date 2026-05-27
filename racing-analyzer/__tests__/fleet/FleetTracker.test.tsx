import '@testing-library/jest-dom';
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';

jest.mock('@/app/services/ApiService', () => ({
  __esModule: true,
  default: {
    createFleetKart: jest.fn().mockResolvedValue({}),
    deleteFleetKart: jest.fn().mockResolvedValue({}),
    autoPopulateFleet: jest.fn().mockResolvedValue({ created_karts: [{ id: 1, label: '7' }] }),
    releaseFleetKart: jest.fn().mockResolvedValue({}),
    setFleetKartLane: jest.fn().mockResolvedValue({}),
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
  column: 'available',
  lane: null,
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

beforeEach(() => jest.clearAllMocks());

describe('FleetTracker kanban', () => {
  test('places karts in the correct columns and lanes', () => {
    const board = [
      kart({ fleet_kart_id: 1, label: 'OnTrackKart', column: 'on_track', holder_team: 'Alpha' }),
      kart({ fleet_kart_id: 2, label: 'InPitKart', column: 'in_pit', holder_team: 'Bravo' }),
      kart({ fleet_kart_id: 3, label: 'LaneTwoKart', column: 'available', lane: 2 }),
    ];
    render(<FleetTracker {...baseProps} fleetBoard={board} />);
    expect(within(screen.getByTestId('col-on-track')).getByText('OnTrackKart')).toBeInTheDocument();
    expect(within(screen.getByTestId('col-in-pit')).getByText('InPitKart')).toBeInTheDocument();
    expect(within(screen.getByTestId('lane-2')).getByText('LaneTwoKart')).toBeInTheDocument();
  });

  test('unlaned available karts land in the "just dropped" area', () => {
    render(<FleetTracker {...baseProps}
      fleetBoard={[kart({ label: 'Dropped', column: 'available', lane: null })]} />);
    expect(within(screen.getByTestId('lane-unsorted')).getByText('Dropped')).toBeInTheDocument();
  });

  test('pace chip reflects classification', () => {
    const board = [
      kart({ fleet_kart_id: 2, label: 'Fast', column: 'on_track', pace_delta_vs_fleet: -0.6, classification: 'fast' }),
    ];
    render(<FleetTracker {...baseProps} fleetBoard={board} />);
    const chip = screen.getByTestId('pace-chip');
    expect(chip).toHaveTextContent('-0.6s');
    expect(chip.className).toMatch(/green/);
  });

  test('tapping an Available kart offers Assign and calls onReassign', () => {
    const onReassign = jest.fn();
    render(<FleetTracker {...baseProps} onReassign={onReassign}
      fleetBoard={[kart({ fleet_kart_id: 5, label: 'Spare', column: 'available', lane: 1 })]} />);
    fireEvent.click(screen.getByText('Spare'));
    const sheet = screen.getByTestId('kart-action-sheet');
    fireEvent.click(within(sheet).getByText(/Assign to a team/i));
    expect(onReassign).toHaveBeenCalledWith(5);
  });

  test('releasing a held kart to a lane calls the API', async () => {
    render(<FleetTracker {...baseProps}
      fleetBoard={[kart({ fleet_kart_id: 9, label: 'Held', column: 'on_track', holder_team: 'Alpha' })]} />);
    fireEvent.click(screen.getByText('Held'));
    const sheet = screen.getByTestId('kart-action-sheet');
    fireEvent.click(within(sheet).getByText('Lane 3'));
    await waitFor(() => expect(ApiService.releaseFleetKart).toHaveBeenCalledWith(1, 9, 3, null));
  });

  test('moving an Available kart to another lane calls the API', async () => {
    render(<FleetTracker {...baseProps}
      fleetBoard={[kart({ fleet_kart_id: 4, label: 'Spare', column: 'available', lane: 1 })]} />);
    fireEvent.click(screen.getByText('Spare'));
    const sheet = screen.getByTestId('kart-action-sheet');
    fireEvent.click(within(sheet).getByText('Lane 2'));
    await waitFor(() => expect(ApiService.setFleetKartLane).toHaveBeenCalledWith(1, 4, 2));
  });

  test('shows the holder competition number with a # prefix', () => {
    render(<FleetTracker {...baseProps}
      fleetBoard={[kart({ label: 'K-7', column: 'on_track', holder_team: 'Alpha', holder_kart_number: 7, holder_position: 2 })]} />);
    expect(screen.getByText(/#7/)).toBeInTheDocument();
  });

  test('lane color editor lets you recolor a lane', () => {
    render(<FleetTracker {...baseProps} fleetBoard={[]} canEditRegistry />);
    fireEvent.click(screen.getByText(/Manage fleet/i));
    const editor = screen.getByTestId('lane-color-editor');
    // Recolor lane 1 to rose; the chosen swatch gets the selected ring.
    const rose = within(editor).getByLabelText('Lane 1 rose');
    fireEvent.click(rose);
    expect(rose.className).toMatch(/ring-2/);
    expect(within(editor).getByLabelText('Lane 1 blue').className).not.toMatch(/ring-2/);
  });

  test('empty registry shows the auto-add prompt', () => {
    render(<FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry />);
    expect(screen.getByText(/No physical karts registered/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Auto-add karts from session/i })).toBeInTheDocument();
  });

  test('registry manager gated to admins', () => {
    const { rerender } = render(<FleetTracker {...baseProps} fleetBoard={[]} canEditRegistry={false} />);
    expect(screen.queryByText(/Manage fleet/i)).not.toBeInTheDocument();
    rerender(<FleetTracker {...baseProps} fleetBoard={[]} canEditRegistry />);
    expect(screen.getByText(/Manage fleet/i)).toBeInTheDocument();
  });

  test('auto-populates when opened on an empty fleet with a live session', async () => {
    render(<FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry isActive sessionId={42} />);
    await waitFor(() => expect(ApiService.autoPopulateFleet).toHaveBeenCalledWith(1));
  });

  test('does NOT auto-populate when inactive / no session / non-admin', () => {
    const { rerender } = render(
      <FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry isActive={false} sessionId={42} />);
    rerender(<FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry isActive sessionId={null} />);
    rerender(<FleetTracker {...baseProps} fleetBoard={[]} registry={[]} canEditRegistry={false} isActive sessionId={42} />);
    expect(ApiService.autoPopulateFleet).not.toHaveBeenCalled();
  });
});
