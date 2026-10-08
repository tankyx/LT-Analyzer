#!/usr/bin/env python3
"""Backfill `lap_history.gap` (per-lap gap-to-leader) from `lap_times`.

The parser now writes the live `Gap` on every completed lap into
`lap_history.gap`, which the Delta chart reads. Track databases created before
that column existed hold historical laps with a NULL gap; this script fills
them in from the `lap_times` snapshot that was recorded on the same tick (the
parser writes both tables from one standings batch, so the timestamps match).

Matching is attempted in three passes, cheapest first:
  1. exact (session_id, kart_number, timestamp)        -- the normal case
  2. same lap time, first snapshot at/after the lap     -- clock skew
  3. same lap time, last snapshot at/before the lap     -- clock skew

Usage
-----
    python migrations/backfill_lap_history_gap.py            # all race_data_track_*.db
    python migrations/backfill_lap_history_gap.py track_1.db track_2.db
    python migrations/backfill_lap_history_gap.py --dry-run   # report, write nothing

Safe to run while the backend is live: WAL + busy_timeout are set, and the
update is a single statement per database. Prefer a quiet period for very
large databases (it still scans each `lap_history` row missing a gap).
"""
from __future__ import annotations

import argparse
import glob
import os
import sqlite3
import sys
import time

BACKFILL_SQL = """
UPDATE lap_history AS lh
   SET gap = COALESCE(
       (SELECT lt.gap FROM lap_times lt
         WHERE lt.session_id = lh.session_id
           AND lt.kart_number = lh.kart_number
           AND lt.timestamp = lh.timestamp
         LIMIT 1),
       (SELECT lt.gap FROM lap_times lt
         WHERE lt.session_id = lh.session_id
           AND lt.kart_number = lh.kart_number
           AND lt.last_lap = lh.lap_time
           AND lt.timestamp >= lh.timestamp
         ORDER BY lt.timestamp ASC
         LIMIT 1),
       (SELECT lt.gap FROM lap_times lt
         WHERE lt.session_id = lh.session_id
           AND lt.kart_number = lh.kart_number
           AND lt.last_lap = lh.lap_time
           AND lt.timestamp <= lh.timestamp
         ORDER BY lt.timestamp DESC
         LIMIT 1)
   )
 WHERE (lh.gap IS NULL OR lh.gap = '')
"""


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def backfill_db(path: str, dry_run: bool = False) -> tuple[int, int]:
    """Return (missing_before, updated)."""
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")

        if not _table_exists(conn, 'lap_history') or not _table_exists(conn, 'lap_times'):
            return (0, 0)

        # Ensure the column exists (the parser's boot-time migration does this
        # too, but the script must work on a database that hasn't been opened
        # by the current code yet).
        cols = [c[1] for c in conn.execute("PRAGMA table_info(lap_history)")]
        if 'gap' not in cols:
            if dry_run:
                # Every lap row would be missing the column, so report them all.
                total = conn.execute("SELECT COUNT(*) FROM lap_history").fetchone()[0]
                print(f"  [dry-run] would add lap_history.gap column")
                return (total, 0)
            conn.execute('ALTER TABLE lap_history ADD COLUMN gap TEXT')

        missing = conn.execute(
            "SELECT COUNT(*) FROM lap_history WHERE gap IS NULL OR gap = ''"
        ).fetchone()[0]
        if missing == 0:
            return (0, 0)
        if dry_run:
            return (missing, 0)

        cursor = conn.execute(BACKFILL_SQL)
        updated = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        conn.commit()
        return (missing, updated)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('databases', nargs='*', help='track DB paths (default: race_data_track_*.db)')
    parser.add_argument('--dry-run', action='store_true', help='report what would change, write nothing')
    args = parser.parse_args(argv)

    paths = args.databases or sorted(glob.glob('race_data_track_*.db'))
    if not paths:
        print('No databases found (expected race_data_track_*.db in the current directory).', file=sys.stderr)
        return 1

    total_missing = total_updated = 0
    for path in paths:
        if not os.path.exists(path):
            print(f"skip {path}: not found", file=sys.stderr)
            continue
        start = time.time()
        try:
            missing, updated = backfill_db(path, dry_run=args.dry_run)
        except sqlite3.Error as exc:
            print(f"FAIL {path}: {exc}", file=sys.stderr)
            continue
        total_missing += missing
        total_updated += updated
        elapsed = time.time() - start
        if args.dry_run:
            print(f"{path}: {missing} lap(s) missing a gap ({elapsed:.1f}s)")
        else:
            print(f"{path}: filled {updated}/{missing} ({elapsed:.1f}s)")

    verb = 'would fill' if args.dry_run else 'filled'
    print(f"\nDone. {verb} {total_missing if args.dry_run else total_updated} row(s) across {len(paths)} database(s).")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
