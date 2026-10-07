"""`GET /api/device/live`: one flat row, cheap when nothing changed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from .conftest import STANDINGS, TRACK_ID, bearer


LIVE = f'/api/device/live?track_id={TRACK_ID}&team=1%20-%20MY%20TEAM'


class TestLiveRow:
    def test_401_without_token(self, client, live_parser):
        r = client.get(LIVE)
        assert r.status_code == 401
        assert r.get_json() == {'error': 'invalid_token'}

    def test_row_shape_and_values(self, client, device_token, live_parser):
        r = client.get(LIVE, headers=bearer(device_token['token']))
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['track_id'] == TRACK_ID
        assert body['session_id'] == 17
        assert body['team'] == '1 - MY TEAM'
        assert body['matched_team'] == '1 - MY TEAM'
        assert body['kart'] == '12'
        assert body['position'] == 2
        assert body['gap_to_front'] == '1.245'
        assert body['gap_to_behind'] == '6.787'
        assert body['last_lap'] == '1:19.701'
        assert body['best_lap'] == '1:19.233'
        assert body['status'] == 'On Track'
        assert body['pit_stops'] == '2'
        assert body['updated_at'].endswith('Z')
        assert isinstance(body['seq'], int)
        # Flat: no nested containers anywhere, and small.
        assert all(not isinstance(v, (dict, list)) for v in body.values())
        assert len(r.data) < 400
        assert r.headers['ETag'] == f'"{body["seq"]}"'
        assert 'no-transform' in r.headers['Cache-Control']

    def test_leader_and_tail_edges(self, client, device_token, live_parser):
        h = bearer(device_token['token'])
        lead = client.get(f'/api/device/live?track_id={TRACK_ID}&team=1%20-%20LEADERS', headers=h).get_json()
        assert lead['position'] == 1 and lead['gap_to_front'] == '-' and lead['gap_to_behind'] == '1.245'
        tail = client.get(f'/api/device/live?track_id={TRACK_ID}&team=2%20-%20CHASERS', headers=h).get_json()
        assert tail['gap_to_behind'] == '-' and tail['status'] == 'Pit-in'

    def test_lapped_gap_keeps_feed_string(self, client, device_token, live_parser):
        live_parser.teams[2]['Gap'] = '1 Tour'
        h = bearer(device_token['token'])
        me = client.get(LIVE, headers=h).get_json()
        assert me['gap_to_behind'] == '1 Tour'
        tail = client.get(f'/api/device/live?track_id={TRACK_ID}&team=2%20-%20CHASERS', headers=h).get_json()
        assert tail['gap_to_front'] == '1 Tour'

    def test_matches_loosely_and_echoes_feed_name(self, client, device_token, live_parser):
        h = bearer(device_token['token'])
        for q in ('my%20team', 'MY%20TEAM', '12'):
            r = client.get(f'/api/device/live?track_id={TRACK_ID}&team={q}', headers=h)
            assert r.status_code == 200, q
            assert r.get_json()['matched_team'] == '1 - MY TEAM'

    def test_etag_roundtrip_304_empty_body(self, client, device_token, live_parser):
        h = bearer(device_token['token'])
        first = client.get(LIVE, headers=h)
        etag = first.headers['ETag']
        r = client.get(LIVE, headers={**h, 'If-None-Match': etag})
        assert r.status_code == 304
        assert r.data == b''
        assert r.headers['ETag'] == etag
        # Weak / unquoted forms are accepted too.
        r = client.get(LIVE, headers={**h, 'If-None-Match': 'W/' + etag})
        assert r.status_code == 304
        r = client.get(LIVE, headers={**h, 'If-None-Match': etag.strip('"')})
        assert r.status_code == 304

    def test_seq_moves_only_when_something_changes(self, client, device_token, live_parser, fleet_app):
        fleet_app._rate_limit_reset()
        h = bearer(device_token['token'])
        a = client.get(LIVE, headers=h).get_json()
        fleet_app._rate_limit_reset()
        b = client.get(LIVE, headers=h).get_json()
        assert a['seq'] == b['seq'] and a['updated_at'] == b['updated_at']
        live_parser.teams[1]['Last Lap'] = '1:19.650'
        fleet_app._rate_limit_reset()
        r = client.get(LIVE, headers={**h, 'If-None-Match': f'"{a["seq"]}"'})
        assert r.status_code == 200
        c = r.get_json()
        assert c['seq'] > a['seq'] and c['last_lap'] == '1:19.650'

    def test_404s_are_json_and_specific(self, client, device_token, live_parser, fleet_app):
        h = bearer(device_token['token'])
        r = client.get(f'/api/device/live?track_id=999&team=x', headers=h)
        assert r.status_code == 404 and r.get_json() == {'error': 'unknown_track'}
        fleet_app._rate_limit_reset()
        r = client.get(f'/api/device/live?track_id={TRACK_ID}&team=NOBODY', headers=h)
        assert r.status_code == 404 and r.get_json() == {'error': 'unknown_team'}
        live_parser.current_session_id = None
        fleet_app._rate_limit_reset()
        r = client.get(LIVE, headers=h)
        assert r.status_code == 404 and r.get_json() == {'error': 'no_live_session'}

    def test_400_on_missing_params(self, client, device_token, live_parser, fleet_app):
        h = bearer(device_token['token'])
        r = client.get(f'/api/device/live?track_id={TRACK_ID}', headers=h)
        assert r.status_code == 400 and r.get_json() == {'error': 'team_required'}
        fleet_app._rate_limit_reset()
        r = client.get('/api/device/live?track_id=abc&team=x', headers=h)
        assert r.status_code == 400 and r.get_json() == {'error': 'invalid_track_id'}

    def test_rate_limit_carries_retry_after(self, client, device_token, live_parser, fleet_app, monkeypatch):
        import race_app.blueprints.device_routes as dr
        monkeypatch.setattr(dr, '_rate_limit_hit', fleet_app._rate_limit_hit)
        h = bearer(device_token['token'])
        codes = [client.get(LIVE, headers=h).status_code for _ in range(4)]
        assert codes[:2] == [200, 200]
        assert 429 in codes
        r = client.get(LIVE, headers=h)
        assert r.status_code == 429
        assert r.get_json() == {'error': 'rate_limited'}
        assert r.headers['Retry-After'] == '2'

    def test_heavy_read_cap_does_not_apply(self, client, device_token, live_parser, fleet_app, monkeypatch):
        """The 120/h heavy-read cap guards history queries; a board polling
        every 2 s would exhaust it in four minutes. Device routes only use
        their own per-token throttle."""
        import race_app.blueprints.device_routes as dr
        monkeypatch.setattr(dr, '_rate_limit_hit', fleet_app._rate_limit_hit)
        h = bearer(device_token['token'])
        with patch.object(fleet_app, 'RATE_LIMITS', {**fleet_app.RATE_LIMITS, 'heavy_read_ip': (1, 3600)}):
            for _ in range(3):
                fleet_app._rate_limit_reset()
                assert client.get(LIVE, headers=h).status_code == 200

    def test_tracks_reports_live_flag(self, client, device_token, live_parser):
        r = client.get('/api/device/tracks', headers=bearer(device_token['token']))
        assert r.get_json() == [{'id': TRACK_ID, 'name': 'Test Track', 'active': True}]


class TestAgreesWithSocketIO:
    def test_same_gaps_as_team_specific_update(self, fleet_app):
        """Both transports read `compute_team_gaps`; check the Socket.IO
        emitter really produces the row the device sees."""
        from multi_track_manager import TrackSpecificParser
        from race_app.device_hub import hub

        parser = TrackSpecificParser.__new__(TrackSpecificParser)
        parser.socketio = MagicMock()
        parser.track_id = TRACK_ID
        parser.logger = MagicMock()
        df = pd.DataFrame(STANDINGS)
        with patch('multi_track_manager._room_occupied', return_value=True):
            parser.emit_team_specific_updates(df, 17, '2026-09-18T14:03:21')
        emitted = {call.kwargs['room']: call.args[1] for call in parser.socketio.emit.call_args_list}
        sock = emitted[f'team_track_{TRACK_ID}_1 - MY TEAM']

        row = hub.build_row(1, TRACK_ID, 17, STANDINGS, '1 - MY TEAM')
        assert row['position'] == int(sock['Position'])
        assert row['gap_to_front'] == sock['gap_to_front']
        assert row['gap_to_behind'] == sock['gap_to_behind']
        assert row['last_lap'] == sock['Last Lap']
        assert row['best_lap'] == sock['Best Lap']
        assert row['status'] == sock['Status']
        assert row['pit_stops'] == sock['Pit Stops']
