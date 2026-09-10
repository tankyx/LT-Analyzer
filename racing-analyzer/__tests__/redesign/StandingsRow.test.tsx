import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StandingsRow, { displayTeamName, getTeamClass, RowTeam } from '@/app/components/RaceDashboard/StandingsRow';

const team: RowTeam = {
  Kart: '14',
  Team: '1 - MY TEAM ENDURANCE',
  Position: '4',
  'Last Lap': '1:19.701',
  'Best Lap': '1:19.233',
  'Pit Stops': '2',
  Gap: '8.115',
  Status: 'On Track',
};

const renderRow = (over: Partial<React.ComponentProps<typeof StandingsRow>> = {}) => {
  const props = {
    team,
    isMyTeam: false,
    isMonitored: false,
    isUpdated: false,
    selectedTrackId: 1,
    onToggleMonitor: jest.fn(),
    onTriggerAlert: jest.fn().mockResolvedValue(undefined),
    ...over,
  };
  render(<StandingsRow {...props} />);
  return props;
};

describe('team name helpers', () => {
  test('class prefix is detected and stripped for display', () => {
    expect(getTeamClass('1 - FOO')).toBe('1');
    expect(getTeamClass('2 - FOO')).toBe('2');
    expect(getTeamClass('FOO')).toBeNull();
    expect(displayTeamName('1 - FOO')).toBe('FOO');
    expect(displayTeamName('FOO')).toBe('FOO');
  });
});

describe('StandingsRow', () => {
  test('renders name without prefix, a class chip, kart number, and timing figures', () => {
    renderRow();
    expect(screen.getByText('MY TEAM ENDURANCE')).toBeInTheDocument();
    // class chip renders twice: name line (desktop) and kart line (phone); CSS shows one
    expect(screen.getAllByText('C1')).toHaveLength(2);
    expect(screen.getByText('#14')).toBeInTheDocument();
    // last lap appears twice: phone stack + desktop column (CSS hides one)
    expect(screen.getAllByText('1:19.701')).toHaveLength(2);
    expect(screen.getByText('1:19.233')).toBeInTheDocument();
  });

  test('star toggles monitoring for that kart', async () => {
    const props = renderRow();
    await userEvent.click(screen.getByLabelText('Monitor MY TEAM ENDURANCE'));
    expect(props.onToggleMonitor).toHaveBeenCalledWith('14');
  });

  test('pit-alert bell only appears for monitored teams that are not already in the pits', async () => {
    const props = renderRow({ isMonitored: true });
    await userEvent.click(screen.getByLabelText('Send pit alert to 1 - MY TEAM ENDURANCE'));
    expect(props.onTriggerAlert).toHaveBeenCalledWith('14', '1 - MY TEAM ENDURANCE', 1);
  });

  test('no bell when unmonitored or when the team is in the pits', () => {
    renderRow({ isMonitored: false });
    expect(screen.queryByLabelText(/Send pit alert/)).toBeNull();
  });

  test('my team gets the YOU tag and an anchor id for Locate', () => {
    renderRow({ isMyTeam: true });
    expect(screen.getByText('YOU')).toBeInTheDocument();
    expect(document.getElementById('team-14')).not.toBeNull();
  });

  test('monitored team in the pits pulses', () => {
    renderRow({ isMonitored: true, team: { ...team, Status: 'Pit-in' } });
    expect(document.getElementById('team-14')?.className).toContain('pit-alert');
    expect(screen.queryByLabelText(/Send pit alert/)).toBeNull();
  });
});
