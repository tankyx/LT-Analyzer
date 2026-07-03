"""Phase 4: login-throttle rework, session GC/cap, hashed session tokens."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from tests.test_auth.conftest import login_as


pytestmark = pytest.mark.integration


def _insert_failures(n, username, ip):
    with sqlite3.connect('auth.db') as conn:
        conn.executemany(
            'INSERT INTO login_attempts (username, ip_address, success) VALUES (?, ?, 0)',
            [(username, ip)] * n,
        )


class TestLoginThrottle:
    def test_joint_key_still_limits(self, auth_app, reset_db):
        _insert_failures(5, 'bob', '1.1.1.1')
        assert auth_app._is_rate_limited('bob', '1.1.1.1') is True
        assert auth_app._is_rate_limited('bob', '2.2.2.2') is False

    def test_username_locked_across_rotating_ips(self, auth_app, reset_db):
        # 10 failures on one account from 10 different IPs: the joint key
        # never trips, the per-username cap does.
        for i in range(10):
            _insert_failures(1, 'victim', f'10.0.0.{i}')
        assert auth_app._is_rate_limited('victim', '99.99.99.99') is True
        assert auth_app._is_rate_limited('someone-else', '99.99.99.99') is False

    def test_ip_locked_across_usernames(self, auth_app, reset_db):
        # Password spraying: 30 failures from one IP over 30 accounts.
        for i in range(30):
            _insert_failures(1, f'user{i}', '6.6.6.6')
        assert auth_app._is_rate_limited('fresh-user', '6.6.6.6') is True
        assert auth_app._is_rate_limited('fresh-user', '7.7.7.7') is False


class TestSessionGcAndCap:
    def test_expired_sessions_deleted_on_login(self, auth_app, client, authenticated_user):
        stale = (datetime.now() - timedelta(hours=1)).isoformat()
        with sqlite3.connect('auth.db') as conn:
            conn.execute(
                'INSERT INTO sessions (session_token, user_id, expires_at) VALUES (?, ?, ?)',
                ('deadbeef' * 8, authenticated_user['id'], stale),
            )
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        with sqlite3.connect('auth.db') as conn:
            count = conn.execute(
                'SELECT COUNT(*) FROM sessions WHERE expires_at <= ?',
                (datetime.now().isoformat(),),
            ).fetchone()[0]
        assert count == 0

    def test_per_user_session_cap(self, auth_app, client, authenticated_user, monkeypatch):
        monkeypatch.setattr(auth_app, 'MAX_SESSIONS_PER_USER', 3)
        for _ in range(6):
            auth_app.create_session(authenticated_user['id'])
        with sqlite3.connect('auth.db') as conn:
            count = conn.execute(
                'SELECT COUNT(*) FROM sessions WHERE user_id = ?',
                (authenticated_user['id'],),
            ).fetchone()[0]
        assert count == 3

    def test_newest_sessions_survive_the_cap(self, auth_app, authenticated_user, monkeypatch):
        monkeypatch.setattr(auth_app, 'MAX_SESSIONS_PER_USER', 2)
        tokens = [auth_app.create_session(authenticated_user['id']) for _ in range(4)]
        assert auth_app.verify_session(tokens[-1]) is not None
        assert auth_app.verify_session(tokens[-2]) is not None
        auth_app._session_cache_invalidate()
        assert auth_app.verify_session(tokens[0]) is None


class TestHashedSessionTokens:
    def test_tokens_stored_hashed(self, auth_app, authenticated_user):
        raw = auth_app.create_session(authenticated_user['id'])
        with sqlite3.connect('auth.db') as conn:
            rows = [r[0] for r in conn.execute('SELECT session_token FROM sessions').fetchall()]
        assert raw not in rows
        assert auth_app._hash_session_token(raw) in rows
        assert auth_app.verify_session(raw)['id'] == authenticated_user['id']

    def test_logout_deletes_hashed_row(self, auth_app, client, authenticated_user):
        from tests.test_auth.conftest import csrf_token
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        token = csrf_token(client)
        client.post('/api/auth/logout', headers={'X-CSRF-Token': token})
        with sqlite3.connect('auth.db') as conn:
            count = conn.execute(
                'SELECT COUNT(*) FROM sessions WHERE user_id = ?',
                (authenticated_user['id'],),
            ).fetchone()[0]
        assert count == 0

    def test_migration_hashes_plaintext_rows_and_preserves_login(self, auth_app, authenticated_user):
        # Simulate a pre-migration row: raw token in the DB.
        raw = 'legacy-raw-token-abcdefghij0123456789012345'
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        with sqlite3.connect('auth.db') as conn:
            conn.execute(
                'INSERT INTO sessions (session_token, user_id, expires_at) VALUES (?, ?, ?)',
                (raw, authenticated_user['id'], future),
            )
        auth_app._ensure_auth_schema()
        with sqlite3.connect('auth.db') as conn:
            rows = [r[0] for r in conn.execute('SELECT session_token FROM sessions').fetchall()]
        assert raw not in rows
        assert auth_app._hash_session_token(raw) in rows
        # The cookie the browser holds (the raw value) still logs in.
        assert auth_app.verify_session(raw)['id'] == authenticated_user['id']

    def test_migration_is_idempotent(self, auth_app, authenticated_user):
        raw = auth_app.create_session(authenticated_user['id'])
        hashed = auth_app._hash_session_token(raw)
        auth_app._ensure_auth_schema()
        auth_app._ensure_auth_schema()
        with sqlite3.connect('auth.db') as conn:
            rows = [r[0] for r in conn.execute('SELECT session_token FROM sessions').fetchall()]
        # Already-hashed rows are untouched (not double-hashed).
        assert hashed in rows
        auth_app._session_cache_invalidate()
        assert auth_app.verify_session(raw)['id'] == authenticated_user['id']
