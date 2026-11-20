/**
 * Colours for charts, stint blocks and anything else that paints data.
 *
 * Everything here is a CSS value built on the tokens in globals.css, so it
 * follows the theme with no `isDarkMode` prop and no re-render: Recharts
 * writes these strings into SVG attributes and inline styles, and the
 * browser resolves the variables.
 */

/** Chart chrome. */
export const CHART = {
  axis: 'rgb(var(--c-muted))',
  grid: 'rgb(var(--c-line))',
  ink: 'rgb(var(--c-ink))',
  surface: 'rgb(var(--c-surface))',
  tooltipBg: 'rgb(var(--c-surface-2))',
  tooltipBorder: 'rgb(var(--c-line))',
  live: 'rgb(var(--c-live))',
  alarm: 'rgb(var(--c-alarm))',
  info: 'rgb(var(--c-info))',
  accent: 'rgb(var(--c-accent))',
  best: 'rgb(var(--c-best))',
} as const;

export const SERIES_COUNT = 10;

const slot = (index: number): number => (((Math.trunc(index) % SERIES_COUNT) + SERIES_COUNT) % SERIES_COUNT) + 1;

/** The data palette, in order: stints, chart series, pit lanes. Wraps after
 *  ten. Pass `alpha` for a translucent fill. Fills and strokes only. */
export const seriesColor = (index: number, alpha?: number): string =>
  alpha === undefined ? `rgb(var(--c-series-${slot(index)}))` : `rgb(var(--c-series-${slot(index)}) / ${alpha})`;

// The series colours are the same in both themes, so the text that sits on
// them is fixed too: whichever of near-black and white reads better on each
// (4.5:1 or more on all but indigo, which is 4.47 with white).
const DARK_INK = 'rgb(10 13 19)';
const LIGHT_INK = 'rgb(255 255 255)';
const SERIES_INK = [DARK_INK, DARK_INK, LIGHT_INK, DARK_INK, LIGHT_INK, DARK_INK, DARK_INK, DARK_INK, DARK_INK, LIGHT_INK];

/** Text colour for a label on `seriesColor(index)`. */
export const seriesInk = (index: number): string => SERIES_INK[slot(index) - 1];

/** Background + text for a block filled with a series colour. */
export const seriesBlock = (index: number): { backgroundColor: string; color: string } => ({
  backgroundColor: seriesColor(index),
  color: seriesInk(index),
});

/**
 * A team's livery colour on the delta chart and the standings: one stable hue
 * per kart number (golden-ratio spread, so neighbours differ), with the
 * lightness taken from `--livery-l` so it reads on either theme.
 */
export const liveryColor = (kartNumber: string | number): string => {
  const kartId = parseInt(String(kartNumber), 10) || 0;
  const hue = Math.round(((kartId * 0.618033988749895) % 1) * 360);
  const saturation = 70 + (kartId % 3) * 10;
  return `hsl(${hue} ${saturation}% var(--livery-l))`;
};
