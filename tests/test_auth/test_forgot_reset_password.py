"""Password reset (forgot + reset) integration tests."""

import sqlite3
from datetime import datetime, timedelta

import pytest


pytestmark = pytest.mark.integration


def test_forgot_password_generates_token_and_sends_email(auth_app, client, mock_email, authenticated_user):
    resp = client.post("/api/auth/forgot-password", json={
        "email": authenticated_user["email"],
        "turnstile_token": "t",
    })
    assert resp.status_code == 200
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT password_reset_token, password_reset_expires FROM users WHERE id = ?",
            (authenticated_user["id"],),
        ).fetchone()
    assert row[0] and len(row[0]) > 20
    assert row[1] is not None
    assert mock_email.send.call_count == 1


def test_forgot_password_returns_generic_for_unknown_email(client, mock_email):
    resp = client.post("/api/auth/forgot-password", json={
        "email": "ghost@example.com",
        "turnstile_token": "t",
    })
    assert resp.status_code == 200
    assert resp.get_json() == {"success": True}
    assert mock_email.send.call_count == 0


def test_reset_password_happy_path_changes_hash_and_invalidates_sessions(
    auth_app, client, mock_email, authenticated_user
):
    # Pretend the user already had a live session.
    with sqlite3.connect("auth.db") as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, session_token, expires_at) VALUES (?, 'stale', ?)",
            (authenticated_user["id"], (datetime.now() + timedelta(hours=1)).isoformat()),
        )
    # Trigger forgot-password to issue a real token.
    client.post("/api/auth/forgot-password", json={
        "email": authenticated_user["email"],
        "turnstile_token": "t",
    })
    with sqlite3.connect("auth.db") as conn:
        token = conn.execute(
            "SELECT password_reset_token FROM users WHERE id = ?",
            (authenticated_user["id"],),
        ).fetchone()[0]
    assert token

    resp = client.post("/api/auth/reset-password", json={
        "token": token,
        "new_password": "brand-new-strong-pass",
    })
    assert resp.status_code == 200
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT password_hash, password_reset_token FROM users WHERE id = ?",
            (authenticated_user["id"],),
        ).fetchone()
        sess_count = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (authenticated_user["id"],)
        ).fetchone()[0]
    assert row[1] is None  # token cleared
    assert auth_app.verify_password("brand-new-strong-pass", row[0])
    assert sess_count == 0  # all sessions invalidated


def test_reset_password_invalid_token(client):
    resp = client.post("/api/auth/reset-password", json={
        "token": "nope",
        "new_password": "a-strong-pass-12",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_token"


def test_reset_password_expired_token(client, authenticated_user):
    with sqlite3.connect("auth.db") as conn:
        conn.execute(
            "UPDATE users SET password_reset_token = ?, password_reset_expires = ? WHERE id = ?",
            ("exp_tok", (datetime.now() - timedelta(hours=1)).isoformat(), authenticated_user["id"]),
        )
    resp = client.post("/api/auth/reset-password", json={
        "token": "exp_tok",
        "new_password": "a-strong-pass-12",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "expired_token"


def test_reset_password_weak_password_rejected(client, authenticated_user):
    with sqlite3.connect("auth.db") as conn:
        conn.execute(
            "UPDATE users SET password_reset_token = ?, password_reset_expires = ? WHERE id = ?",
            ("good_tok", (datetime.now() + timedelta(hours=1)).isoformat(), authenticated_user["id"]),
        )
    resp = client.post("/api/auth/reset-password", json={
        "token": "good_tok",
        "new_password": "short",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "weak_password"
