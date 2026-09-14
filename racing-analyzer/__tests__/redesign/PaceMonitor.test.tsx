/**
 * The pace view: what a crew reads to decide whether the kart under them is
 * worth keeping, independent of track position.
 */
import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

jest.mock('@/app/services/ApiService', () => ({
  __esModule: true,
  default: { getTeamPace: jest.fn() },
}));

import ApiService from '@/app/services/ApiService';
import PaceMonitor, { formatDelta, paceTone, PaceReport } from '@/app/components/RaceDashboard/PaceMonitor';

const stint = (over: Partial<PaceReport['stints'][0]> = {}) => ({
  stint_index: 0,
  start_ts: '2026-09-14T12:00:00',
  end_ts: '2026-09-14T12:30:00',
  lap_count: 12,
  mean: 59.0,
  best: 58.4,
  field_median: 60.0,
  field_laps: 40,
  field_basis: 'stint_window',
  residual: -1.0,
  confidence: 'high' as const,
  ...over,
});

const report = (over: Partial<PaceReport> = {}): PaceReport => ({
  team: 'MY TEAM',
  matched_team: 'MY TEAM',
  session_id: 7,
  stints: [stint()],
  current: stint(),
  current_laps: [59.1, 58.9],
  recent: { laps: 5, mean: 59.2, residual: -0.8 },
  trend: 'stable',
  trend_drift: 0.05,
  field_ref_seconds: 60.0,
  own_norm_residual: -1.0,
  kart: null,
  verdict: { verdict: 'keep', reason: 'Running at your normal pace.', delta_vs_own_norm: 0.0, band: 0.25 },
  ...over,
});

const mockPace = (r: PaceReport) => (ApiService.getTeamPace as jest.Mock).mockResolvedValue(r);

describe('formatDelta / paceTone', () => {
  test('signs the delta and keeps two decimals', () => {
    expect(formatDelta(-1.234)).toBe('−1.23s');
    expect(formatDelta(0.5)).toBe('+0.50s');
    expect(formatDelta(null)).toBe('—');
  });

  test('faster than the field is good, slower is not', () => {
    expect(paceTone(-0.5)).toContain('live');
    expect(paceTone(0.5)).toContain('alarm');
    expect(paceTone(0)).toContain('ink');
    expect(paceTone(null)).toContain('muted');
  });
});

describe('PaceMonitor', () => {
  beforeEach(() => (ApiService.getTeamPace as jest.Mock).mockReset());

  test('asks for the chosen team on the chosen track', async () => {
    mockPace(report());
    render(<PaceMonitor trackId={3} teamName="MY TEAM" sessionId={7} />);
    await waitFor(() => expect(ApiService.getTeamPace).toHaveBeenCalledWith(3, 'MY TEAM', 7));
  });

  test('leads with the verdict and its reason', async () => {
    mockPace(report({
      verdict: { verdict: 'switch', reason: '1.80s a lap off your own normal pace.', delta_vs_own_norm: 1.8, band: 0.3 },
    }));
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);

    expect(await screen.findByText('Switch at the next stop')).toBeInTheDocument();
    expect(screen.getByText('1.80s a lap off your own normal pace.')).toBeInTheDocument();
  });

  test('shows pace against the field rather than position', async () => {
    mockPace(report({ own_norm_residual: -1.3 }));
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);

    // −1.00s is the current stint, and the same stint again in the list below.
    expect(await screen.findAllByText('−1.00s')).toHaveLength(2);
    expect(screen.getByText('−0.80s')).toBeInTheDocument();  // last 5 laps
    expect(screen.getByText('−1.30s')).toBeInTheDocument();  // our own norm
    expect(screen.getByText('60.00s')).toBeInTheDocument();  // field median
    expect(screen.getByText(/12 laps · high confidence/)).toBeInTheDocument();
  });

  test('reports a fading stint', async () => {
    mockPace(report({ trend: 'fading', trend_drift: 0.6 }));
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);
    expect(await screen.findByText('Fading')).toBeInTheDocument();
  });

  test('marks the best and worst stints, and the current one', async () => {
    mockPace(report({
      stints: [
        stint({ stint_index: 0, residual: -1.5 }),
        stint({ stint_index: 1, residual: 0.8 }),
        stint({ stint_index: 2, residual: -0.2 }),
      ],
      current: stint({ stint_index: 2, residual: -0.2 }),
    }));
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);

    expect(await screen.findByText('BEST')).toBeInTheDocument();
    expect(screen.getByText('WORST')).toBeInTheDocument();
    expect(screen.getByText('CURRENT')).toBeInTheDocument();
  });

  test('names the physical kart when a fleet is configured', async () => {
    mockPace(report({ kart: { fleet_kart_id: 4, label: 'K-12' } }));
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);
    expect(await screen.findByText('K-12')).toBeInTheDocument();
  });

  test('asks for a team before doing anything', () => {
    render(<PaceMonitor trackId={1} teamName="" />);
    expect(screen.getByText(/Choose your team above/)).toBeInTheDocument();
    expect(ApiService.getTeamPace).not.toHaveBeenCalled();
  });

  test('explains an idle track instead of showing an error code', async () => {
    (ApiService.getTeamPace as jest.Mock).mockRejectedValue(new Error('no_active_session'));
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);
    expect(await screen.findByText(/No session running on this track yet/)).toBeInTheDocument();
  });

  test('a failed load can be retried', async () => {
    (ApiService.getTeamPace as jest.Mock).mockRejectedValueOnce(new Error('boom')).mockResolvedValue(report());
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);

    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Keep this kart')).toBeInTheDocument();
  });

  test('states that it does not separate kart from driver', async () => {
    mockPace(report());
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);
    expect(await screen.findByText(/does not separate the kart from the driver/)).toBeInTheDocument();
  });

  test('a thin sample is labelled rather than dressed up', async () => {
    mockPace(report({
      stints: [stint({ lap_count: 2, confidence: 'low' })],
      current: stint({ lap_count: 2, confidence: 'low' }),
      verdict: { verdict: 'insufficient', reason: 'Fewer than 5 clean laps on this kart so far.', delta_vs_own_norm: null, band: null },
    }));
    render(<PaceMonitor trackId={1} teamName="MY TEAM" />);

    expect(await screen.findByText('Not enough laps yet')).toBeInTheDocument();
    expect(screen.getByText('thin sample')).toBeInTheDocument();
  });
});
