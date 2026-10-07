import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import PitAlertTarget, {
  DeviceToken,
  PIT_ALERT_TARGET_KEY,
  describeDelivery,
  loadPitAlertTarget,
  savePitAlertTarget,
  targetIdsFor,
} from '@/app/components/RaceDashboard/PitAlertTarget';

const boards: DeviceToken[] = [
  { id: 7, label: 'datalogger-p4', created_at: '', expires_at: '', last_seen_at: null, revoked: false, online: true },
  { id: 9, label: 'pit-wall', created_at: '', expires_at: '', last_seen_at: null, revoked: false, online: false },
  { id: 3, label: 'old-board', created_at: '', expires_at: '', last_seen_at: null, revoked: true, online: false },
];

describe('describeDelivery', () => {
  test('no boards registered: phones only, success', () => {
    expect(describeDelivery({ delivered_to: 0, devices_online: 0 }, 0)).toEqual({
      text: 'sent to your phones',
      tone: 'success',
    });
  });
  test('boards registered but none connected is a warning', () => {
    expect(describeDelivery({ delivered_to: 0, devices_online: 0 }, 2)).toEqual({
      text: 'no board listening',
      tone: 'warning',
    });
  });
  test('a board is online but out of scope is a warning', () => {
    expect(describeDelivery({ delivered_to: 0, devices_online: 1 }, 2).tone).toBe('warning');
    expect(describeDelivery({ delivered_to: 0, devices_online: 1 }, 2).text).toMatch(/this track or team/);
  });
  test('counts boards buzzed', () => {
    expect(describeDelivery({ delivered_to: 1, devices_online: 2 }, 2)).toEqual({
      text: '1 board buzzed (2 online)',
      tone: 'success',
    });
    expect(describeDelivery({ delivered_to: 2, devices_online: 2 }, 2).text).toBe('2 boards buzzed (2 online)');
  });
  test('tolerates a response without counts', () => {
    expect(describeDelivery({}, 1).tone).toBe('warning');
  });
});

describe('target persistence', () => {
  beforeEach(() => localStorage.clear());
  test('defaults to all and round-trips a device id', () => {
    expect(loadPitAlertTarget()).toBe('all');
    savePitAlertTarget(7);
    expect(localStorage.getItem(PIT_ALERT_TARGET_KEY)).toBe('7');
    expect(loadPitAlertTarget()).toBe(7);
    savePitAlertTarget('all');
    expect(loadPitAlertTarget()).toBe('all');
  });
  test('ignores garbage', () => {
    localStorage.setItem(PIT_ALERT_TARGET_KEY, 'nope');
    expect(loadPitAlertTarget()).toBe('all');
  });
  test('targetIdsFor maps to the request field', () => {
    expect(targetIdsFor('all')).toBeUndefined();
    expect(targetIdsFor(9)).toEqual([9]);
  });
});

describe('PitAlertTarget', () => {
  test('renders nothing without active boards', () => {
    const { container } = render(<PitAlertTarget devices={[boards[2]]} value="all" onChange={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
  test('lists active boards with an online marker and reports changes', () => {
    const onChange = jest.fn();
    render(<PitAlertTarget devices={boards} value="all" onChange={onChange} />);
    const select = screen.getByLabelText('Pit alert target') as HTMLSelectElement;
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels).toEqual(['All boards', '● datalogger-p4', '○ pit-wall']);
    fireEvent.change(select, { target: { value: '9' } });
    expect(onChange).toHaveBeenCalledWith(9);
    fireEvent.change(select, { target: { value: 'all' } });
    expect(onChange).toHaveBeenCalledWith('all');
  });
  test('falls back to all when the chosen board was revoked', () => {
    render(<PitAlertTarget devices={boards} value={3} onChange={() => {}} />);
    expect((screen.getByLabelText('Pit alert target') as HTMLSelectElement).value).toBe('all');
  });
});
