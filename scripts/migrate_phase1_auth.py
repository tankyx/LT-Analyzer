#!/usr/bin/env python3
"""Phase 1 auth schema migration. Idempotent — safe to re-run.

Adds:
 - columns on users: email_verified, verification_token(+expires),
   password_reset_token(+expires), tos_accepted_at, deleted_at.
 - partial unique indexes on verification_token, password_reset_token,
   LOWER(email).
 - new tables: invite_codes, audit_log, rate_limit_events (with indexes).
 - backfill: email_verified=1 for existing admins.
 - bootstrap: one invite code with max_uses=20 if invite_codes is empty.

Aborts cleanly before creating the email unique index if duplicates exist —
the operator must resolve them first rather than have the migration silently
fail mid-way.

Usage:  python scripts/migrate_phase1_auth.py [--db PATH]
"""

import argparse
import os
import secrets
import sqlite3
import sys


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _index_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    if _column_exists(conn, table, column):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    return True


def _check_duplicate_emails(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT LOWER(email) AS k, COUNT(*) AS c
        FROM users
        WHERE email IS NOT NULL AND TRIM(email) <> ''
        GROUP BY k
        HAVING c > 1
        """
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def migrate(db_path: str) -> dict:
    """Run the migration. Returns a summary dict for callers (tests use this)."""
    summary: dict[str, object] = {
        'columns_added': [],
        'tables_created': [],
        'indexes_created': [],
        'admins_backfilled': 0,
        'invite_seed_code': None,
        'warnings': [],
    }

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        # Sanity-check before the email unique index — refuse to proceed on dupes.
        dupes = _check_duplicate_emails(conn)
        if dupes:
            msg = ', '.join(f"{e} ({n} rows)" for e, n in dupes[:5])
            raise RuntimeError(
                f"Aborting migration: duplicate emails exist (case-insensitive): {msg}. "
                "Resolve manually before re-running so we don't silently lose data."
            )

        # --- users columns ---
        for col_name, col_ddl in [
            ('email_verified', 'email_verified INTEGER NOT NULL DEFAULT 0'),
            ('verification_token', 'verification_token TEXT'),
            ('verification_token_expires', 'verification_token_expires TIMESTAMP'),
            ('password_reset_token', 'password_reset_token TEXT'),
            ('password_reset_expires', 'password_reset_expires TIMESTAMP'),
            ('tos_accepted_at', 'tos_accepted_at TIMESTAMP'),
            ('deleted_at', 'deleted_at TIMESTAMP'),
        ]:
            if _add_column(conn, 'users', col_name, col_ddl):
                summary['columns_added'].append(col_name)

        # --- partial unique indexes ---
        if not _index_exists(conn, 'idx_users_verification_token'):
            conn.execute(
                "CREATE UNIQUE INDEX idx_users_verification_token "
                "ON users(verification_token) WHERE verification_token IS NOT NULL"
            )
            summary['indexes_created'].append('idx_users_verification_token')
        if not _index_exists(conn, 'idx_users_password_reset_token'):
            conn.execute(
                "CREATE UNIQUE INDEX idx_users_password_reset_token "
                "ON users(password_reset_token) WHERE password_reset_token IS NOT NULL"
            )
            summary['indexes_created'].append('idx_users_password_reset_token')
        if not _index_exists(conn, 'idx_users_email_lower'):
            conn.execute(
                "CREATE UNIQUE INDEX idx_users_email_lower "
                "ON users(LOWER(email)) WHERE email IS NOT NULL AND deleted_at IS NULL"
            )
            summary['indexes_created'].append('idx_users_email_lower')

        # --- invite_codes ---
        if not _table_exists(conn, 'invite_codes'):
            conn.execute(
                """
                CREATE TABLE invite_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    uses INTEGER NOT NULL DEFAULT 0,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    note TEXT,
                    FOREIGN KEY (created_by) REFERENCES users(id)
                )
                """
            )
            summary['tables_created'].append('invite_codes')
        if not _index_exists(conn, 'idx_invite_codes_code'):
            conn.execute("CREATE INDEX idx_invite_codes_code ON invite_codes(code)")
            summary['indexes_created'].append('idx_invite_codes_code')

        # --- audit_log ---
        if not _table_exists(conn, 'audit_log'):
            conn.execute(
                """
                CREATE TABLE audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id INTEGER,
                    action TEXT NOT NULL,
                    target TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    details TEXT
                )
                """
            )
            summary['tables_created'].append('audit_log')
        if not _index_exists(conn, 'idx_audit_log_actor'):
            conn.execute(
                "CREATE INDEX idx_audit_log_actor "
                "ON audit_log(actor_user_id, timestamp DESC)"
            )
            summary['indexes_created'].append('idx_audit_log_actor')
        if not _index_exists(conn, 'idx_audit_log_action'):
            conn.execute(
                "CREATE INDEX idx_audit_log_action "
                "ON audit_log(action, timestamp DESC)"
            )
            summary['indexes_created'].append('idx_audit_log_action')

        # --- rate_limit_events ---
        if not _table_exists(conn, 'rate_limit_events'):
            conn.execute(
                """
                CREATE TABLE rate_limit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bucket TEXT NOT NULL,
                    key TEXT NOT NULL,
                    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            summary['tables_created'].append('rate_limit_events')
        if not _index_exists(conn, 'idx_rate_limit_bucket_key_time'):
            conn.execute(
                "CREATE INDEX idx_rate_limit_bucket_key_time "
                "ON rate_limit_events(bucket, key, occurred_at)"
            )
            summary['indexes_created'].append('idx_rate_limit_bucket_key_time')

        # --- admin backfill ---
        cur = conn.execute(
            "UPDATE users SET email_verified = 1 WHERE role = 'admin' AND email_verified = 0"
        )
        summary['admins_backfilled'] = cur.rowcount

        # Warn on placeholder admin emails — forgot-password won't reach those.
        placeholders = conn.execute(
            "SELECT username, email FROM users "
            "WHERE role = 'admin' AND email LIKE '%@localhost'"
        ).fetchall()
        for username, email in placeholders:
            summary['warnings'].append(
                f"Admin '{username}' has placeholder email '{email}'. "
                "Set a real email before relying on forgot-password."
            )

        # --- bootstrap invite ---
        count = conn.execute("SELECT COUNT(*) FROM invite_codes").fetchone()[0]
        if count == 0:
            code = secrets.token_urlsafe(8)
            conn.execute(
                "INSERT INTO invite_codes (code, max_uses, note) VALUES (?, ?, ?)",
                (code, 20, 'phase1 beta seed'),
            )
            summary['invite_seed_code'] = code

        conn.commit()
    finally:
        conn.close()

    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--db',
        default=os.environ.get('AUTH_DB_PATH', 'auth.db'),
        help='Path to auth.db (default: ./auth.db)',
    )
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.stderr.write(f"ERROR: {args.db} does not exist. Run initialize_databases.py first.\n")
        sys.exit(1)

    try:
        summary = migrate(args.db)
    except RuntimeError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(2)

    print(f"Migration complete on {args.db}")
    print(f"  Columns added:    {summary['columns_added'] or '(none — already present)'}")
    print(f"  Tables created:   {summary['tables_created'] or '(none — already present)'}")
    print(f"  Indexes created:  {summary['indexes_created'] or '(none — already present)'}")
    print(f"  Admins backfilled: {summary['admins_backfilled']}")
    if summary['invite_seed_code']:
        print()
        print(f"  BETA INVITE CODE (max_uses=20): {summary['invite_seed_code']}")
        print("  Distribute this to early testers. Save it now — it won't be shown again.")
    for w in summary['warnings']:
        print(f"  WARNING: {w}")


if __name__ == '__main__':
    main()
