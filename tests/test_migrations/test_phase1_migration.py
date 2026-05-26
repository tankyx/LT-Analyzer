"""Migration script tests — idempotency, duplicate-email guard, bootstrap invite."""

import sqlite3
import sys
from pathlib import Path

import pytest

# Make the scripts dir importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.migrate_phase1_auth import migrate  # noqa: E402


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
        "VALUES ('admin', 'hash', 'admin@localhost', 'admin')"
    )
    conn.commit()
    conn.close()
    return str(db)


def _column_set(db_path, table):
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_migration_adds_columns_and_tables(tmp_path):
    db = _make_base(tmp_path)
    summary = migrate(db)
    cols = _column_set(db, "users")
    for expected in [
        "email_verified",
        "verification_token",
        "verification_token_expires",
        "password_reset_token",
        "password_reset_expires",
        "tos_accepted_at",
        "deleted_at",
    ]:
        assert expected in cols

    with sqlite3.connect(db) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "invite_codes" in tables
    assert "audit_log" in tables
    assert "rate_limit_events" in tables

    assert summary["admins_backfilled"] == 1
    assert summary["invite_seed_code"] is not None
    assert any("placeholder email" in w for w in summary["warnings"])


def test_migration_is_idempotent(tmp_path):
    db = _make_base(tmp_path)
    s1 = migrate(db)
    s2 = migrate(db)
    assert s2["columns_added"] == []
    assert s2["tables_created"] == []
    assert s2["indexes_created"] == []
    # Second run doesn't re-backfill rows that are already verified.
    assert s2["admins_backfilled"] == 0
    # Bootstrap invite only created once.
    assert s2["invite_seed_code"] is None


def test_migration_partial_unique_email_rejects_duplicates(tmp_path):
    db = _make_base(tmp_path)
    migrate(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, email, role) "
            "VALUES ('u2', 'h', 'shared@a.com', 'user')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO users (username, password_hash, email, role) "
                "VALUES ('u3', 'h', 'SHARED@a.com', 'user')"
            )


def test_migration_aborts_on_pre_existing_duplicate_emails(tmp_path):
    db = _make_base(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, email, role) "
            "VALUES ('u2', 'h', 'Same@x.com', 'user')"
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, email, role) "
            "VALUES ('u3', 'h', 'same@x.com', 'user')"
        )
        conn.commit()
    with pytest.raises(RuntimeError) as ei:
        migrate(db)
    assert "duplicate emails" in str(ei.value).lower()


def test_partial_unique_token_indexes_allow_null(tmp_path):
    db = _make_base(tmp_path)
    migrate(db)
    with sqlite3.connect(db) as conn:
        # Two rows with NULL verification_token must coexist.
        conn.execute(
            "INSERT INTO users (username, password_hash, email, role) "
            "VALUES ('a', 'h', 'a@x.com', 'user')"
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, email, role) "
            "VALUES ('b', 'h', 'b@x.com', 'user')"
        )
        # But duplicate non-null tokens are rejected.
        conn.execute("UPDATE users SET verification_token = 'shared' WHERE username = 'a'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE users SET verification_token = 'shared' WHERE username = 'b'")
