"""Login endpoint changes: Turnstile + email_verified gate + audit."""

import sqlite3

import pytest

from tests.test_auth.conftest import login_as


pytestmark = pytest.mark.integration


def test_login_blocks_unverified_user(auth_app, client):
    with sqlite3.connect("auth.db") as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, email_verified) "
            "VALUES ('uv', ?, 'uv@x', 'user', 1, 0)",
            (auth_app.hash_password("good-password-12"),),
        )
    resp = login_as(client, "uv", "good-password-12")
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"] == "email_not_verified"
    assert body["email"] == "uv@x"


def test_login_succeeds_for_verified_user(authenticated_user, client):
    resp = login_as(client, authenticated_user["username"], authenticated_user["password"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["user"]["username"] == authenticated_user["username"]


def test_login_failure_is_audited(client, authenticated_user):
    login_as(client, authenticated_user["username"], "wrong-password-1234")
    with sqlite3.connect("auth.db") as conn:
        rows = conn.execute(
            "SELECT action FROM audit_log WHERE action = 'login_failed'"
        ).fetchall()
    assert len(rows) >= 1


def test_login_success_is_audited(client, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    with sqlite3.connect("auth.db") as conn:
        rows = conn.execute(
            "SELECT action FROM audit_log WHERE action = 'login_success'"
        ).fetchall()
    assert len(rows) == 1


def test_login_rate_limit_still_works(auth_app, client, monkeypatch):
    """The legacy _is_rate_limited should still kick in after enough failures."""
    monkeypatch.setattr(auth_app, "LOGIN_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(auth_app, "LOGIN_WINDOW_MINUTES", 15)
    with sqlite3.connect("auth.db") as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, email_verified) "
            "VALUES ('rl', ?, 'rl@x', 'user', 1, 1)",
            (auth_app.hash_password("password-strong-1"),),
        )
    for _ in range(3):
        login_as(client, "rl", "wrong-1234567890")
    resp = login_as(client, "rl", "wrong-1234567890")
    assert resp.status_code == 429
