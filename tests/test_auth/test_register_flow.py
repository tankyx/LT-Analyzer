"""Registration flow integration tests."""

import sqlite3

import pytest


pytestmark = pytest.mark.integration


def _seed_invite(code="bigcode123", max_uses=5):
    with sqlite3.connect("auth.db") as conn:
        conn.execute(
            "INSERT INTO invite_codes (code, max_uses, uses, note) VALUES (?, ?, 0, 'test')",
            (code, max_uses),
        )


def test_happy_path_creates_user_unverified_and_sends_email(client, mock_email):
    _seed_invite()
    resp = client.post("/api/auth/register", json={
        "username": "newperson",
        "email": "NewPerson@Example.com",
        "password": "a-strong-pass-12",
        "invite_code": "bigcode123",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["success"] is True
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT username, email, email_verified, verification_token, role, tos_accepted_at "
            "FROM users WHERE username = 'newperson'"
        ).fetchone()
    assert row is not None
    username, email, verified, token, role, tos = row
    assert verified == 0
    assert token and len(token) > 20
    assert role == "user"
    assert tos is not None
    assert email == "newperson@example.com"  # stored lowercased

    # Email was sent with a link containing the token.
    assert mock_email.send.call_count == 1
    args, _ = mock_email.send.call_args
    assert token in args[3] or token in args[4]


def test_missing_invite_blocks_registration_when_closed(client, mock_email):
    resp = client.post("/api/auth/register", json={
        "username": "joiner1",
        "email": "j@example.com",
        "password": "a-strong-pass-12",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "registration_failed"
    assert mock_email.send.call_count == 0


def test_weak_password_rejected(client, mock_email):
    _seed_invite()
    resp = client.post("/api/auth/register", json={
        "username": "joiner2",
        "email": "j@example.com",
        "password": "short",
        "invite_code": "bigcode123",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "weak_password"


def test_reserved_username_rejected(client):
    _seed_invite()
    resp = client.post("/api/auth/register", json={
        "username": "admin",  # reserved
        "email": "j@example.com",
        "password": "a-strong-pass-12",
        "invite_code": "bigcode123",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_username"


def test_terms_not_accepted_rejected(client):
    _seed_invite()
    resp = client.post("/api/auth/register", json={
        "username": "joiner3",
        "email": "j@example.com",
        "password": "a-strong-pass-12",
        "invite_code": "bigcode123",
        "accept_terms": False,
        "turnstile_token": "t",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "terms_not_accepted"


def test_duplicate_email_returns_generic_error(client, mock_email):
    _seed_invite(max_uses=10)
    # First registration succeeds
    r1 = client.post("/api/auth/register", json={
        "username": "person1",
        "email": "dup@example.com",
        "password": "a-strong-pass-12",
        "invite_code": "bigcode123",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert r1.status_code == 200
    # Second registration with same email (case-insensitive) gets generic error.
    r2 = client.post("/api/auth/register", json={
        "username": "person2",
        "email": "DUP@example.com",
        "password": "a-strong-pass-12",
        "invite_code": "bigcode123",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert r2.status_code == 400
    assert r2.get_json()["error"] == "registration_failed"


def test_invite_uses_increment_and_exhaust(client, mock_email):
    _seed_invite(code="single", max_uses=1)
    r1 = client.post("/api/auth/register", json={
        "username": "first",
        "email": "first@example.com",
        "password": "a-strong-pass-12",
        "invite_code": "single",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert r1.status_code == 200
    r2 = client.post("/api/auth/register", json={
        "username": "second",
        "email": "second@example.com",
        "password": "a-strong-pass-12",
        "invite_code": "single",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert r2.status_code == 400
    with sqlite3.connect("auth.db") as conn:
        uses = conn.execute("SELECT uses FROM invite_codes WHERE code = 'single'").fetchone()[0]
    assert uses == 1


def test_failed_register_does_not_burn_invite(client, mock_email):
    """Regression: an INSERT IntegrityError (e.g. duplicate email) must NOT consume
    an invite-code use. Bug found in prod 2026-05-26: the with-block was committing
    on early return so the invite counter incremented even though no user was created."""
    _seed_invite(code="precious", max_uses=3)
    # First registration succeeds → uses=1
    r1 = client.post("/api/auth/register", json={
        "username": "userone",
        "email": "dup@example.com",
        "password": "a-strong-pass-12",
        "invite_code": "precious",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert r1.status_code == 200, r1.get_data(as_text=True)
    # Three duplicate-email attempts must NOT each consume a use
    for i in range(3):
        r = client.post("/api/auth/register", json={
            "username": f"u_dup_{i}",
            "email": "dup@example.com",  # same email — partial-unique index rejects
            "password": "a-strong-pass-12",
            "invite_code": "precious",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert r.status_code == 400, r.get_data(as_text=True)
    with sqlite3.connect("auth.db") as conn:
        uses = conn.execute(
            "SELECT uses FROM invite_codes WHERE code = 'precious'"
        ).fetchone()[0]
    # Only one consumption — the one that actually created a user.
    assert uses == 1


def test_audit_row_written_on_register(client, mock_email):
    _seed_invite()
    client.post("/api/auth/register", json={
        "username": "audited",
        "email": "audited@example.com",
        "password": "a-strong-pass-12",
        "invite_code": "bigcode123",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    with sqlite3.connect("auth.db") as conn:
        rows = conn.execute(
            "SELECT action FROM audit_log WHERE action = 'user_register'"
        ).fetchall()
    assert len(rows) == 1
