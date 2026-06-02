"""Fixtures for the Phase 1 auth test suite.

Key idea: chdir into a per-session temp dir, seed `auth.db` with the original
schema (matching initialize_databases.py), then import `race_ui`. race_ui's
`_ensure_auth_schema()` runs at import and adds the Phase 1 columns/tables on
top of that base schema, giving us a real sqlite-backed Flask test client.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from typing import Iterator
from unittest.mock import MagicMock

import pytest


BASE_AUTH_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    role TEXT DEFAULT 'user',
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    ip_address TEXT,
    success BOOLEAN,
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture(scope="session")
def auth_app(tmp_path_factory) -> Iterator:
    """Session-scoped: stage auth.db + tracks.db in a tmp cwd and import race_ui."""
    tmpdir = tmp_path_factory.mktemp("auth_test_root")
    original_cwd = os.getcwd()
    os.chdir(tmpdir)

    # Seed base auth.db (mirrors initialize_databases.py)
    conn = sqlite3.connect("auth.db")
    conn.executescript(BASE_AUTH_SCHEMA)
    conn.commit()
    conn.close()

    # Stable env for the import — soft-pass turnstile, NullEmailSender, locked-down defaults.
    os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-" + "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    os.environ.setdefault("TURNSTILE_SECRET_KEY", "")
    os.environ.setdefault("BREVO_API_KEY", "")
    os.environ.setdefault("REGISTRATION_OPEN", "false")
    os.environ.setdefault("ENABLE_TEST_ENDPOINTS", "false")
    os.environ.setdefault("SESSION_COOKIE_SECURE", "false")  # test client uses http

    # Drop any cached race_ui import so a previous session can't bleed state.
    for mod in list(sys.modules):
        if (
            mod == "race_ui" or mod.startswith("race_ui.")
            or mod == "race_app" or mod.startswith("race_app.")
        ):
            del sys.modules[mod]

    sys.path.insert(0, str(tmpdir.parent.parent.parent))  # ensure project root importable
    # Project root is the LT-Analyzer dir; conftest.py at tests/ already inserted it.
    import race_ui  # noqa: E402

    race_ui.app.config["TESTING"] = True

    yield race_ui

    os.chdir(original_cwd)


@pytest.fixture
def reset_db(auth_app) -> Iterator:
    """Truncate the per-test mutable tables before each test."""
    with sqlite3.connect("auth.db") as conn:
        for tbl in (
            "sessions",
            "login_attempts",
            "audit_log",
            "rate_limit_events",
            "invite_codes",
            "users",
        ):
            try:
                conn.execute(f"DELETE FROM {tbl}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
    yield


@pytest.fixture
def client(auth_app, reset_db):
    """Flask test client. Each test starts with a fresh auth.db state."""
    with auth_app.app.test_client() as c:
        yield c


@pytest.fixture
def mock_email(auth_app, monkeypatch):
    """Replace the email sender with a Mock that records send() calls."""
    sender = MagicMock()
    sender.send.return_value = (True, "")
    monkeypatch.setattr(auth_app, "_email_sender", sender)
    return sender


@pytest.fixture
def authenticated_admin(auth_app, client):
    """Insert an admin user, return (user_id, password). Tests can log in with these."""
    pw = "admin-password-12345"
    with sqlite3.connect("auth.db") as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, email_verified) "
            "VALUES (?, ?, ?, 'admin', 1, 1)",
            ("admin", auth_app.hash_password(pw), "admin@example.com"),
        )
        uid = cur.lastrowid
        conn.commit()
    return {"id": uid, "username": "admin", "password": pw}


@pytest.fixture
def authenticated_user(auth_app, client):
    """Insert a verified non-admin user."""
    pw = "user-password-12345"
    with sqlite3.connect("auth.db") as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, email_verified) "
            "VALUES (?, ?, ?, 'user', 1, 1)",
            ("alice", auth_app.hash_password(pw), "alice@example.com"),
        )
        uid = cur.lastrowid
        conn.commit()
    return {"id": uid, "username": "alice", "password": pw, "email": "alice@example.com"}


def login_as(client, username: str, password: str):
    """Helper: log in via /api/auth/login (Turnstile is soft-pass during tests)."""
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "turnstile_token": "test"},
    )


def csrf_token(client) -> str:
    return client.get("/api/auth/csrf").get_json()["csrfToken"]
