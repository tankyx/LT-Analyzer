/**
 * Stint-schedule maths for the planner.
 *
 * The invariant everything here serves: the planned schedule spans exactly
 * the configured race length. Stint time plus the pit stops between stints
 * must add up to `totalRaceTime`, with no minutes lost to rounding and none
 * invented.
 */

export interface StintConfig {
  numStints: number;
  minStintTime: number;
  maxStintTime: number;
  pitDuration: number;
  numDrivers: number;
  totalRaceTime: number;
}

export interface StintAssignment {
  driver: number;
  stint: number;
  duration: number;
  isJoker: boolean;
  isLong: boolean;
  startTime: number;
  endTime: number;
}

/** Minutes, to one decimal — the finest granularity the planner offers. */
export const roundTenth = (n: number): number => Math.round(n * 10) / 10;

/** Time available for driving: the race minus every pit stop between stints. */
export const drivingTime = (cfg: StintConfig): number =>
  roundTenth(cfg.totalRaceTime - cfg.pitDuration * Math.max(0, cfg.numStints - 1));

/**
 * Split `available` minutes across `numStints` stints so the parts sum to
 * exactly `available`.
 *
 * Dividing and rounding each stint independently loses or invents up to half
 * a minute per stint — a 358 minute race over 10 stints came out as 355. Here
 * the whole-minute remainder is handed to the earliest stints (longer first,
 * which is what a team wants while the track is quiet) and any sub-minute
 * remainder goes to the last stint, so nothing is dropped.
 */
export const distributeStintTime = (available: number, numStints: number): number[] => {
  if (numStints <= 0) return [];
  if (available <= 0) return new Array(numStints).fill(0);

  const base = Math.floor(available / numStints);
  const remainder = roundTenth(available - base * numStints);
  // 1e-9 absorbs float noise so 2.9999999 counts as the 3 whole minutes it is.
  const wholeMinutesToShare = Math.floor(remainder + 1e-9);
  const subMinute = roundTenth(remainder - wholeMinutesToShare);

  const durations = Array.from(
    { length: numStints },
    (_, i) => base + (i < wholeMinutesToShare ? 1 : 0),
  );
  if (subMinute > 0) {
    durations[numStints - 1] = roundTenth(durations[numStints - 1] + subMinute);
  }
  return durations;
};

/**
 * Build a fresh stint table for a config: drivers in rotation, stint lengths
 * filling the race exactly, and running start/end times.
 */
export const buildStintTable = (cfg: StintConfig): StintAssignment[] => {
  const durations = distributeStintTime(drivingTime(cfg), cfg.numStints);
  const assignments: StintAssignment[] = [];
  let currentTime = 0;

  durations.forEach((duration, index) => {
    assignments.push({
      driver: (index % Math.max(1, cfg.numDrivers)) + 1,
      stint: index + 1,
      duration,
      isJoker: false,
      isLong: false,
      startTime: roundTenth(currentTime),
      endTime: roundTenth(currentTime + duration),
    });
    currentTime = roundTenth(currentTime + duration);
    if (index < durations.length - 1) {
      currentTime = roundTenth(currentTime + cfg.pitDuration);
    }
  });

  return assignments;
};

/** Wall-clock the plan occupies: driving plus the pit stops between stints. */
export const plannedSpan = (assignments: StintAssignment[], cfg: StintConfig): number => {
  if (assignments.length === 0) return 0;
  const driving = assignments.reduce((total, s) => total + s.duration, 0);
  return roundTenth(driving + cfg.pitDuration * (assignments.length - 1));
};

/** Does this table still describe this race? */
export const planFitsConfig = (assignments: StintAssignment[], cfg: StintConfig): boolean => {
  if (assignments.length === 0 || assignments.length !== cfg.numStints) return false;
  return Math.abs(plannedSpan(assignments, cfg) - cfg.totalRaceTime) < 0.05;
};

/**
 * The race parameters a table is built from. When this changes, the table no
 * longer describes the race and has to be rebuilt — the old code only watched
 * the stint count, so editing the race length left the previous schedule in
 * place and the planner kept planning the old race.
 */
export const planSignature = (cfg: StintConfig): string =>
  [cfg.numStints, cfg.numDrivers, cfg.totalRaceTime, cfg.pitDuration].join('|');
