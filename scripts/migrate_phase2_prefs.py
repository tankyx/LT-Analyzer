#!/usr/bin/env python3
"""Phase 2 user-prefs schema migration. Idempotent — safe to re-run.

Adds:
 - user_track_prefs table: per-(user_id, track_id) settings for my_team,
   monitored_teams, pit_stop_time, required_pit_stops, default_lap_time,
   stint_planner_config, stint_planner_presets, driver_names,
   current_driver_index, updated_at.
 - UNIQUE(user_id, track_id) so each user has at most one row per track.
 - FK on user_id → users(id) ON DELETE CASCADE.
 - idx_user_track_prefs_user index on user_id.

Usage:  python scripts/migrate_phase2_prefs.py [--db PATH]
"""

import argparse
import os
import sqlite3
import sys


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


def migrate(db_path: str) -> dict:
    """Run the migration. Returns a summary dict for tests/callers."""
    summary: dict[str, object] = {
        'tables_created': [],
        'indexes_created': [],
    }

    conn = sqlite3.connect(db_path)
    # Make sure FK enforcement is on so the cascade clause has effect.
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if not _table_exists(conn, 'user_track_prefs'):
            conn.execute('''
                CREATE TABLE user_track_prefs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    my_team TEXT,
                    monitored_teams TEXT,
                    pit_stop_time INTEGER,
                    required_pit_stops INTEGER,
                    default_lap_time REAL,
                    stint_planner_config TEXT,
                    stint_planner_presets TEXT,
                    driver_names TEXT,
                    current_driver_index INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, track_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            summary['tables_created'].append('user_track_prefs')

        if not _index_exists(conn, 'idx_user_track_prefs_user'):
            conn.execute(
                'CREATE INDEX idx_user_track_prefs_user '
                'ON user_track_prefs(user_id)'
            )
            summary['indexes_created'].append('idx_user_track_prefs_user')

        # stint_assignments column added after the initial migration.
        cols = {row[1] for row in conn.execute('PRAGMA table_info(user_track_prefs)').fetchall()}
        if 'stint_assignments' not in cols:
            conn.execute('ALTER TABLE user_track_prefs ADD COLUMN stint_assignments TEXT')
            summary['tables_created'].append('user_track_prefs.stint_assignments (column)')

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

    summary = migrate(args.db)
    print(f"Phase 2 migration complete on {args.db}")
    print(f"  Tables created:  {summary['tables_created'] or '(none — already present)'}")
    print(f"  Indexes created: {summary['indexes_created'] or '(none — already present)'}")


if __name__ == '__main__':
    main()
