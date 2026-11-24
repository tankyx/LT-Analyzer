/** What the quick start needs to know about the dashboard to show progress. */
export interface QuickStartState {
  /** Name of the track on screen; empty while the track list loads. */
  trackName: string;
  /** True once the live field is listed, so a team can actually be picked. */
  hasField: boolean;
  /** "Apex Hunters (#12)", or '' when no team is pinned. */
  myTeamLabel: string;
  monitoredCount: number;
}

export type QuickStartStepId = 'track' | 'team' | 'rivals' | 'pit';

export interface QuickStartStep {
  id: QuickStartStepId;
  title: string;
  body: string;
  /** Where the user stands on this step, when there is something to say. */
  status?: string;
  /** True only for steps the dashboard can see are complete. */
  done: boolean;
}

/** The four setup steps, in the order a new user should take them. */
export function buildQuickStartSteps(state: QuickStartState): QuickStartStep[] {
  const { trackName, hasField, myTeamLabel, monitoredCount } = state;
  const teamPinned = myTeamLabel !== '';

  return [
    {
      id: 'track',
      title: 'Choose your track',
      body: 'Tap the track name in the top bar. Tracks with a session running are listed first, under Live now.',
      status: trackName ? `Showing ${trackName}` : undefined,
      done: false,
    },
    {
      id: 'team',
      title: 'Pick your team',
      body: 'Use “Choose your team” at the top of the page. It pins your position, lap times and the gaps to the karts ahead and behind.',
      status: teamPinned
        ? `Pinned: ${myTeamLabel}`
        : hasField
          ? undefined
          : 'The team list appears when a session is live on this track.',
      done: teamPinned,
    },
    {
      id: 'rivals',
      title: 'Star your rivals',
      body: 'Tap the star on a team’s row in Standings. Starred teams show in Monitored and on the Delta chart, with gaps measured from your team.',
      status: monitoredCount > 0 ? `${monitoredCount} ${monitoredCount === 1 ? 'team' : 'teams'} starred` : undefined,
      done: monitoredCount > 0,
    },
    {
      id: 'pit',
      title: 'Set the pit rules',
      body: 'After starring a rival, open Monitored and enter the required pit stops and the pit stop time. Adjusted gaps then count the stops each team still has to make.',
      done: false,
    },
  ];
}
