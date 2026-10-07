"""`GET /api/device/stream` (SSE) and pit alerts in both directions."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest


from .conftest import TRACK_ID, bearer, login, read_frames


STREAM = f'/api/device/stream?track_id={TRACK_ID}&team=1%20-%20MY%20TEAM'


def parse_frame(frame: str) -> dict:
    out = {}
    for line in frame.strip().split('\n'):
        k, _, v = line.partition(':')
        out[k.strip()] = v.strip()
    if 'data' in out:
        out['json'] = json.loads(out['data'])
    return out


@pytest.fixture(autouse=True)
def fast_heartbeat(monkeypatch):
    import race_app.blueprints.device_routes as dr
    monkeypatch.setattr(dr, 'HEARTBEAT_SECONDS', 0.2)


def open_stream(client, token, path=STREAM):
    resp = client.get(path, headers={**bearer(token), 'Accept': 'text/event-stream'}, buffered=False)
    assert resp.status_code == 200, resp.data
    assert resp.headers['Content-Type'].startswith('text/event-stream')
    return resp


def second_token(client, user, label='board-2'):
    csrf = client.get('/api/auth/csrf').get_json()['csrfToken']
    r = client.post('/api/device/tokens', json={'label': label}, headers={'X-CSRF-Token': csrf})
    assert r.status_code == 201
    return r.get_json()


class TestStream:
    def test_snapshot_then_changes_then_heartbeat(self, client, device_token, live_parser, hub):
        resp = open_stream(client, device_token['token'])
        try:
            retry, first = read_frames(resp, 2)
            assert retry == 'retry: 5000\n\n'
            f = parse_frame(first)
            assert f['event'] == 'team'
            assert f['id'] == str(f['json']['seq'])
            assert f['json']['position'] == 2 and f['json']['gap_to_front'] == '1.245'
            assert 'Cache-Control' in resp.headers and 'no-transform' in resp.headers['Cache-Control']

            # Nothing changed -> heartbeat, no data frame.
            (hb,) = read_frames(resp, 1)
            assert hb == ': heartbeat\n\n'

            # A parser commit with a real change -> a new team frame.
            live_parser.teams[1]['Last Lap'] = '1:19.500'
            hub.notify_track(TRACK_ID, 17, 'ts')
            (nxt,) = read_frames(resp, 1)
            n = parse_frame(nxt)
            assert n['event'] == 'team' and n['json']['last_lap'] == '1:19.500'
            assert int(n['id']) > int(f['id'])

            # A commit with no visible change -> nothing but a heartbeat.
            hub.notify_track(TRACK_ID, 17, 'ts')
            (again,) = read_frames(resp, 1)
            assert again == ': heartbeat\n\n'
        finally:
            resp.close()

    def test_stream_stays_open_without_live_session(self, client, device_token, live_parser, hub):
        live_parser.current_session_id = None
        resp = open_stream(client, device_token['token'])
        try:
            _, first = read_frames(resp, 2)
            f = parse_frame(first)
            assert f['event'] == 'status' and f['json']['error'] == 'no_live_session'
            # Session starts -> team frame arrives on the same connection.
            live_parser.current_session_id = 18
            hub.notify_track(TRACK_ID, 18, 'ts')
            (nxt,) = read_frames(resp, 1)
            assert parse_frame(nxt)['event'] == 'team'
        finally:
            resp.close()

    def test_unsubscribes_on_close(self, client, device_token, live_parser, hub):
        resp = open_stream(client, device_token['token'])
        read_frames(resp, 2)
        assert hub.online_devices(device_token['user']['id']) == {device_token['id']}
        resp.close()
        assert hub.online_devices(device_token['user']['id']) == set()

    def test_stream_rejects_bad_params_as_json(self, client, device_token, live_parser):
        h = bearer(device_token['token'])
        r = client.get(f'/api/device/stream?track_id=999&team=x', headers=h)
        assert r.status_code == 404 and r.get_json() == {'error': 'unknown_track'}
        r = client.get(f'/api/device/stream?track_id={TRACK_ID}', headers=h)
        assert r.status_code == 400
        r = client.get(STREAM)
        assert r.status_code == 401


class TestWebToDevice:
    def trigger(self, client, csrf, **overrides):
        body = {'track_id': TRACK_ID, 'team_name': '1 - MY TEAM', 'alert_message': 'PIT NOW'}
        body.update(overrides)
        return client.post('/api/trigger-pit-alert', json=body, headers={'X-CSRF-Token': csrf})

    def test_alert_reaches_streaming_board(self, client, device_token, live_parser, fleet_app):
        resp = open_stream(client, device_token['token'])
        try:
            read_frames(resp, 2)
            with patch.object(fleet_app.socketio, 'emit'):
                r = self.trigger(client, device_token['csrf'])
            assert r.status_code == 200
            body = r.get_json()
            assert body['ok'] is True and body['delivered_to'] == 1 and body['devices_online'] == 1
            (frame,) = read_frames(resp, 1)
            a = parse_frame(frame)
            assert a['event'] == 'alert'
            j = a['json']
            assert j['alert_type'] == 'pit_required'
            assert j['alert_message'] == 'PIT NOW'
            assert j['track_id'] == TRACK_ID and j['team_name'] == '1 - MY TEAM'
            assert j['flash_color'] == '#FF0000' and j['duration_ms'] == 80000 and j['priority'] == 'high'
            assert j['triggered_by_user_id'] == device_token['user']['id']
            assert j['target_device_ids'] is None
            assert j['timestamp'].endswith('Z')
            assert a['id'] and a['id'] != str(j.get('seq'))
        finally:
            resp.close()

    def test_no_board_listening_is_reported(self, client, device_token, live_parser, fleet_app):
        with patch.object(fleet_app.socketio, 'emit'):
            r = self.trigger(client, device_token['csrf'])
        assert r.status_code == 200
        assert r.get_json()['delivered_to'] == 0 and r.get_json()['devices_online'] == 0

    def test_board_on_other_track_or_team_is_silent(self, client, device_token, live_parser, fleet_app):
        import sqlite3
        with sqlite3.connect('tracks.db') as c:
            c.execute("INSERT OR IGNORE INTO tracks (id, track_name, timing_url, websocket_url, is_active) "
                      "VALUES (55, 'Other', 'http://o/', 'ws://o/', 1)")
        other = open_stream(client, device_token['token'],
                            path='/api/device/stream?track_id=55&team=1%20-%20MY%20TEAM')
        try:
            read_frames(other, 2)
            with patch.object(fleet_app.socketio, 'emit'):
                r = self.trigger(client, device_token['csrf'])
            assert r.get_json()['delivered_to'] == 0
            assert r.get_json()['devices_online'] == 1
            (frame,) = read_frames(other, 1)
            assert frame == ': heartbeat\n\n'
        finally:
            other.close()

        mine = open_stream(client, device_token['token'])
        try:
            # The first alert was fresh and aimed at track 1: now that this
            # board follows track 1 it is replayed once, right after the snapshot.
            _, _, replay = read_frames(mine, 3)
            assert parse_frame(replay)['event'] == 'alert'
            with patch.object(fleet_app.socketio, 'emit'):
                r = self.trigger(client, device_token['csrf'], team_name='2 - CHASERS')
            assert r.get_json()['delivered_to'] == 0
            (frame,) = read_frames(mine, 1)
            assert frame == ': heartbeat\n\n'
        finally:
            mine.close()

    def test_explicit_target_buzzes_one_board_only(self, client, device_token, live_parser, fleet_app):
        tok2 = second_token(client, device_token['user'])
        s1 = open_stream(client, device_token['token'])
        s2 = open_stream(client, tok2['token'])
        try:
            read_frames(s1, 2)
            read_frames(s2, 2)
            with patch.object(fleet_app.socketio, 'emit'):
                r = self.trigger(client, device_token['csrf'], target_device_ids=[tok2['id']])
            body = r.get_json()
            assert body['delivered_to'] == 1 and body['devices_online'] == 2
            (f2,) = read_frames(s2, 1)
            assert parse_frame(f2)['event'] == 'alert'
            assert parse_frame(f2)['json']['target_device_ids'] == [tok2['id']]
            (f1,) = read_frames(s1, 1)
            assert f1 == ': heartbeat\n\n'
        finally:
            s1.close()
            s2.close()

    def test_untargeted_alert_buzzes_every_candidate(self, client, device_token, live_parser, fleet_app):
        tok2 = second_token(client, device_token['user'])
        s1 = open_stream(client, device_token['token'])
        s2 = open_stream(client, tok2['token'])
        try:
            read_frames(s1, 2)
            read_frames(s2, 2)
            with patch.object(fleet_app.socketio, 'emit'):
                r = self.trigger(client, device_token['csrf'])
            assert r.get_json()['delivered_to'] == 2
            assert parse_frame(read_frames(s1, 1)[0])['event'] == 'alert'
            assert parse_frame(read_frames(s2, 1)[0])['event'] == 'alert'
        finally:
            s1.close()
            s2.close()

    def test_target_must_be_own_device(self, client, device_token, live_parser, fleet_app):
        with patch.object(fleet_app.socketio, 'emit'):
            r = self.trigger(client, device_token['csrf'], target_device_ids=[99999])
        assert r.status_code == 400 and r.get_json()['message'] == 'unknown_device'
        with patch.object(fleet_app.socketio, 'emit'):
            r = self.trigger(client, device_token['csrf'], target_device_ids='7')
        assert r.status_code == 400

    def test_phones_still_get_socketio_alert(self, client, device_token, live_parser, fleet_app):
        with patch.object(fleet_app.socketio, 'emit') as emit:
            self.trigger(client, device_token['csrf'])
        rooms = {c.kwargs.get('room'): c.args for c in emit.call_args_list}
        assert f"user_{device_token['user']['id']}" in rooms
        assert f'track_{TRACK_ID}' in rooms
        assert rooms[f"user_{device_token['user']['id']}"][1]['origin'] == 'web'

    def test_fresh_alert_replays_on_reconnect_stale_does_not(self, client, device_token, live_parser, fleet_app):
        # Board is offline when the operator presses PIT NOW.
        with patch.object(fleet_app.socketio, 'emit'):
            r = self.trigger(client, device_token['csrf'])
        assert r.get_json()['delivered_to'] == 0
        resp = open_stream(client, device_token['token'])
        try:
            _, snap, alert = read_frames(resp, 3)
            assert parse_frame(snap)['event'] == 'team'
            assert parse_frame(alert)['event'] == 'alert'
        finally:
            resp.close()
        # Delivered once: a second reconnect does not replay it.
        resp = open_stream(client, device_token['token'])
        try:
            _, _, third = read_frames(resp, 3)
            assert third == ': heartbeat\n\n'
        finally:
            resp.close()
        # An alert past its window is dropped, never replayed late.
        with patch.object(fleet_app.socketio, 'emit'):
            self.trigger(client, device_token['csrf'])
        with patch('race_app.device_hub.time.monotonic', return_value=time.monotonic() + 200):
            resp = open_stream(client, device_token['token'])
            try:
                _, _, third = read_frames(resp, 3)
                assert third == ': heartbeat\n\n'
            finally:
                resp.close()


class TestDeviceToWeb:
    def test_device_alert_broadcasts_with_origin_and_no_csrf(self, client, device_token, live_parser, fleet_app):
        client.post('/api/auth/logout', headers={'X-CSRF-Token': device_token['csrf']})
        with patch.object(fleet_app.socketio, 'emit') as emit:
            r = client.post('/api/device/pit-alert',
                            json={'track_id': TRACK_ID, 'team_name': '1 - MY TEAM', 'alert_message': 'PIT NOW'},
                            headers=bearer(device_token['token']))
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['ok'] is True and body['delivered_to'] == 0 and body['timestamp'].endswith('Z')
        by_event = {c.args[0]: (c.args[1], c.kwargs.get('room')) for c in emit.call_args_list}
        bc, room = by_event['pit_alert_broadcast']
        assert room == f'track_{TRACK_ID}'
        assert bc['origin'] == 'device' and bc['origin_label'] == 'datalogger-p4'
        pa, room = by_event['pit_alert']
        assert room == f"user_{device_token['user']['id']}"
        assert pa['origin'] == 'device' and pa['origin_label'] == 'datalogger-p4'

    def test_device_alert_reaches_other_boards_not_itself(self, client, device_token, live_parser, fleet_app):
        tok2 = second_token(client, device_token['user'])
        s1 = open_stream(client, device_token['token'])
        s2 = open_stream(client, tok2['token'])
        try:
            read_frames(s1, 2)
            read_frames(s2, 2)
            with patch.object(fleet_app.socketio, 'emit'):
                r = client.post('/api/device/pit-alert',
                                json={'track_id': TRACK_ID, 'team_name': '1 - MY TEAM'},
                                headers=bearer(device_token['token']))
            assert r.get_json()['delivered_to'] == 1 and r.get_json()['devices_online'] == 2
            assert parse_frame(read_frames(s2, 1)[0])['event'] == 'alert'
            assert read_frames(s1, 1)[0] == ': heartbeat\n\n'
        finally:
            s1.close()
            s2.close()

    def test_device_alert_validation(self, client, device_token, live_parser):
        h = bearer(device_token['token'])
        r = client.post('/api/device/pit-alert', json={'track_id': 'x', 'team_name': 'a'}, headers=h)
        assert r.status_code == 400 and r.get_json() == {'error': 'invalid_track_id'}
        r = client.post('/api/device/pit-alert', json={'track_id': TRACK_ID}, headers=h)
        assert r.status_code == 400 and r.get_json() == {'error': 'team_required'}
        r = client.post('/api/device/pit-alert', json={'track_id': 999, 'team_name': 'a'}, headers=h)
        assert r.status_code == 404 and r.get_json() == {'error': 'unknown_track'}
