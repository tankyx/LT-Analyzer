import React from 'react';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FeatureTour from '@/app/components/RaceDashboard/FeatureTour';
import TabbedInterface from '@/app/components/RaceDashboard/TabbedInterface';
import {
  TOUR_STEPS,
  TourStep,
  findTourTarget,
  placeTourCard,
  spotlightBox,
} from '@/app/components/RaceDashboard/lib/tour';

type Rect = { top: number; left: number; width: number; height: number };

const added: HTMLElement[] = [];

/** jsdom has no layout, so give an element the geometry a browser would. */
function layOut(el: HTMLElement, rect: Rect | null): HTMLElement {
  el.getClientRects = () => (rect ? [rect] : []) as unknown as DOMRectList;
  el.getBoundingClientRect = () =>
    ({
      ...(rect ?? { top: 0, left: 0, width: 0, height: 0 }),
      right: rect ? rect.left + rect.width : 0,
      bottom: rect ? rect.top + rect.height : 0,
      x: rect?.left ?? 0,
      y: rect?.top ?? 0,
      toJSON: () => ({}),
    }) as DOMRect;
  return el;
}

function addTarget(name: string, rect: Rect | null): HTMLElement {
  const el = layOut(document.createElement('div'), rect);
  el.setAttribute('data-tour', name);
  document.body.appendChild(el);
  added.push(el);
  return el;
}

afterEach(() => {
  added.splice(0).forEach((el) => el.remove());
});

const phone = { width: 360, height: 740 };
const desktop = { width: 1440, height: 900 };
const card = { width: 336, height: 190 };

const insideViewport = (pos: { top: number; left: number }, viewport: typeof phone) =>
  pos.top >= 12 &&
  pos.left >= 12 &&
  pos.top + card.height <= viewport.height - 12 &&
  pos.left + card.width <= viewport.width - 12;

describe('TOUR_STEPS', () => {
  test('walks the screen from the track to the guide, each stop once', () => {
    const ids = TOUR_STEPS.map((s) => s.id);
    expect(ids).toEqual(['track', 'team', 'standings', 'monitored', 'pace', 'chart', 'stints', 'fleet', 'guide']);
    expect(new Set(ids).size).toBe(ids.length);
    expect(TOUR_STEPS.every((s) => s.title && s.body && s.targets.length > 0)).toBe(true);
  });

  test('every tab step points at a tab button TabbedInterface really renders', () => {
    const tabSteps = TOUR_STEPS.filter((s) => s.tab && s.id !== 'standings');
    const tabs = [{ id: 'standings', label: 'Standings' }, ...tabSteps.map((s) => ({ id: s.id, label: s.title }))];
    const { container } = render(
      <TabbedInterface tabs={tabs} pinnedId="standings">
        {tabs.map((t) => (
          <div key={t.id}>{t.label} panel</div>
        ))}
      </TabbedInterface>,
    );
    expect(tabSteps.map((s) => s.id)).toEqual(['monitored', 'pace', 'chart', 'stints', 'fleet']);
    for (const step of tabSteps) {
      expect(step.tab).toBe(step.id);
      // One in the desktop dock, one in the phone bar.
      expect(container.querySelectorAll(step.targets[0])).toHaveLength(2);
    }
  });
});

describe('findTourTarget', () => {
  test('returns the copy that is laid out, not the hidden one', () => {
    addTarget('tab-pace', null); // the copy hidden at this breakpoint
    const shown = addTarget('tab-pace', { top: 680, left: 120, width: 60, height: 56 });
    expect(findTourTarget(['[data-tour="tab-pace"]'])).toBe(shown);
  });

  test('falls back through the candidates, then to nothing', () => {
    const panel = addTarget('standings', { top: 200, left: 0, width: 340, height: 600 });
    expect(findTourTarget(['[data-tour="standings"] [role="row"]', '[data-tour="standings"]'])).toBe(panel);
    expect(findTourTarget(['[data-tour="missing"]'])).toBeNull();
  });
});

describe('spotlightBox', () => {
  test('grows the target by the padding', () => {
    expect(spotlightBox({ top: 100, left: 50, width: 200, height: 40 }, desktop)).toEqual({
      top: 94,
      left: 44,
      width: 212,
      height: 52,
    });
  });

  test('is cut off at the viewport edges', () => {
    expect(spotlightBox({ top: 0, left: 0, width: 360, height: 56 }, phone)).toEqual({
      top: 0,
      left: 0,
      width: 360,
      height: 62,
    });
    const bottomBar = spotlightBox({ top: 684, left: 300, width: 60, height: 56 }, phone);
    expect(bottomBar.top + bottomBar.height).toBe(740);
    expect(bottomBar.left + bottomBar.width).toBe(360);
  });
});

describe('placeTourCard', () => {
  test('goes below a target near the top, centred on it and kept on screen', () => {
    const trackButton = { top: 8, left: 12, width: 220, height: 40 };
    const pos = placeTourCard(trackButton, card, phone);
    expect(pos.top).toBe(8 + 40 + 12);
    expect(pos.left).toBe(12); // would centre off the left edge; clamped
    expect(insideViewport(pos, phone)).toBe(true);
  });

  test('goes above a target in the bottom tab bar', () => {
    const tab = { top: 684, left: 120, width: 60, height: 56 };
    const pos = placeTourCard(tab, card, phone);
    expect(pos.top + card.height).toBe(684 - 12);
    expect(insideViewport(pos, phone)).toBe(true);
  });

  test('sits beside the full-height timing tower on desktop', () => {
    const tower = { top: 56, left: 0, width: 380, height: 844 };
    const pos = placeTourCard(tower, card, desktop);
    expect(pos.left).toBe(380 + 12);
    expect(insideViewport(pos, desktop)).toBe(true);
  });

  test('lays over the bottom of a target that fills a phone screen', () => {
    const panel = { top: 180, left: 12, width: 336, height: 520 };
    const pos = placeTourCard(panel, card, phone);
    expect(pos.top).toBe(phone.height - card.height - 12);
    expect(insideViewport(pos, phone)).toBe(true);
  });

  test('is centred when there is nothing to point at', () => {
    expect(placeTourCard(null, card, desktop)).toEqual({ top: (900 - 190) / 2, left: (1440 - 336) / 2 });
  });

  test('never leaves the viewport, wherever the target is', () => {
    for (const viewport of [phone, desktop]) {
      for (const top of [0, 100, 400, viewport.height - 60]) {
        for (const left of [0, viewport.width / 2 - 30, viewport.width - 60]) {
          const pos = placeTourCard({ top, left, width: 60, height: 56 }, card, viewport);
          expect(insideViewport(pos, viewport)).toBe(true);
        }
      }
    }
  });
});

describe('FeatureTour', () => {
  const steps: TourStep[] = [
    { id: 'track', title: 'Your track', body: 'Where you are.', targets: ['[data-tour="track"]'] },
    { id: 'pace', title: 'Pace', body: 'How fast.', targets: ['[data-tour="tab-pace"]'], tab: 'pace' },
    { id: 'guide', title: 'Guide', body: 'Come back here.', targets: ['[data-tour="guide"]'] },
  ];
  const setUp = (over: Partial<React.ComponentProps<typeof FeatureTour>> = {}) => {
    const props = { steps, onShowTab: jest.fn(), onClose: jest.fn(), onOpenQuickStart: jest.fn(), ...over };
    render(<FeatureTour {...props} />);
    return props;
  };
  const tour = () => screen.getByRole('dialog', { name: 'Feature tour' });

  test('starts on the first step, with the way forward focused and no way back', () => {
    const props = setUp();
    expect(tour()).toHaveTextContent('Tour · 1 of 3');
    expect(screen.getByRole('heading', { name: 'Your track' })).toBeInTheDocument();
    expect(screen.getByText('Where you are.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toHaveFocus();
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
    expect(props.onShowTab).not.toHaveBeenCalled();
  });

  test('Next and Back move through the steps and bring each step’s tab forward', async () => {
    const props = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(tour()).toHaveTextContent('Tour · 2 of 3');
    expect(screen.getByRole('heading', { name: 'Pace' })).toBeInTheDocument();
    expect(props.onShowTab).toHaveBeenCalledTimes(1);
    expect(props.onShowTab).toHaveBeenCalledWith('pace');

    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('heading', { name: 'Your track' })).toBeInTheDocument();
    expect(props.onShowTab).toHaveBeenCalledTimes(1);
  });

  test('the arrow keys move through it too', async () => {
    setUp();
    await userEvent.keyboard('{ArrowRight}{ArrowRight}');
    expect(screen.getByRole('heading', { name: 'Guide' })).toBeInTheDocument();
    await userEvent.keyboard('{ArrowRight}'); // already at the end
    expect(tour()).toHaveTextContent('Tour · 3 of 3');
    await userEvent.keyboard('{ArrowLeft}');
    expect(screen.getByRole('heading', { name: 'Pace' })).toBeInTheDocument();
  });

  test('the last step offers the quick start or a plain finish', async () => {
    const props = setUp();
    await userEvent.keyboard('{ArrowRight}{ArrowRight}');
    expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Quick start' })).toHaveFocus();

    await userEvent.click(screen.getByRole('button', { name: 'Quick start' }));
    expect(props.onOpenQuickStart).toHaveBeenCalledTimes(1);
    expect(props.onClose).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  test('can be skipped at any point, by button or Escape', async () => {
    const props = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Skip the tour' }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
    await userEvent.keyboard('{Escape}');
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  test('spotlights the element the step points at', () => {
    addTarget('track', { top: 100, left: 50, width: 200, height: 40 });
    setUp();
    expect(screen.getByTestId('tour-spotlight')).toHaveStyle({
      top: '94px',
      left: '44px',
      width: '212px',
      height: '52px',
    });
  });

  test('follows the element when it moves', () => {
    jest.useFakeTimers();
    try {
      const el = addTarget('track', { top: 100, left: 50, width: 200, height: 40 });
      setUp();
      layOut(el, { top: 300, left: 50, width: 200, height: 40 });
      act(() => {
        jest.advanceTimersByTime(300);
      });
      expect(screen.getByTestId('tour-spotlight')).toHaveStyle({ top: '294px' });
    } finally {
      jest.useRealTimers();
    }
  });

  test('a step with nothing on screen to point at is still shown, without a spotlight', () => {
    setUp();
    expect(screen.queryByTestId('tour-spotlight')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Your track' })).toBeInTheDocument();
  });

  test('the full tour visits every tab in order', async () => {
    const props = setUp({ steps: undefined });
    expect(tour()).toHaveTextContent(`Tour · 1 of ${TOUR_STEPS.length}`);
    for (let i = 1; i < TOUR_STEPS.length; i += 1) {
      await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    }
    expect(screen.getByRole('heading', { name: 'Guide' })).toBeInTheDocument();
    expect(props.onShowTab.mock.calls.map(([id]) => id)).toEqual([
      'standings',
      'monitored',
      'pace',
      'chart',
      'stints',
      'fleet',
    ]);
  });
});

describe('TabbedInterface with the parent owning the tab', () => {
  const tabs = [
    { id: 'standings', label: 'Standings' },
    { id: 'pace', label: 'Pace' },
    { id: 'fleet', label: 'Fleet' },
  ];
  const panel = (id: string) => document.getElementById(`tab-panel-${id}`);
  const shell = (activeTab: string | undefined, onTabChange = jest.fn()) => (
    <TabbedInterface tabs={tabs} defaultTab="standings" activeTab={activeTab} onTabChange={onTabChange}>
      {tabs.map((t) => (
        <div key={t.id}>{t.label} panel</div>
      ))}
    </TabbedInterface>
  );

  test('shows the tab it is told to and only reports clicks', async () => {
    const onTabChange = jest.fn();
    const { rerender } = render(shell('pace', onTabChange));
    expect(panel('pace')).not.toHaveAttribute('hidden');
    expect(panel('fleet')).toHaveAttribute('hidden');

    await userEvent.click(screen.getAllByRole('button', { name: 'Fleet' })[0]);
    expect(onTabChange).toHaveBeenCalledWith('fleet');
    // Still on Pace until the parent says otherwise.
    expect(panel('pace')).not.toHaveAttribute('hidden');

    rerender(shell('fleet', onTabChange));
    expect(panel('fleet')).not.toHaveAttribute('hidden');
    expect(panel('pace')).toHaveAttribute('hidden');
  });

  test('still manages its own tab when none is given', async () => {
    render(shell(undefined));
    expect(panel('standings')).not.toHaveAttribute('hidden');
    await userEvent.click(screen.getAllByRole('button', { name: 'Pace' })[0]);
    expect(panel('pace')).not.toHaveAttribute('hidden');
  });
});
