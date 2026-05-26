"""Self-service /api/auth/me endpoints (GDPR baseline)."""

import sqlite3

import pytest

from tests.test_auth.conftest import csrf_token, login_as


pytestmark = pytest.mark.integration


def test_me_get_returns_own_profile(client, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    user = resp.get_json()["user"]
    assert user["username"] == authenticated_user["username"]
    assert user["email"] == authenticated_user["email"]
    assert user["role"] == "user"
    assert "password_hash" not in user


def test_me_get_requires_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_export_includes_own_audit_rows(client, auth_app, authenticated_user):
    auth_app._audit("self_test_event", actor_user_id=authenticated_user["id"], target="x")
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    token = csrf_token(client)
    resp = client.post("/api/auth/me/export", headers={"X-CSRF-Token": token})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["profile"]["username"] == authenticated_user["username"]
    actions = {row["action"] for row in body["audit_log"]}
    assert "self_test_event" in actions
    # self_export is audited but happens after the audit query — verify via DB.
    with sqlite3.connect("auth.db") as conn:
        post_row = conn.execute(
            "SELECT 1 FROM audit_log WHERE action = 'self_export' AND actor_user_id = ?",
            (authenticated_user["id"],),
        ).fetchone()
    assert post_row is not None


def test_me_export_does_not_leak_other_users(client, auth_app, authenticated_user):
    # Insert someone else and an audit row for them.
    with sqlite3.connect("auth.db") as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, email_verified) "
            "VALUES ('other', 'h', 'other@example.com', 'user', 1, 1)"
        )
        other_id = cur.lastrowid
    auth_app._audit("secret", actor_user_id=other_id, target="leak")

    login_as(client, authenticated_user["username"], authenticated_user["password"])
    token = csrf_token(client)
    resp = client.post("/api/auth/me/export", headers={"X-CSRF-Token": token})
    actions = {row["action"] for row in resp.get_json()["audit_log"]}
    assert "secret" not in actions


def test_me_delete_soft_deletes_scrambles_and_invalidates(client, auth_app, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    token = csrf_token(client)
    resp = client.delete("/api/auth/me", headers={"X-CSRF-Token": token})
    assert resp.status_code == 200

    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT username, email, is_active, deleted_at FROM users WHERE id = ?",
            (authenticated_user["id"],),
        ).fetchone()
        sess_count = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (authenticated_user["id"],)
        ).fetchone()[0]
    assert row[0].startswith("deleted_") and "alice" not in row[0]
    assert row[1].startswith("deleted+")
    assert row[2] == 0
    assert row[3] is not None  # deleted_at set
    assert sess_count == 0

    # Subsequent login attempt as the original username fails (it's been scrambled).
    resp2 = client.post(
        "/api/auth/login",
        json={
            "username": authenticated_user["username"],
            "password": authenticated_user["password"],
            "turnstile_token": "t",
        },
    )
    assert resp2.status_code == 401
