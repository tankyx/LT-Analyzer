import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import KartAssignmentEntry from '@/app/components/RaceDashboard/KartAssignmentEntry';
import { FleetKart } from '@/app/components/RaceDashboard/FleetTracker';

const registry: FleetKart[] = [
  { id: 11, label: 'K11', is_active: true },
  { id: 12, label: 'K12', is_active: true },
];

describe('KartAssignmentEntry', () => {
  test('prompt mode shows which team pitted and submits the chosen kart', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined);
    render(
      <KartAssignmentEntry
        registry={registry}
        teams={[]}
        prompt={{ teamNumber: '7', teamName: 'Team Falcon' }}
        onSubmit={onSubmit}
        onCancel={jest.fn()}
      />,
    );
    expect(screen.getByText(/Team Falcon \(#7\) just pitted/i)).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('kart-select'), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ teamName: 'Team Falcon', fleetKartId: 12 }));
  });

  test('Save is disabled until a kart is chosen', () => {
    render(
      <KartAssignmentEntry
        registry={registry}
        teams={[]}
        prompt={{ teamNumber: '7', teamName: 'Team Falcon' }}
        onSubmit={jest.fn()}
        onCancel={jest.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
  });

  test('a rejected submit does not crash and re-enables Save', async () => {
    const onSubmit = jest.fn().mockRejectedValue(new Error('network'));
    render(
      <KartAssignmentEntry
        registry={registry}
        teams={[]}
        prompt={{ teamNumber: '1', teamName: 'T' }}
        onSubmit={onSubmit}
        onCancel={jest.fn()}
      />,
    );
    fireEvent.change(screen.getByTestId('kart-select'), { target: { value: '11' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: /save/i })).not.toBeDisabled();
  });

  test('clicking the overlay cancels', () => {
    const onCancel = jest.fn();
    render(
      <KartAssignmentEntry registry={registry} teams={[]} onSubmit={jest.fn()} onCancel={onCancel} />,
    );
    fireEvent.click(screen.getByTestId('assignment-overlay'));
    expect(onCancel).toHaveBeenCalled();
  });
});
