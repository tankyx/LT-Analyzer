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

import { appendLapGapHistory, MAX_GAP_HISTORY } from '@/app/components/RaceDashboard';

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
