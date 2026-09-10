import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MyTeamStrip, { computeMyTeamContext, formatGap, StripTeam } from '@/app/components/RaceDashboard/MyTeamStrip';

const row = (o: Partial<StripTeam> & { Kart: string; Position: string }): StripTeam => ({
  Team: `Team ${o.Kart}`,
  'Last Lap': '1:19.700',
  'Best Lap': '1:19.200',
  'Pit Stops': '2',
  Gap: '',
  Status: 'On Track',
  ...o,
});

const field: StripTeam[] = [
  row({ Kart: '7', Position: '1', Gap: '' }),
  row({ Kart: '21', Position: '2', Gap: '2.341' }),
  row({ Kart: '14', Position: '3', Gap: '8.115', 'Last Lap': '1:19.200' }),
  row({ Kart: '28', Position: '4', Gap: '14.902' }),
  row({ Kart: '9', Position: '5', Gap: '1 Tour' }),
];

describe('computeMyTeamContext', () => {
  test('returns null when my kart is not in the field', () => {
    expect(computeMyTeamContext(field, '99')).toBeNull();
  });

  test('gap ahead is negative, gap behind positive, both from Gap-to-leader', () => {
    const ctx = computeMyTeamContext(field, '14')!;
    expect(ctx.position).toBe(3);
    expect(ctx.ahead?.team.Kart).toBe('21');
    expect(ctx.ahead?.gap).toBeCloseTo(-5.774, 3);
    expect(ctx.behind?.team.Kart).toBe('28');
    expect(ctx.behind?.gap).toBeCloseTo(6.787, 3);
  });

  test('a lapped neighbour yields a null gap instead of a bogus number', () => {
    const ctx = computeMyTeamContext(field, '28')!;
    expect(ctx.behind?.team.Kart).toBe('9');
    expect(ctx.behind?.gap).toBeNull();
  });

  test('leader has no car ahead; last has no car behind', () => {
    expect(computeMyTeamContext(field, '7')!.ahead).toBeNull();
    expect(computeMyTeamContext(field, '9')!.behind).toBeNull();
  });

  test('flags a personal best when last lap equals best lap', () => {
    expect(computeMyTeamContext(field, '14')!.isPersonalBest).toBe(true);
    expect(computeMyTeamContext(field, '21')!.isPersonalBest).toBe(false);
  });
});

describe('formatGap', () => {
  test('uses a true minus sign and three decimals', () => {
    expect(formatGap(-1.2)).toBe('−1.200');
    expect(formatGap(6.787)).toBe('+6.787');
    expect(formatGap(null)).toBe('—');
  });
});

describe('MyTeamStrip', () => {
  test('offers a team picker until a team is chosen', async () => {
    const onSelect = jest.fn();
    render(
      <MyTeamStrip teams={field} myTeam="" onSelectMyTeam={onSelect} isQualificationMode={false} requiredPitStops={5} />,
    );
    const select = screen.getByLabelText('Choose your team');
    await userEvent.selectOptions(select, '14');
    expect(onSelect).toHaveBeenCalledWith('14');
  });

  test('shows position, gaps and remaining stops for the chosen team', () => {
    render(
      <MyTeamStrip teams={field} myTeam="14" onSelectMyTeam={() => {}} isQualificationMode={false} requiredPitStops={5} />,
    );
    expect(screen.getByText('Team 14')).toBeInTheDocument();
    expect(screen.getAllByText('−5.774').length).toBeGreaterThan(0);
    expect(screen.getAllByText('+6.787').length).toBeGreaterThan(0);
    expect(screen.getByText('2 / 5')).toBeInTheDocument();
    expect(screen.getByText('3 to go')).toBeInTheDocument();
  });

  test('pit alert button calls back with kart and team, and is hidden while in the pits', async () => {
    const onPitAlert = jest.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <MyTeamStrip teams={field} myTeam="14" onSelectMyTeam={() => {}} isQualificationMode={false} requiredPitStops={5} onPitAlert={onPitAlert} />,
    );
    await userEvent.click(screen.getByTitle('Send PIT NOW alert to the driver overlay'));
    expect(onPitAlert).toHaveBeenCalledWith('14', 'Team 14');

    const pitted = field.map((t) => (t.Kart === '14' ? { ...t, Status: 'Pit-in' } : t));
    rerender(
      <MyTeamStrip teams={pitted} myTeam="14" onSelectMyTeam={() => {}} isQualificationMode={false} requiredPitStops={5} onPitAlert={onPitAlert} />,
    );
    expect(screen.queryByTitle('Send PIT NOW alert to the driver overlay')).toBeNull();
  });

  test('the team name is the change control: opens the picker in place, can be cancelled or used', async () => {
    const onSelect = jest.fn();
    render(
      <MyTeamStrip teams={field} myTeam="14" onSelectMyTeam={onSelect} isQualificationMode={false} requiredPitStops={5} />,
    );
    expect(screen.queryByLabelText('Choose your team')).toBeNull();
    await userEvent.click(screen.getByLabelText('Change my team'));
    expect(screen.getByLabelText('Choose your team')).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('Cancel team change'));
    expect(screen.queryByLabelText('Choose your team')).toBeNull();
    await userEvent.click(screen.getByLabelText('Change my team'));
    await userEvent.selectOptions(screen.getByLabelText('Choose your team'), '21');
    expect(onSelect).toHaveBeenCalledWith('21');
    expect(screen.queryByLabelText('Choose your team')).toBeNull();
  });
});
