/**
 * Schedule maths: the planned stints plus the pit stops between them must
 * add up to exactly the race length, for any division.
 */
import {
  buildStintTable,
  distributeStintTime,
  drivingTime,
  planFitsConfig,
  planSignature,
  plannedSpan,
  roundTenth,
  StintConfig,
} from '@/app/components/RaceDashboard/lib/stintPlan';

const cfg = (over: Partial<StintConfig> = {}): StintConfig => ({
  numStints: 8,
  minStintTime: 25,
  maxStintTime: 60,
  pitDuration: 5,
  numDrivers: 4,
  totalRaceTime: 360,
  ...over,
});

describe('distributeStintTime', () => {
  test('splits evenly when it divides', () => {
    expect(distributeStintTime(300, 10)).toEqual([30, 30, 30, 30, 30, 30, 30, 30, 30, 30]);
  });

  test('hands the leftover whole minutes to the earliest stints', () => {
    // 313 over 10 stints: three stints of 32, seven of 31.
    expect(distributeStintTime(313, 10)).toEqual([32, 32, 32, 31, 31, 31, 31, 31, 31, 31]);
  });

  test('always sums to exactly the time available', () => {
    for (let available = 45; available <= 900; available += 7) {
      for (let stints = 1; stints <= 20; stints++) {
        const parts = distributeStintTime(available, stints);
        expect(parts).toHaveLength(stints);
        expect(roundTenth(parts.reduce((a, b) => a + b, 0))).toBe(available);
      }
    }
  });

  test('carries a sub-minute remainder on the last stint', () => {
    const parts = distributeStintTime(340.5, 8);
    expect(roundTenth(parts.reduce((a, b) => a + b, 0))).toBe(340.5);
    expect(parts[parts.length - 1]).toBe(42.5);
  });

  test('degenerate inputs do not produce negative stints', () => {
    expect(distributeStintTime(0, 4)).toEqual([0, 0, 0, 0]);
    expect(distributeStintTime(-30, 4)).toEqual([0, 0, 0, 0]);
    expect(distributeStintTime(100, 0)).toEqual([]);
  });
});

describe('buildStintTable', () => {
  test('the reported case: 358 minutes over 10 stints spans 358, not 355', () => {
    const config = cfg({ numStints: 10, totalRaceTime: 358 });
    const table = buildStintTable(config);

    expect(drivingTime(config)).toBe(313); // 358 minus nine 5-minute stops
    expect(table).toHaveLength(10);
    expect(plannedSpan(table, config)).toBe(358);
    expect(table[table.length - 1].endTime).toBe(358);
  });

  test('spans the race exactly across a wide range of setups', () => {
    for (const totalRaceTime of [90, 240, 358, 359, 361, 720, 1440]) {
      for (const numStints of [1, 2, 5, 7, 10, 11, 13, 20]) {
        for (const pitDuration of [0, 2.5, 5, 12]) {
          const config = cfg({ totalRaceTime, numStints, pitDuration });
          if (drivingTime(config) <= 0) continue;
          const table = buildStintTable(config);
          expect(plannedSpan(table, config)).toBe(totalRaceTime);
          expect(roundTenth(table[table.length - 1].endTime)).toBe(totalRaceTime);
        }
      }
    }
  });

  test('stints run back to back with the pit stop between them', () => {
    const config = cfg({ numStints: 3, totalRaceTime: 100, pitDuration: 5 });
    const table = buildStintTable(config);
    expect(table[0].startTime).toBe(0);
    expect(table[1].startTime).toBe(roundTenth(table[0].endTime + 5));
    expect(table[2].startTime).toBe(roundTenth(table[1].endTime + 5));
  });

  test('drivers rotate through the line-up', () => {
    const table = buildStintTable(cfg({ numStints: 6, numDrivers: 3 }));
    expect(table.map(s => s.driver)).toEqual([1, 2, 3, 1, 2, 3]);
  });

  test('a race shorter than its pit stops yields no driving time, not negative stints', () => {
    const config = cfg({ numStints: 10, totalRaceTime: 30, pitDuration: 10 });
    const table = buildStintTable(config);
    expect(table.every(s => s.duration === 0)).toBe(true);
  });
});

describe('planFitsConfig', () => {
  const config = cfg({ numStints: 10, totalRaceTime: 358 });

  test('accepts a table built for the config', () => {
    expect(planFitsConfig(buildStintTable(config), config)).toBe(true);
  });

  test('rejects a table built for a different race length', () => {
    const stale = buildStintTable(cfg({ numStints: 10, totalRaceTime: 330 }));
    expect(planFitsConfig(stale, config)).toBe(false);
  });

  test('rejects the wrong number of stints, or none', () => {
    expect(planFitsConfig(buildStintTable(cfg({ numStints: 8, totalRaceTime: 358 })), config)).toBe(false);
    expect(planFitsConfig([], config)).toBe(false);
  });
});

describe('planSignature', () => {
  test('changes with any race parameter the table is built from', () => {
    const base = planSignature(cfg());
    expect(planSignature(cfg({ totalRaceTime: 358 }))).not.toBe(base);
    expect(planSignature(cfg({ pitDuration: 3 }))).not.toBe(base);
    expect(planSignature(cfg({ numStints: 9 }))).not.toBe(base);
    expect(planSignature(cfg({ numDrivers: 5 }))).not.toBe(base);
  });

  test('ignores parameters the table does not depend on', () => {
    expect(planSignature(cfg({ minStintTime: 20, maxStintTime: 70 }))).toBe(planSignature(cfg()));
  });
});
