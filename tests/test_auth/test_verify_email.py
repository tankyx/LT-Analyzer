"""Email-verification and resend-verification tests."""

import sqlite3
from datetime import datetime, timedelta

import pytest


pytestmark = pytest.mark.integration


def _make_unverified_user(token="vtok123", expires_in_hours=48):
    expires = (datetime.now() + timedelta(hours=expires_in_hours)).isoformat()
    with sqlite3.connect("auth.db") as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, "
            "email_verified, verification_token, verification_token_expires) "
            "VALUES ('bob', 'hash', 'bob@example.com', 'user', 1, 0, ?, ?)",
            (token, expires),
        )
        return cur.lastrowid


def test_verify_email_flips_flag_and_clears_token(client, mock_email):
    uid = _make_unverified_user(token="goodtoken")
    resp = client.post("/api/auth/verify-email", json={"token": "goodtoken"})
    assert resp.status_code == 200
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT email_verified, verification_token FROM users WHERE id = ?", (uid,)
        ).fetchone()
    assert row == (1, None)
    # A welcome email was attempted.
    assert mock_email.send.call_count == 1


def test_verify_email_invalid_token(client):
    resp = client.post("/api/auth/verify-email", json={"token": "nope"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_token"


def test_verify_email_expired_token(client):
    _make_unverified_user(token="expired", expires_in_hours=-1)
    resp = client.post("/api/auth/verify-email", json={"token": "expired"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "expired_token"


def test_verify_email_blank_token(client):
    resp = client.post("/api/auth/verify-email", json={"token": ""})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_token"


def test_verify_email_reused_token_fails(client, mock_email):
    _make_unverified_user(token="oneuse")
    r1 = client.post("/api/auth/verify-email", json={"token": "oneuse"})
    assert r1.status_code == 200
    r2 = client.post("/api/auth/verify-email", json={"token": "oneuse"})
    assert r2.status_code == 400


def test_resend_verification_generates_new_token_for_unverified(client, mock_email):
    uid = _make_unverified_user(token="oldtok")
    resp = client.post("/api/auth/resend-verification", json={
        "email": "bob@example.com",
        "turnstile_token": "t",
    })
    assert resp.status_code == 200
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT verification_token FROM users WHERE id = ?", (uid,)
        ).fetchone()
    assert row[0] and row[0] != "oldtok"
    assert mock_email.send.call_count == 1


def test_resend_verification_returns_generic_for_unknown_email(client, mock_email):
    resp = client.post("/api/auth/resend-verification", json={
        "email": "nobody@example.com",
        "turnstile_token": "t",
    })
    assert resp.status_code == 200
    assert resp.get_json() == {"success": True}
    assert mock_email.send.call_count == 0


def test_resend_verification_skips_already_verified(client, mock_email):
    with sqlite3.connect("auth.db") as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, email_verified) "
            "VALUES ('alice', 'h', 'a@example.com', 'user', 1, 1)"
        )
    resp = client.post("/api/auth/resend-verification", json={
        "email": "a@example.com",
        "turnstile_token": "t",
    })
    assert resp.status_code == 200
    assert mock_email.send.call_count == 0
