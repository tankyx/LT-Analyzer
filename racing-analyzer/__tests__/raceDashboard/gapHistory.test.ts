/**
 * Client-side gap history for the Delta chart.
 *
 * Phase 2 removed the backend's `gap_history`; this helper rebuilds the
 * per-lap series from the deltas computed in the dashboard. One point is
 * appended each time a monitored kart's `Last Lap` changes (a completed lap),
 * the first sample is seeded immediately, and unmonitored karts are forgotten.
 */

jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://api.test',
  WS_BASE_URL: 'ws://api.test',
  TURNSTILE_SITE_KEY: '',
  INVITE_REQUIRED: true,
}));

import { appendLapGapHistory, buildGapHistoryFromSeries, MAX_GAP_HISTORY } from '@/app/components/RaceDashboard';

const team = (kart: string, lastLap: string) => ({ Kart: kart, 'Last Lap': lastLap });
const delta = (gap: number, adjusted_gap?: number) => ({ gap, adjusted_gap });

describe('appendLapGapHistory', () => {
  test('seeds the first sample immediately so the chart draws at once', () => {
    const next = appendLapGapHistory({}, ['12'], { '12': delta(3.5, 4.0) }, [team('12', '1:02.000')]);
    expect(next['12']).toEqual({ gaps: [3.5], adjusted_gaps: [4.0], last_update: '1:02.000' });
  });

  test('appends a point when the lap time changes', () => {
    const first = appendLapGapHistory({}, ['12'], { '12': delta(3.5) }, [team('12', '1:02.000')]);
    const second = appendLapGapHistory(first, ['12'], { '12': delta(2.1) }, [team('12', '1:01.500')]);
    expect(second['12'].gaps).toEqual([3.5, 2.1]);
    expect(second['12'].last_update).toBe('1:01.500');
  });

  test('does not append while the lap is unchanged', () => {
    const first = appendLapGapHistory({}, ['12'], { '12': delta(3.5) }, [team('12', '1:02.000')]);
    const second = appendLapGapHistory(first, ['12'], { '12': delta(9.9) }, [team('12', '1:02.000')]);
    expect(second).toBe(first); // same reference: nothing changed
    expect(second['12'].gaps).toEqual([3.5]);
  });

  test('falls back to the raw gap when no adjusted gap is supplied', () => {
    const next = appendLapGapHistory({}, ['12'], { '12': delta(3.5) }, [team('12', '1:02.000')]);
    expect(next['12'].adjusted_gaps).toEqual([3.5]);
  });

  test('skips karts with no last-lap yet and unknown karts', () => {
    const next = appendLapGapHistory(
      {},
      ['12', '99'],
      { '12': delta(3.5), '99': delta(1.0) },
      [team('12', ''), team('99', '')],
    );
    expect(next).toEqual({});
  });

  test('forgets karts that are no longer monitored', () => {
    const first = appendLapGapHistory({}, ['12', '7'], { '12': delta(3.5), '7': delta(1.2) },
      [team('12', '1:02.000'), team('7', '1:03.000')]);
    expect(Object.keys(first).sort()).toEqual(['12', '7']);

    const second = appendLapGapHistory(first, ['12'], { '12': delta(3.5) }, [team('12', '1:02.000')]);
    expect(Object.keys(second)).toEqual(['12']);
  });

  test('caps the series to the most recent entries', () => {
    let history = appendLapGapHistory({}, ['12'], { '12': delta(0) }, [team('12', 'lap-0')], 3);
    for (let i = 1; i < 6; i++) {
      history = appendLapGapHistory(history, ['12'], { '12': delta(i) }, [team('12', `lap-${i}`)], 3);
    }
    expect(history['12'].gaps).toEqual([3, 4, 5]);
    expect(history['12'].adjusted_gaps).toEqual([3, 4, 5]);
    expect(history['12'].last_update).toBe('lap-5');
  });

  test('default cap bounds memory', () => {
    let history = appendLapGapHistory({}, ['12'], { '12': delta(0) }, [team('12', 'lap-0')]);
    for (let i = 1; i < MAX_GAP_HISTORY + 10; i++) {
      history = appendLapGapHistory(history, ['12'], { '12': delta(i) }, [team('12', `lap-${i}`)]);
    }
    expect(history['12'].gaps).toHaveLength(MAX_GAP_HISTORY);
    expect(history['12'].gaps[history['12'].gaps.length - 1]).toBe(MAX_GAP_HISTORY + 9);
  });
});

// Per-lap gap (seconds) + cumulative pit count, keyed by kart.
const lap = (gap_seconds: number | null, pit_stops = 0, lap_time = '1:00.000') =>
  ({ lap: 0, gap: gap_seconds == null ? '1 Tour' : String(gap_seconds), gap_seconds, lap_time, pit_stops });
const seriesEntry = (kart: string, laps: ReturnType<typeof lap>[]) => ({ kart, team: `Team ${kart}`, laps });

describe('buildGapHistoryFromSeries', () => {
  test('turns per-lap gap-to-leader into a head-to-head series', () => {
    const series = {
      '1': seriesEntry('1', [lap(0), lap(0), lap(0)]),
      '7': seriesEntry('7', [lap(2), lap(3.5), lap(5)]),
    };
    const history = buildGapHistoryFromSeries(series, '1', ['7'], 158, 7);
    expect(history['7'].gaps).toEqual([2, 3.5, 5]);
    expect(history['7'].last_update).toBe('1:00.000');
  });

  test('subtracts my team gaps when it is not the leader', () => {
    const series = {
      '1': seriesEntry('1', [lap(1), lap(1.5)]),
      '7': seriesEntry('7', [lap(3), lap(5)]),
    };
    const history = buildGapHistoryFromSeries(series, '1', ['7'], 158, 7);
    expect(history['7'].gaps).toEqual([2, 3.5]);
  });

  test('skips lapped laps where a seconds gap is meaningless', () => {
    const series = {
      '1': seriesEntry('1', [lap(0), lap(0), lap(0)]),
      '7': seriesEntry('7', [lap(2), lap(null), lap(6)]),
    };
    const history = buildGapHistoryFromSeries(series, '1', ['7'], 158, 7);
    expect(history['7'].gaps).toEqual([2, 6]);
  });

  test('applies completed-stop (150s) and remaining-stop compensation', () => {
    const series = {
      '1': seriesEntry('1', [lap(0, 0), lap(0, 0)]),
      '7': seriesEntry('7', [lap(2, 0), lap(3, 1)]),
    };
    const history = buildGapHistoryFromSeries(series, '1', ['7'], 158, 7);
    // lap 2: +3s track, one completed stop -> +150; remaining stop one fewer
    // for the rival -> -158 in the adjusted series.
    expect(history['7'].gaps).toEqual([2, 153]);
    expect(history['7'].adjusted_gaps).toEqual([2, -5]);
  });

  test('returns nothing when our own team has no laps recorded', () => {
    const series = { '7': seriesEntry('7', [lap(2)]) };
    expect(buildGapHistoryFromSeries(series, '1', ['7'], 158, 7)).toEqual({});
  });

  test('caps the seeded series to the most recent entries', () => {
    const laps = Array.from({ length: 8 }, (_, i) => lap(i));
    const series = { '1': seriesEntry('1', laps.map(() => lap(0))), '7': seriesEntry('7', laps) };
    const history = buildGapHistoryFromSeries(series, '1', ['7'], 158, 7, 3);
    expect(history['7'].gaps).toEqual([5, 6, 7]);
  });

  test('keeps last_update at the latest lap even when its point was skipped', () => {
    const series = {
      '1': seriesEntry('1', [lap(0), lap(0)]),
      '7': seriesEntry('7', [lap(2), lap(null, 0, '1:09.999')]),
    };
    const history = buildGapHistoryFromSeries(series, '1', ['7'], 158, 7);
    expect(history['7'].gaps).toEqual([2]);
    expect(history['7'].last_update).toBe('1:09.999');
  });
});
