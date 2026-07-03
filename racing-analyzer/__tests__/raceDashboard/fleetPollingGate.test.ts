/**
 * Fleet /fleet/state polling gate: hidden tabs never poll; users without a
 * fleet only poll while the Fleet tab is open; users with a fleet keep
 * background polling so pit alerts still fire.
 */

jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://api.test',
  WS_BASE_URL: 'ws://api.test',
  TURNSTILE_SITE_KEY: '',
  INVITE_REQUIRED: true,
}));

import { shouldPollFleet } from '@/app/components/RaceDashboard';

describe('shouldPollFleet', () => {
  test('hidden document never polls, regardless of tab or fleet', () => {
    expect(shouldPollFleet('hidden', 'fleet', 5)).toBe(false);
    expect(shouldPollFleet('hidden', 'standings', 5)).toBe(false);
    expect(shouldPollFleet('hidden', 'fleet', 0)).toBe(false);
  });

  test('no fleet configured: polls only while the Fleet tab is active', () => {
    expect(shouldPollFleet('visible', 'fleet', 0)).toBe(true);
    expect(shouldPollFleet('visible', 'standings', 0)).toBe(false);
    expect(shouldPollFleet('visible', 'chart', 0)).toBe(false);
  });

  test('fleet configured: polls in the background from any tab', () => {
    expect(shouldPollFleet('visible', 'standings', 3)).toBe(true);
    expect(shouldPollFleet('visible', 'fleet', 3)).toBe(true);
  });

  test('undefined visibility (SSR) falls through to the tab/fleet rule', () => {
    expect(shouldPollFleet(undefined, 'fleet', 0)).toBe(true);
    expect(shouldPollFleet(undefined, 'standings', 0)).toBe(false);
  });
});
