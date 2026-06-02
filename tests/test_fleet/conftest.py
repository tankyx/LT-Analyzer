"""Fixtures for the Fleet Tracker test suite.

Self-contained (does not reuse test_auth's session fixture) because the fleet
endpoints validate track_id against tracks.db and read per-track
race_data_track_N.db files — neither of which the auth suite seeds. We chdir
into a temp cwd, seed auth.db + tracks.db with the full production schema, then
import race_ui fresh so its module globals (track_db, app) bind to our temp DBs.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta
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

# Full tracks schema (mirrors initialize_databases.initialize_tracks_db) so
# get_track_by_id's SELECT of location/length_meters/etc. succeeds.
TRACKS_SCHEMA = """
CREATE TABLE tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_name TEXT NOT NULL,
    location TEXT,
    length_meters INTEGER,
    description TEXT,
    timing_url TEXT,
    websocket_url TEXT,
    column_mappings TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO tracks (id, track_name, location, timing_url, websocket_url, is_active)
VALUES (1, 'Test Track', 'Testville', 'http://example.com', 'ws://example.com', 1);
"""

TRACK_ID = 1


@pytest.fixture(scope="session")
def fleet_app(tmp_path_factory) -> Iterator:
    tmpdir = tmp_path_factory.mktemp("fleet_test_root")
    original_cwd = os.getcwd()
    os.chdir(tmpdir)

    conn = sqlite3.connect("auth.db")
    conn.executescript(BASE_AUTH_SCHEMA)
    conn.commit()
    conn.close()

    conn = sqlite3.connect("tracks.db")
    conn.executescript(TRACKS_SCHEMA)
    conn.commit()
    conn.close()

    os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-" + "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    os.environ.setdefault("TURNSTILE_SECRET_KEY", "")
    os.environ.setdefault("BREVO_API_KEY", "")
    os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

    for mod in list(sys.modules):
        if (
            mod == "race_ui" or mod.startswith("race_ui.")
            or mod == "race_app" or mod.startswith("race_app.")
        ):
            del sys.modules[mod]

    import race_ui  # noqa: E402
    race_ui.app.config["TESTING"] = True

    # Create the per-track race_data_track_1.db with the fleet tables.
    from multi_track_manager import MultiTrackManager
    MultiTrackManager().initialize_track_database(TRACK_ID)

    yield race_ui

    os.chdir(original_cwd)


@pytest.fixture
def reset_fleet(fleet_app) -> Iterator:
    """Truncate per-test mutable tables in auth.db and the track DB."""
    with sqlite3.connect("auth.db") as conn:
        for tbl in ("sessions", "login_attempts", "audit_log", "users"):
            try:
                conn.execute(f"DELETE FROM {tbl}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
    with sqlite3.connect(f"race_data_track_{TRACK_ID}.db") as conn:
        for tbl in ("fleet_assignments", "fleet_karts", "lap_history", "lap_times", "race_sessions"):
            conn.execute(f"DELETE FROM {tbl}")
        conn.commit()
    yield


@pytest.fixture
def track_conn(fleet_app, reset_fleet) -> Iterator[sqlite3.Connection]:
    """A connection to the (clean) per-track DB."""
    conn = sqlite3.connect(f"race_data_track_{TRACK_ID}.db")
    yield conn
    conn.close()


@pytest.fixture
def client(fleet_app, reset_fleet):
    with fleet_app.app.test_client() as c:
        yield c


@pytest.fixture
def admin_user(fleet_app, reset_fleet):
    pw = "admin-password-12345"
    with sqlite3.connect("auth.db") as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, email_verified) "
            "VALUES ('admin', ?, 'admin@example.com', 'admin', 1, 1)",
            (fleet_app.hash_password(pw),),
        )
        uid = cur.lastrowid
        conn.commit()
    return {"id": uid, "username": "admin", "password": pw}


@pytest.fixture
def normal_user(fleet_app, reset_fleet):
    pw = "user-password-12345"
    with sqlite3.connect("auth.db") as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, role, is_active, email_verified) "
            "VALUES ('alice', ?, 'alice@example.com', 'user', 1, 1)",
            (fleet_app.hash_password(pw),),
        )
        uid = cur.lastrowid
        conn.commit()
    return {"id": uid, "username": "alice", "password": pw}


def login(client, username, password):
    """Log in and return the CSRF token (Turnstile soft-passes in tests)."""
    client.post("/api/auth/login",
                json={"username": username, "password": password, "turnstile_token": "test"})
    return client.get("/api/auth/csrf").get_json()["csrfToken"]


# --- seed helpers -----------------------------------------------------------

def seed_session(conn, session_id, name="Endurance Test"):
    conn.execute(
        "INSERT INTO race_sessions (session_id, start_time, name, track) VALUES (?, ?, ?, 'Test Track')",
        (session_id, datetime.now().isoformat(), name),
    )
    conn.commit()


# Default owner used by direct-compute tests that don't go through the client.
SEED_USER_ID = 1


def seed_fleet_kart(conn, label, user_id=SEED_USER_ID):
    cur = conn.execute(
        "INSERT INTO fleet_karts (user_id, label, is_active, created_at) VALUES (?, ?, 1, ?)",
        (user_id, label, datetime.now().isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def seed_laps(conn, session_id, team, lap_secs, pit_counts, base=None, kart_number=7):
    """Insert lap_history rows. lap_secs and pit_counts are parallel lists;
    timestamps are spaced 1 minute apart so they fall inside the rolling window.

    A tiny per-lap offset (i*0.001s) keeps each lap_time string distinct so the
    analyzer's stale-snapshot dedup (identical consecutive strings) doesn't drop
    them. This shifts means by <0.005s, so pace assertions use approx().
    """
    base = base or datetime(2026, 5, 26, 12, 0, 0)
    rows = []
    for i, (secs, pit) in enumerate(zip(lap_secs, pit_counts)):
        ts = (base + timedelta(minutes=i)).isoformat()
        rows.append((session_id, ts, kart_number, team, i, f"{secs + i * 0.001:.3f}", 1, pit))
    conn.executemany(
        "INSERT INTO lap_history (session_id, timestamp, kart_number, team_name, "
        "lap_number, lap_time, position_after_lap, pit_this_lap) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def seed_assignment(conn, session_id, team, fleet_kart_id, stint_index, source="manual",
                    user_id=SEED_USER_ID):
    cur = conn.execute(
        "INSERT INTO fleet_assignments (user_id, session_id, team_name, fleet_kart_id, stint_index, "
        "source, created_at, superseded) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (user_id, session_id, team, fleet_kart_id, stint_index, source, datetime.now().isoformat()),
    )
    conn.commit()
    return cur.lastrowid
