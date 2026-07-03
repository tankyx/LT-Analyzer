"""Socket.IO hardening: login-required connect, input validation, room caps.

Uses flask-socketio's test client bound to the real Flask test client so the
session cookie set by /api/auth/login is visible on the socket handshake.
"""

import pytest

from tests.test_auth.conftest import login_as


pytestmark = pytest.mark.integration


def _socket_client(auth_app, flask_client):
    return auth_app.socketio.test_client(auth_app.app, flask_test_client=flask_client)


def _room_sids(auth_app, room):
    rooms = auth_app.socketio.server.manager.rooms.get('/', {})
    return set(rooms.get(room, {}))


@pytest.fixture
def test_track(auth_app):
    """Ensure a known track exists in tracks.db; return its id."""
    existing = auth_app.track_db.get_all_tracks()
    for t in existing:
        if t['track_name'] == 'Socket Test Track':
            return t['id']
    result = auth_app.track_db.add_track(
        track_name='Socket Test Track',
        timing_url='https://www.apex-timing.com/live-timing/test/',
        websocket_url='wss://www.apex-timing.com:8000/',
    )
    return result['id']


class TestConnectAuth:
    def test_anonymous_connect_rejected(self, auth_app, client):
        sock = _socket_client(auth_app, client)
        assert not sock.is_connected()

    def test_authenticated_connect_accepted(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        assert sock.is_connected()
        events = {e['name'] for e in sock.get_received()}
        assert 'session_identified' in events
        sock.disconnect()


class TestJoinTrackValidation:
    def test_join_track_rejects_non_integer(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.get_received()
        sock.emit('join_track', {'track_id': '../../etc/passwd'})
        events = {e['name'] for e in sock.get_received()}
        assert 'track_joined' not in events
        assert not _room_sids(auth_app, 'track_../../etc/passwd')
        sock.disconnect()

    def test_join_track_rejects_unknown_track(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.get_received()
        sock.emit('join_track', {'track_id': 999999})
        events = {e['name'] for e in sock.get_received()}
        assert 'track_joined' not in events
        sock.disconnect()

    def test_join_track_accepts_known_track(self, auth_app, client, authenticated_user, test_track):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.get_received()
        sock.emit('join_track', {'track_id': test_track})
        events = {e['name'] for e in sock.get_received()}
        assert 'track_joined' in events
        sock.disconnect()


class TestJoinTeamRoomValidation:
    def test_rejects_overlong_team_name(self, auth_app, client, authenticated_user, test_track):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.get_received()
        sock.emit('join_team_room', {'track_id': test_track, 'team_name': 'x' * 65})
        received = sock.get_received()
        errors = [e for e in received if e['name'] == 'team_room_error']
        assert errors, f'expected team_room_error, got {[e["name"] for e in received]}'
        sock.disconnect()

    def test_rejects_unprintable_team_name(self, auth_app, client, authenticated_user, test_track):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.get_received()
        sock.emit('join_team_room', {'track_id': test_track, 'team_name': 'bad\nname'})
        received = sock.get_received()
        assert any(e['name'] == 'team_room_error' for e in received)
        sock.disconnect()

    def test_accepts_valid_team_name(self, auth_app, client, authenticated_user, test_track):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.get_received()
        sock.emit('join_team_room', {'track_id': test_track, 'team_name': 'Team Alpha'})
        received = sock.get_received()
        joined = [e for e in received if e['name'] == 'team_room_joined']
        assert joined
        assert joined[0]['args'][0]['team_name'] == 'Team Alpha'
        sock.disconnect()


class TestSubscribeUserPrefs:
    def test_other_users_prefs_room_denied(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        other_id = authenticated_user['id'] + 1000
        sock.emit('subscribe_user_prefs', {'user_id': other_id})
        assert not _room_sids(auth_app, f'user_prefs_{other_id}')
        sock.disconnect()

    def test_own_prefs_room_allowed(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.emit('subscribe_user_prefs', {'user_id': authenticated_user['id']})
        assert _room_sids(auth_app, f'user_prefs_{authenticated_user["id"]}')
        sock.disconnect()


class TestRoomJoinCap:
    def test_room_join_cap_enforced(self, auth_app, client, authenticated_user, test_track, monkeypatch):
        monkeypatch.setattr(auth_app, 'SOCKET_MAX_ROOM_JOINS', 3)
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.get_received()
        for i in range(3):
            sock.emit('join_team_room', {'track_id': test_track, 'team_name': f'Team {i}'})
        received = sock.get_received()
        assert sum(1 for e in received if e['name'] == 'team_room_joined') == 3
        # Fourth distinct room is refused...
        sock.emit('join_team_room', {'track_id': test_track, 'team_name': 'Team overflow'})
        received = sock.get_received()
        assert any(e['name'] == 'team_room_error' for e in received)
        # ...but re-joining an already-held room stays allowed.
        sock.emit('join_team_room', {'track_id': test_track, 'team_name': 'Team 0'})
        received = sock.get_received()
        assert any(e['name'] == 'team_room_joined' for e in received)
        sock.disconnect()

    def test_leaving_frees_cap_slot(self, auth_app, client, authenticated_user, test_track, monkeypatch):
        monkeypatch.setattr(auth_app, 'SOCKET_MAX_ROOM_JOINS', 2)
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        sock.get_received()
        sock.emit('join_team_room', {'track_id': test_track, 'team_name': 'Team A'})
        sock.emit('join_team_room', {'track_id': test_track, 'team_name': 'Team B'})
        sock.emit('leave_team_room', {'track_id': test_track, 'team_name': 'Team A'})
        sock.get_received()
        sock.emit('join_team_room', {'track_id': test_track, 'team_name': 'Team C'})
        received = sock.get_received()
        assert any(e['name'] == 'team_room_joined' for e in received)
        sock.disconnect()


class TestDisconnectCleanup:
    def test_disconnect_clears_sid_state(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        sock = _socket_client(auth_app, client)
        assert sock.is_connected()
        with auth_app._socket_state_lock:
            assert len(auth_app._socket_users) >= 1
        sock.disconnect()
        with auth_app._socket_state_lock:
            assert len(auth_app._socket_users) == 0
            assert len(auth_app._socket_room_joins) == 0
