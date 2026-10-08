/**
 * The planned schedule must always span exactly the configured race length:
 * changing the race length or the pit duration has to rebuild the plan, and
 * per-stint rounding must not lose or invent minutes.
 *
 * These invariants live in lib/stintPlan.ts and are tested directly here —
 * the UI (timeline blocks, editor) is a thin projection over the same table,
 * so pinning the maths keeps the regression checks independent of markup.
 */
import {
  buildStintTable,
  drivingTime,
  planFitsConfig,
  planSignature,
  plannedSpan,
  StintConfig,
} from '@/app/components/RaceDashboard/lib/stintPlan';

const cfg = (over: Partial<StintConfig> = {}): StintConfig => ({
  numStints: 10,
  minStintTime: 25,
  maxStintTime: 60,
  pitDuration: 5,
  numDrivers: 4,
  totalRaceTime: 358,
  ...over,
});

describe('StintPlanner schedule', () => {
  test('a 358 minute race with 10 stints is planned over 358 minutes, not the previous length', () => {
    const c = cfg();
    const table = buildStintTable(c);
    expect(table).toHaveLength(10);
    expect(plannedSpan(table, c)).toBe(358);
  });

  test('changing the race length alone rebuilds the plan', () => {
    for (const total of [240, 358]) {
      const c = cfg({ totalRaceTime: total });
      expect(plannedSpan(buildStintTable(c), c)).toBe(total);
    }
    expect(planSignature(cfg({ totalRaceTime: 240 }))).not.toBe(
      planSignature(cfg({ totalRaceTime: 358 })),
    );
  });

  test('changing the pit duration rebuilds the plan to still fit the race', () => {
    const c = cfg({ pitDuration: 3, totalRaceTime: 358 });
    expect(plannedSpan(buildStintTable(c), c)).toBe(358);
  });

  test('the schedule fills the race exactly for awkward divisions', () => {
    for (const [stints, total] of [['7', '358'], ['11', '359'], ['13', '361'], ['9', '400']]) {
      const c = cfg({ numStints: Number(stints), totalRaceTime: Number(total) });
      const table = buildStintTable(c);
      expect(table).toHaveLength(Number(stints));
      expect(plannedSpan(table, c)).toBe(Number(total));
    }
  });

  test('the last stint ends at the chequered flag', () => {
    const c = cfg();
    const table = buildStintTable(c);
    expect(table[table.length - 1].endTime).toBe(c.totalRaceTime);
  });

  test('the summary spells out stints versus pit stops and the planned total', () => {
    const c = cfg();
    const table = buildStintTable(c);
    expect(table).toHaveLength(c.numStints); // N stints
    expect(c.numStints - 1).toBe(9); // N-1 pit stops
    expect(plannedSpan(table, c)).toBe(c.totalRaceTime); // Planned X of Y
    expect(planFitsConfig(table, c)).toBe(true); // not short/over
    expect(drivingTime(c)).toBe(c.totalRaceTime - c.pitDuration * (c.numStints - 1));
  });

  test('a plan that no longer fits the race is flagged rather than left silent', () => {
    const c = cfg();
    const table = buildStintTable(c);
    // Shorten the LAST stint: there is nothing after it to absorb the time,
    // so the plan now stops short of the flag.
    const shortened = table.map((s, i) =>
      i === table.length - 1 ? { ...s, duration: 25 } : s,
    );
    expect(plannedSpan(shortened, c)).toBeLessThan(c.totalRaceTime);
    expect(planFitsConfig(shortened, c)).toBe(false);
  });
});
