import { useCallback, useEffect, useRef, useState } from 'react';
import { hasSeenOnboarding, markOnboardingSeen } from '../../../utils/persistence';

/** The part of the per-track preferences that shows whether an account is set up. */
export interface OnboardingPrefs {
  my_team?: string | null;
  monitored_teams?: string[] | null;
}

/** No team pinned and nobody starred: the account has not been set up on this track. */
export function isUnconfigured(prefs: OnboardingPrefs): boolean {
  return !prefs.my_team && !(prefs.monitored_teams && prefs.monitored_teams.length > 0);
}

/**
 * Decides, once per login, whether to start the first-launch onboarding (the
 * feature tour, which ends on the quick start) unprompted.
 *
 * It is offered only to an account that has not closed it in this browser and
 * has nothing set up on the track it lands on. An account that already has a
 * team pinned is mid-event: it is marked as seen and never interrupted.
 *
 * `settledTrackId` is the track the dashboard resolved at startup (null until
 * then) and `loaded` the latest preferences that came back from the server.
 * Waiting for the two to agree keeps the placeholder track the dashboard
 * starts on from being mistaken for an empty account. If the preferences
 * never load, nothing is offered and the question is asked again next visit.
 */
export function useOnboardingOffer(
  username: string | undefined,
  settledTrackId: number | null,
  loaded: { trackId: number; prefs: OnboardingPrefs } | null,
): { offered: boolean; dismiss: () => void } {
  const [offered, setOffered] = useState(false);
  const decidedFor = useRef<string | null>(null);

  useEffect(() => {
    if (!username || settledTrackId === null || !loaded) return;
    if (loaded.trackId !== settledTrackId) return;
    if (decidedFor.current === username) return;
    decidedFor.current = username;
    if (hasSeenOnboarding(username)) return;
    if (isUnconfigured(loaded.prefs)) {
      setOffered(true);
    } else {
      markOnboardingSeen(username);
    }
  }, [username, settledTrackId, loaded]);

  const dismiss = useCallback(() => {
    if (username) markOnboardingSeen(username);
    setOffered(false);
  }, [username]);

  return { offered, dismiss };
}
