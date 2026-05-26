"""Phase 2 migration: user_track_prefs table + index + FK cascade."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.migrate_phase2_prefs import migrate as migrate_phase2  # noqa: E402
from scripts.migrate_phase1_auth import migrate as migrate_phase1  # noqa: E402


pytestmark = pytest.mark.integration


BASE_SCHEMA = """
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


def _make_base(tmp_path) -> str:
    db = tmp_path / "auth.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(BASE_SCHEMA)
    conn.execute(
        "INSERT INTO users (username, password_hash, email, role) "
        "VALUES ('alice', 'hash', 'a@example.com', 'user')"
    )
    conn.commit()
    conn.close()
    # Phase 1 has to run first because phase 2 doesn't recreate the base schema.
    migrate_phase1(str(db))
    return str(db)


def test_creates_table_and_index(tmp_path):
    db = _make_base(tmp_path)
    summary = migrate_phase2(db)
    assert 'user_track_prefs' in summary['tables_created']
    assert 'idx_user_track_prefs_user' in summary['indexes_created']
    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(user_track_prefs)").fetchall()}
    for expected in [
        'id', 'user_id', 'track_id', 'my_team', 'monitored_teams',
        'pit_stop_time', 'required_pit_stops', 'default_lap_time',
        'stint_planner_config', 'stint_planner_presets', 'driver_names',
        'current_driver_index', 'updated_at',
    ]:
        assert expected in cols


def test_idempotent(tmp_path):
    db = _make_base(tmp_path)
    migrate_phase2(db)
    second = migrate_phase2(db)
    assert second['tables_created'] == []
    assert second['indexes_created'] == []


def test_unique_user_track_constraint(tmp_path):
    db = _make_base(tmp_path)
    migrate_phase2(db)
    with sqlite3.connect(db) as conn:
        uid = conn.execute("SELECT id FROM users").fetchone()[0]
        conn.execute(
            "INSERT INTO user_track_prefs (user_id, track_id) VALUES (?, 1)", (uid,)
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO user_track_prefs (user_id, track_id) VALUES (?, 1)", (uid,)
            )


def test_fk_cascade_on_hard_delete(tmp_path):
    """If a user row is hard-deleted, their prefs should cascade."""
    db = _make_base(tmp_path)
    migrate_phase2(db)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        uid = conn.execute("SELECT id FROM users").fetchone()[0]
        conn.execute(
            "INSERT INTO user_track_prefs (user_id, track_id) VALUES (?, 1)", (uid,)
        )
        conn.execute("INSERT INTO user_track_prefs (user_id, track_id) VALUES (?, 2)", (uid,))
        conn.commit()
        # Sessions hold a non-cascading FK to users; clear those first for the
        # hard delete to succeed.
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        remaining = conn.execute(
            "SELECT COUNT(*) FROM user_track_prefs WHERE user_id = ?", (uid,)
        ).fetchone()[0]
    assert remaining == 0
