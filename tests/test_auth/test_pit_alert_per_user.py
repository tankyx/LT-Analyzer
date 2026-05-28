"""Per-user routing for the pit_alert Socket.IO event.

The pit-alert endpoint used to fan out to every Socket.IO client in
`team_track_{id}_{name}` — so a rival team's Android device that happened
to be monitoring the same team buzzed too. We changed it to emit to
`user_{id}` of the triggering user, identified via the Flask session
cookie when the client connects.

These tests patch socketio.emit so we can assert the emit ROOM rather
than spin up a real Socket.IO server in-process (heavy + flaky).
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

from .conftest import login_as, csrf_token


def _seed_track(auth_app, name='Test Track', track_id=999):
    """Add a track so /api/trigger-pit-alert's track_id check passes."""
    with sqlite3.connect('tracks.db') as c:
        c.execute(
            "INSERT OR IGNORE INTO tracks (id, track_name, timing_url, websocket_url, provider) "
            "VALUES (?, ?, ?, ?, 'apex')",
            (track_id, name, 'http://t/', 'wss://t/'),
        )
        c.commit()


class TestPitAlertPerUser:
    def test_alert_emits_to_triggering_user_room_not_team_room(
        self, auth_app, client, authenticated_user
    ):
        _seed_track(auth_app)
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        token = csrf_token(client)

        with patch.object(auth_app.socketio, 'emit') as mock_emit:
            r = client.post(
                '/api/trigger-pit-alert',
                json={'track_id': 999, 'team_name': 'BIBAN',
                      'alert_message': 'PIT NOW'},
                headers={'X-CSRF-Token': token},
            )
        assert r.status_code == 200
        rooms = [call.kwargs.get('room') or (call.args[2] if len(call.args) > 2 else None)
                 for call in mock_emit.call_args_list]
        # The pit_alert (phone-bound) must land on the user's personal room,
        # NOT the team room (which would broadcast to rivals).
        user_room = f"user_{authenticated_user['id']}"
        assert user_room in rooms, f"pit_alert never emitted to {user_room}; rooms={rooms}"
        assert f'team_track_999_BIBAN' not in rooms, (
            'pit_alert should NOT fan out to team_track_* rooms anymore '
            '(that was the bug we fixed)'
        )

    def test_pit_alert_broadcast_still_fires_on_track_room(
        self, auth_app, client, authenticated_user
    ):
        # The web dashboard's banner alert uses pit_alert_broadcast on the
        # track room — that should still happen so other web operators can
        # see "BIBAN was sent a pit alert" in their standings view.
        _seed_track(auth_app)
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        token = csrf_token(client)

        events = []
        def capture(event, payload, **kw):
            events.append((event, kw.get('room')))

        with patch.object(auth_app.socketio, 'emit', side_effect=capture):
            client.post(
                '/api/trigger-pit-alert',
                json={'track_id': 999, 'team_name': 'BIBAN',
                      'alert_message': 'PIT NOW'},
                headers={'X-CSRF-Token': token},
            )
        assert ('pit_alert_broadcast', 'track_999') in events

    def test_alert_payload_carries_triggering_user_id(
        self, auth_app, client, authenticated_user
    ):
        _seed_track(auth_app)
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        token = csrf_token(client)

        captured = {}
        def capture(event, payload, **kw):
            if event == 'pit_alert':
                captured['payload'] = payload

        with patch.object(auth_app.socketio, 'emit', side_effect=capture):
            client.post(
                '/api/trigger-pit-alert',
                json={'track_id': 999, 'team_name': 'BIBAN'},
                headers={'X-CSRF-Token': token},
            )
        assert captured['payload']['triggered_by_user_id'] == authenticated_user['id']
        assert captured['payload']['team_name'] == 'BIBAN'

    def test_anonymous_caller_rejected(self, auth_app, client):
        _seed_track(auth_app)
        # No login — login_required must reject before we even reach the
        # per-user routing.
        r = client.post(
            '/api/trigger-pit-alert',
            json={'track_id': 999, 'team_name': 'BIBAN'},
        )
        assert r.status_code in (401, 403)
