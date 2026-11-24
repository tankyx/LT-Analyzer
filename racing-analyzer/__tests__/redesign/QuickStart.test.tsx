import React from 'react';
import { render, renderHook, screen, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import HelpDrawer from '@/app/components/RaceDashboard/HelpDrawer';
import { buildQuickStartSteps, QuickStartState } from '@/app/components/RaceDashboard/lib/quickStart';
import { isUnconfigured, useOnboardingOffer, OnboardingPrefs } from '@/app/components/RaceDashboard/lib/onboarding';
import { hasSeenOnboarding, markOnboardingSeen } from '@/app/utils/persistence';

const SEEN_KEY = 'lt_analyzer_onboarding_seen';

const fresh: QuickStartState = {
  trackName: 'Mariembourg',
  hasField: false,
  myTeamLabel: '',
  monitoredCount: 0,
};

beforeEach(() => {
  localStorage.clear();
});

describe('buildQuickStartSteps', () => {
  test('a new account on an idle track: four steps in order, none done', () => {
    const steps = buildQuickStartSteps(fresh);
    expect(steps.map((s) => s.id)).toEqual(['track', 'team', 'rivals', 'pit']);
    expect(steps.every((s) => !s.done)).toBe(true);
    expect(steps[0].status).toBe('Showing Mariembourg');
    // No field yet, so say why there is no team list to pick from.
    expect(steps[1].status).toMatch(/when a session is live/);
    expect(steps[2].status).toBeUndefined();
  });

  test('with a live field the team step needs no explanation', () => {
    const steps = buildQuickStartSteps({ ...fresh, hasField: true });
    expect(steps[1].status).toBeUndefined();
    expect(steps[1].done).toBe(false);
  });

  test('a pinned team and starred rivals tick their steps', () => {
    const steps = buildQuickStartSteps({
      trackName: 'Spa',
      hasField: true,
      myTeamLabel: 'Apex Hunters (#12)',
      monitoredCount: 2,
    });
    expect(steps[1]).toMatchObject({ done: true, status: 'Pinned: Apex Hunters (#12)' });
    expect(steps[2]).toMatchObject({ done: true, status: '2 teams starred' });
    // Track and pit rules always have a value, so they are never ticked.
    expect(steps[0].done).toBe(false);
    expect(steps[3].done).toBe(false);
  });

  test('one starred rival reads in the singular', () => {
    expect(buildQuickStartSteps({ ...fresh, monitoredCount: 1 })[2].status).toBe('1 team starred');
  });

  test('no status line while the track name is still loading', () => {
    expect(buildQuickStartSteps({ ...fresh, trackName: '' })[0].status).toBeUndefined();
  });
});

describe('isUnconfigured', () => {
  test('true only with no team pinned and nobody starred', () => {
    expect(isUnconfigured({ my_team: null, monitored_teams: [] })).toBe(true);
    expect(isUnconfigured({})).toBe(true);
    expect(isUnconfigured({ my_team: '12', monitored_teams: [] })).toBe(false);
    expect(isUnconfigured({ my_team: null, monitored_teams: ['7'] })).toBe(false);
  });
});

describe('onboarding seen flag', () => {
  test('is kept per account and ignores case', () => {
    expect(hasSeenOnboarding('brianb13')).toBe(false);
    markOnboardingSeen('BrianB13');
    expect(hasSeenOnboarding('brianb13')).toBe(true);
    expect(hasSeenOnboarding('tankyx')).toBe(false);
  });

  test('marking twice stores the account once', () => {
    markOnboardingSeen('brianb13');
    markOnboardingSeen('brianb13');
    expect(JSON.parse(localStorage.getItem(SEEN_KEY) || '[]')).toEqual(['brianb13']);
  });

  test('a stored value of the wrong shape reads as nobody', () => {
    localStorage.setItem(SEEN_KEY, JSON.stringify({ brianb13: true }));
    expect(hasSeenOnboarding('brianb13')).toBe(false);
    markOnboardingSeen('brianb13');
    expect(hasSeenOnboarding('brianb13')).toBe(true);
  });
});

describe('useOnboardingOffer', () => {
  type Props = {
    username?: string;
    settled: number | null;
    loaded: { trackId: number; prefs: OnboardingPrefs } | null;
  };
  const empty: OnboardingPrefs = { my_team: null, monitored_teams: [] };
  const setUp = (initial: Props) =>
    renderHook((p: Props) => useOnboardingOffer(p.username, p.settled, p.loaded), { initialProps: initial });

  test('offers the onboarding to an account with nothing set up', () => {
    const { result } = setUp({ username: 'brianb13', settled: 40, loaded: { trackId: 40, prefs: empty } });
    expect(result.current.offered).toBe(true);
    // Not marked until the user closes it, so a reload shows it again.
    expect(hasSeenOnboarding('brianb13')).toBe(false);
  });

  test('waits for the startup track and for that track’s preferences', () => {
    // The dashboard starts on a placeholder track (1) before the real one (40)
    // is known: empty prefs for the placeholder must not trigger the offer.
    const { result, rerender } = setUp({ username: 'tankyx', settled: null, loaded: { trackId: 1, prefs: empty } });
    expect(result.current.offered).toBe(false);

    rerender({ username: 'tankyx', settled: 40, loaded: { trackId: 1, prefs: empty } });
    expect(result.current.offered).toBe(false);

    rerender({ username: 'tankyx', settled: 40, loaded: { trackId: 40, prefs: { my_team: '12', monitored_teams: ['7'] } } });
    expect(result.current.offered).toBe(false);
    // A set-up account is recorded so it is never interrupted later.
    expect(hasSeenOnboarding('tankyx')).toBe(true);
  });

  test('does not offer again once the account has closed it in this browser', () => {
    markOnboardingSeen('brianb13');
    const { result } = setUp({ username: 'brianb13', settled: 40, loaded: { trackId: 40, prefs: empty } });
    expect(result.current.offered).toBe(false);
  });

  test('stays quiet when the preferences never load, and asks again next visit', () => {
    const { result } = setUp({ username: 'brianb13', settled: 40, loaded: null });
    expect(result.current.offered).toBe(false);
    expect(hasSeenOnboarding('brianb13')).toBe(false);
  });

  test('decides once: clearing the team later does not bring the offer back', () => {
    const { result, rerender } = setUp({
      username: 'tankyx',
      settled: 40,
      loaded: { trackId: 40, prefs: { my_team: '12', monitored_teams: [] } },
    });
    localStorage.clear();
    rerender({ username: 'tankyx', settled: 40, loaded: { trackId: 40, prefs: empty } });
    expect(result.current.offered).toBe(false);
  });

  test('dismiss withdraws the offer and records the account', () => {
    const { result } = setUp({ username: 'brianb13', settled: 40, loaded: { trackId: 40, prefs: empty } });
    act(() => result.current.dismiss());
    expect(result.current.offered).toBe(false);
    expect(hasSeenOnboarding('brianb13')).toBe(true);
  });

  test('does nothing without a logged-in user', () => {
    const { result } = setUp({ username: undefined, settled: 40, loaded: { trackId: 40, prefs: empty } });
    expect(result.current.offered).toBe(false);
    act(() => result.current.dismiss());
    expect(localStorage.getItem(SEEN_KEY)).toBeNull();
  });
});

describe('HelpDrawer', () => {
  const quickStart = (over: Partial<QuickStartState> = {}, onChooseTrack = jest.fn()) => ({
    ...fresh,
    ...over,
    onChooseTrack,
  });

  test('opens on the quick start with the four steps and a way out', async () => {
    const onClose = jest.fn();
    render(<HelpDrawer onClose={onClose} initialView="quickstart" quickStart={quickStart()} />);

    expect(screen.getByRole('dialog', { name: 'Quick start' })).toBeInTheDocument();
    const steps = screen.getAllByRole('listitem');
    expect(steps).toHaveLength(4);
    expect(within(steps[0]).getByRole('heading', { name: 'Choose your track' })).toBeInTheDocument();
    expect(within(steps[0]).getByText('Showing Mariembourg')).toBeInTheDocument();
    expect(within(steps[3]).getByRole('heading', { name: 'Set the pit rules' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Got it' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('“Switch track” hands over to the track picker', async () => {
    const onChooseTrack = jest.fn();
    render(<HelpDrawer onClose={jest.fn()} initialView="quickstart" quickStart={quickStart({}, onChooseTrack)} />);
    await userEvent.click(screen.getByRole('button', { name: 'Switch track' }));
    expect(onChooseTrack).toHaveBeenCalledTimes(1);
  });

  test('completed steps are announced as done', () => {
    render(
      <HelpDrawer
        onClose={jest.fn()}
        initialView="quickstart"
        quickStart={quickStart({ hasField: true, myTeamLabel: 'Apex Hunters (#12)', monitoredCount: 3 })}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Pick your team (done)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Star your rivals (done)' })).toBeInTheDocument();
    expect(screen.getByText('Pinned: Apex Hunters (#12)')).toBeInTheDocument();
    expect(screen.getByText('3 teams starred')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Choose your track' })).toBeInTheDocument();
  });

  test('switches between the quick start and the tab reference', async () => {
    render(<HelpDrawer onClose={jest.fn()} initialView="quickstart" quickStart={quickStart()} />);
    const section = screen.getByRole('group', { name: 'Guide section' });
    expect(within(section).getByRole('button', { name: 'Quick start' })).toHaveAttribute('aria-pressed', 'true');

    await userEvent.click(within(section).getByRole('button', { name: 'Tabs & keys' }));
    expect(screen.getByRole('dialog', { name: 'Dashboard guide' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Fleet' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Keyboard' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Got it' })).not.toBeInTheDocument();

    await userEvent.click(within(section).getByRole('button', { name: 'Quick start' }));
    expect(screen.getByRole('heading', { name: 'Pick your team' })).toBeInTheDocument();
  });

  test('opens on the tab reference by default', () => {
    render(<HelpDrawer onClose={jest.fn()} quickStart={quickStart()} />);
    expect(screen.getByRole('dialog', { name: 'Dashboard guide' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Standings' })).toBeInTheDocument();
  });

  test('without setup state it is the tab reference only', () => {
    render(<HelpDrawer onClose={jest.fn()} initialView="quickstart" />);
    expect(screen.getByRole('dialog', { name: 'Dashboard guide' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Guide section' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Standings' })).toBeInTheDocument();
  });

  test('Escape closes it', async () => {
    const onClose = jest.fn();
    render(<HelpDrawer onClose={onClose} initialView="quickstart" quickStart={quickStart()} />);
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('“Take the tour” replays the feature tour, and is absent when there is none', async () => {
    const onStartTour = jest.fn();
    const { unmount } = render(
      <HelpDrawer onClose={jest.fn()} quickStart={quickStart()} onStartTour={onStartTour} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Take the tour' }));
    expect(onStartTour).toHaveBeenCalledTimes(1);
    unmount();

    render(<HelpDrawer onClose={jest.fn()} quickStart={quickStart()} />);
    expect(screen.queryByRole('button', { name: 'Take the tour' })).not.toBeInTheDocument();
  });
});
