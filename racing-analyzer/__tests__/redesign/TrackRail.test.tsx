import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TrackRail, { groupTracks, RailTrack } from '@/app/components/RaceDashboard/TrackRail';

const tracks: RailTrack[] = [
  { track_id: 1, track_name: 'Mariembourg', active: true, teams_count: 24, provider: 'apex' },
  { track_id: 2, track_name: 'Spa-Francorchamps', active: false },
  { track_id: 184, track_name: 'Buckmore Park', active: true, teams_count: 18, provider: 'alphahub' },
  { track_id: 5, track_name: 'Eupen', active: false },
];

describe('groupTracks', () => {
  test('splits live from idle, each alphabetical', () => {
    const { live, idle } = groupTracks(tracks, '');
    expect(live.map((t) => t.track_name)).toEqual(['Buckmore Park', 'Mariembourg']);
    expect(idle.map((t) => t.track_name)).toEqual(['Eupen', 'Spa-Francorchamps']);
  });
  test('search filters both groups by prefix and by provider', () => {
    expect(groupTracks(tracks, 'sp').idle.map((t) => t.track_name)).toEqual(['Spa-Francorchamps']);
    expect(groupTracks(tracks, 'sp').live).toEqual([]);
    expect(groupTracks(tracks, 'alpha').live.map((t) => t.track_name)).toEqual(['Buckmore Park']);
  });
});

describe('TrackRail', () => {
  test('rail: shows Live/Idle headers, team counts, and selects on click', async () => {
    const onSelect = jest.fn();
    render(<TrackRail tracks={tracks} selectedTrackId={1} onSelect={onSelect} />);
    expect(screen.getByText('Live now · 2')).toBeInTheDocument();
    expect(screen.getByText('Idle · 2')).toBeInTheDocument();
    expect(screen.getByText('18 teams · AlphaHub')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Eupen'));
    expect(onSelect).toHaveBeenCalledWith(5);
  });

  test('sheet: picking a track also closes; Escape closes', async () => {
    const onSelect = jest.fn();
    const onClose = jest.fn();
    render(<TrackRail tracks={tracks} selectedTrackId={1} onSelect={onSelect} variant="sheet" onClose={onClose} />);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Buckmore Park'));
    expect(onSelect).toHaveBeenCalledWith(184);
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  test('search narrows the list and can be cleared', async () => {
    render(<TrackRail tracks={tracks} selectedTrackId={1} onSelect={() => {}} />);
    await userEvent.type(screen.getByLabelText('Search tracks'), 'zzz');
    expect(screen.getByText(/No tracks match/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('Clear search'));
    expect(screen.getByText('Mariembourg')).toBeInTheDocument();
  });

  test('admin entry only renders for admins', () => {
    const { rerender } = render(<TrackRail tracks={tracks} selectedTrackId={1} onSelect={() => {}} onOpenAdmin={() => {}} />);
    expect(screen.queryByText('Admin')).toBeNull();
    rerender(<TrackRail tracks={tracks} selectedTrackId={1} onSelect={() => {}} isAdmin onOpenAdmin={() => {}} />);
    expect(screen.getByText('Admin')).toBeInTheDocument();
  });
});
