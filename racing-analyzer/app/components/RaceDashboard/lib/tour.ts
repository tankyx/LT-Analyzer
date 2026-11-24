/** One stop on the feature tour. */
export interface TourStep {
  id: string;
  title: string;
  body: string;
  /**
   * CSS selectors for the element to spotlight, most specific first. The
   * first one that is on screen wins; with none, the step is shown without a
   * spotlight rather than skipped.
   */
  targets: string[];
  /** Tab to bring forward while this step is shown. */
  tab?: string;
}

const tabStep = (id: string, title: string, body: string): TourStep => ({
  id,
  title,
  body,
  targets: [`[data-tour="tab-${id}"]`],
  tab: id,
});

/** The first-launch tour: where each feature lives, in screen order. */
export const TOUR_STEPS: TourStep[] = [
  {
    id: 'track',
    title: 'Your track',
    body: 'This is the track you are watching. Tap it to switch; tracks with a session running are listed first.',
    targets: ['[data-tour="track"]'],
  },
  {
    id: 'team',
    title: 'Your team',
    body: 'Pick your team here. It pins your position, lap times and the gaps to the karts ahead and behind. Once a team is pinned, the bell sends a pit alert.',
    targets: ['[data-tour="my-team"]'],
  },
  {
    id: 'standings',
    title: 'Standings',
    body: 'The live order with last lap, best lap and gap. Tap the star on a row to follow that team as a rival.',
    targets: ['[data-tour="standings"] [role="row"]', '[data-tour="standings"]'],
    tab: 'standings',
  },
  tabStep(
    'monitored',
    'Monitored',
    'Your starred rivals, with the gap measured from your team. Adjusted gaps count the pit stops each side still has to make.',
  ),
  tabStep('pace', 'Pace', 'How your lap pace compares with the rest of the field at the same moment, stint by stint.'),
  tabStep('chart', 'Delta', 'Your gap to each starred rival across the last 15 laps, so you can see who is closing.'),
  tabStep('stints', 'Stints', 'Plan driver stints and pit windows, and keep a saved plan for each race format.'),
  tabStep(
    'fleet',
    'Fleet',
    'Track which physical kart each team is on, and spot the fast ones as they come into the pits.',
  ),
  {
    id: 'guide',
    title: 'Guide',
    body: 'This tour and the quick start live here. Next up: four steps to set up your pit wall.',
    targets: ['[data-tour="guide"]'],
  },
];

export interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

/**
 * The first candidate that is actually laid out. The standings tower and the
 * tab bars are rendered twice, one copy hidden per breakpoint, so a plain
 * querySelector would often return the hidden one.
 */
export function findTourTarget(selectors: string[], root: ParentNode = document): HTMLElement | null {
  for (const selector of selectors) {
    const nodes = Array.from(root.querySelectorAll<HTMLElement>(selector));
    const visible = nodes.find((el) => el.getClientRects().length > 0);
    if (visible) return visible;
  }
  return null;
}

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(value, Math.max(min, max)));

/** The spotlight: the target grown by `pad`, cut off at the viewport edges. */
export function spotlightBox(target: Box, viewport: Size, pad = 6): Box {
  const top = Math.max(0, target.top - pad);
  const left = Math.max(0, target.left - pad);
  const bottom = Math.min(viewport.height, target.top + target.height + pad);
  const right = Math.min(viewport.width, target.left + target.width + pad);
  return { top, left, width: Math.max(0, right - left), height: Math.max(0, bottom - top) };
}

/**
 * Where the tour card goes: below the target, else above, else beside it,
 * always inside the viewport. A target too big to sit beside (the standings
 * panel on a phone) gets the card laid over its lower edge. With no target
 * the card is centred.
 */
export function placeTourCard(
  target: Box | null,
  card: Size,
  viewport: Size,
  gap = 12,
  margin = 12,
): { top: number; left: number } {
  const maxLeft = viewport.width - card.width - margin;
  const maxTop = viewport.height - card.height - margin;

  if (!target) {
    return {
      top: clamp((viewport.height - card.height) / 2, margin, maxTop),
      left: clamp((viewport.width - card.width) / 2, margin, maxLeft),
    };
  }

  const alignedLeft = clamp(target.left + target.width / 2 - card.width / 2, margin, maxLeft);
  const alignedTop = clamp(target.top + target.height / 2 - card.height / 2, margin, maxTop);

  const below = target.top + target.height + gap;
  if (below <= maxTop) return { top: below, left: alignedLeft };

  const above = target.top - gap - card.height;
  if (above >= margin) return { top: above, left: alignedLeft };

  const right = target.left + target.width + gap;
  if (right <= maxLeft) return { top: alignedTop, left: right };

  const left = target.left - gap - card.width;
  if (left >= margin) return { top: alignedTop, left };

  return { top: clamp(maxTop, margin, maxTop), left: alignedLeft };
}
