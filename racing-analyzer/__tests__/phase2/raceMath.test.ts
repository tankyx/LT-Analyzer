import {
  parseTimeToSeconds,
  gapToLeaderSeconds,
  pitStopsCount,
  headToHeadGap,
  adjustedGap,
  calculateTrend,
  buildDelta,
} from '@/utils/raceMath';

describe('parseTimeToSeconds', () => {
  test('M:SS.mmm form', () => {
    expect(parseTimeToSeconds('1:23.456')).toBeCloseTo(83.456, 3);
  });
  test('SS.mmm form', () => {
    expect(parseTimeToSeconds('59.999')).toBeCloseTo(59.999, 3);
  });
  test('empty / null', () => {
    expect(parseTimeToSeconds('')).toBe(0);
    expect(parseTimeToSeconds(null)).toBe(0);
    expect(parseTimeToSeconds(undefined)).toBe(0);
  });
});

describe('gapToLeaderSeconds', () => {
  test('plain number form', () => {
    expect(gapToLeaderSeconds({ Gap: '12.345' })).toBeCloseTo(12.345);
  });
  test('M:SS form', () => {
    expect(gapToLeaderSeconds({ Gap: '1:05.500' })).toBeCloseTo(65.5);
  });
  test('lapped team returns Infinity', () => {
    expect(gapToLeaderSeconds({ Gap: '1 Tour' })).toBe(Number.POSITIVE_INFINITY);
  });
  test('empty / missing', () => {
    expect(gapToLeaderSeconds({})).toBe(0);
    expect(gapToLeaderSeconds({ Gap: '' })).toBe(0);
  });
});

describe('pitStopsCount', () => {
  test('parses integer', () => {
    expect(pitStopsCount({ 'Pit Stops': '3' })).toBe(3);
  });
  test('missing / empty / non-numeric → 0', () => {
    expect(pitStopsCount({})).toBe(0);
    expect(pitStopsCount({ 'Pit Stops': '' })).toBe(0);
    expect(pitStopsCount({ 'Pit Stops': 'n/a' })).toBe(0);
  });
});

describe('headToHeadGap', () => {
  test('positive when other is further from leader', () => {
    const me = { Gap: '10.0' };
    const other = { Gap: '15.5' };
    expect(headToHeadGap(me, other)).toBeCloseTo(5.5);
  });
  test('negative when other is closer to leader (ahead of me)', () => {
    const me = { Gap: '15.0' };
    const other = { Gap: '10.0' };
    expect(headToHeadGap(me, other)).toBeCloseTo(-5.0);
  });
  test('lapped → NaN', () => {
    expect(headToHeadGap({ Gap: '1 Tour' }, { Gap: '5.0' })).toBeNaN();
    expect(headToHeadGap({ Gap: '5.0' }, { Gap: '2 Tours' })).toBeNaN();
  });
});

describe('adjustedGap', () => {
  const cfg = { pit_stop_time: 150, required_pit_stops: 7 };

  test('all pit stops complete on both sides → no adjustment', () => {
    const me = { Gap: '10', 'Pit Stops': '7' };
    const other = { Gap: '20', 'Pit Stops': '7' };
    expect(adjustedGap(10, me, other, cfg)).toBeCloseTo(10);
  });

  test('I owe one more stop than them → adjusted gap to them is smaller', () => {
    const me = { Gap: '10', 'Pit Stops': '5' };
    const other = { Gap: '20', 'Pit Stops': '6' };
    // raw=10, myRemaining=2, otherRemaining=1 → adjusted = 10 + (1-2)*150 = -140
    expect(adjustedGap(10, me, other, cfg)).toBeCloseTo(-140);
  });

  test('they owe more than me → adjusted gap grows', () => {
    const me = { Gap: '10', 'Pit Stops': '6' };
    const other = { Gap: '20', 'Pit Stops': '5' };
    // raw=10, myRemaining=1, otherRemaining=2 → adjusted = 10 + (2-1)*150 = 160
    expect(adjustedGap(10, me, other, cfg)).toBeCloseTo(160);
  });

  test('NaN raw propagates', () => {
    expect(adjustedGap(Number.NaN, { 'Pit Stops': '0' }, { 'Pit Stops': '0' }, cfg)).toBeNaN();
  });
});

describe('calculateTrend', () => {
  test('empty history → arrow 0', () => {
    expect(calculateTrend(5, [])).toEqual({ value: 0, arrow: 0 });
  });
  test('gap shrinking → -1 arrow', () => {
    const r = calculateTrend(3, [5]);
    expect(r.arrow).toBe(-1);
    expect(r.value).toBeCloseTo(-2);
  });
  test('gap growing → +1 arrow', () => {
    const r = calculateTrend(7, [5]);
    expect(r.arrow).toBe(1);
    expect(r.value).toBeCloseTo(2);
  });
  test('within noise band → arrow 0', () => {
    const r = calculateTrend(5.02, [5]);
    expect(r.arrow).toBe(0);
  });
});

describe('buildDelta', () => {
  test('builds a summary row', () => {
    const me = { Kart: '1', Team: 'ME', Position: '1', Gap: '0', 'Pit Stops': '3', 'Last Lap': '1:01', 'Best Lap': '1:00' };
    const other = { Kart: '2', Team: 'OTHER', Position: '2', Gap: '4.5', 'Pit Stops': '3', 'Last Lap': '1:02', 'Best Lap': '1:00.5' };
    const summary = buildDelta(me, other, { pit_stop_time: 150, required_pit_stops: 7 });
    expect(summary.kart).toBe('2');
    expect(summary.team_name).toBe('OTHER');
    expect(summary.position).toBe(2);
    expect(summary.gap).toBeCloseTo(4.5);
    expect(summary.adjusted_gap).toBeCloseTo(4.5); // same pit stops → no adj
  });
});
