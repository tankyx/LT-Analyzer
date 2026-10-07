#!/usr/bin/env python3
"""Retroactive lap_times dedup: delete rows the 2026-05-26 write-dedup would
never have written.

The live parser only INSERTs a lap_times row when (position, last_lap,
best_lap, pit_stops) changed for that (session_id, kart_number), keeping the
first sighting as a baseline (multi_track_manager.py store_lap_data). Data
written before that fix is a per-tick snapshot — hundreds of consecutive
identical rows per kart. This script applies the same rule retroactively:
within each (session_id, kart_number), ordered by (timestamp, id), delete
every row whose four dedup fields equal the previous row's.

Preserved by construction:
 - every distinct (session, kart, best_lap) combination — the row where a
   value first changed always survives, so MIN(timestamp) per best-lap value
   (used for best_lap_timestamp in /top-teams) is unchanged;
 - session lists, kart lists, first/last rows per kart.
Deleted rows can differ only in gap/RunTime/timestamp — the same fields the
live write-dedup already discards.

Safe on a LIVE database: the dup scan is a WAL snapshot read; deletes run in
short batches so parser writes interleave. VACUUM (the actual space reclaim)
is NOT run here unless --vacuum is passed — run it when the track is quiet.

Usage:
    python scripts/retro_dedup_lap_times.py --db race_data_track_10.db \
        [--dry-run] [--batch 200000] [--vacuum]
"""

import argparse
import os
import sqlite3
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--batch', type=int, default=200000)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--vacuum', action='store_true')
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f'no such file: {args.db}')

    conn = sqlite3.connect(args.db, timeout=30.0)
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA temp_store=FILE')

    t0 = time.time()
    before = conn.execute('SELECT COUNT(*) FROM lap_times').fetchone()[0]
    print(f'{args.db}: {before:,} lap_times rows; scanning for redundant rows...')

    # Invariant fingerprints (cheap-ish, one pass each over the table).
    inv_before = {
        'sessions': conn.execute(
            'SELECT COUNT(DISTINCT session_id) FROM lap_times').fetchone()[0],
        'session_karts': conn.execute(
            'SELECT COUNT(*) FROM (SELECT DISTINCT session_id, kart_number FROM lap_times)'
        ).fetchone()[0],
        'best_lap_triples': conn.execute(
            'SELECT COUNT(*) FROM (SELECT DISTINCT session_id, kart_number, best_lap FROM lap_times)'
        ).fetchone()[0],
    }

    conn.execute('''
        CREATE TEMP TABLE dups AS
        SELECT id FROM (
            SELECT id,
                   position   IS LAG(position)   OVER w AS same_pos,
                   last_lap   IS LAG(last_lap)   OVER w AS same_ll,
                   best_lap   IS LAG(best_lap)   OVER w AS same_bl,
                   pit_stops  IS LAG(pit_stops)  OVER w AS same_ps,
                   LAG(id) OVER w AS prev_id
            FROM lap_times
            WINDOW w AS (PARTITION BY session_id, kart_number ORDER BY timestamp, id)
        )
        WHERE prev_id IS NOT NULL
          AND same_pos AND same_ll AND same_bl AND same_ps
    ''')
    dup_count = conn.execute('SELECT COUNT(*) FROM dups').fetchone()[0]
    print(f'  redundant rows: {dup_count:,} of {before:,} '
          f'({100.0 * dup_count / max(before, 1):.1f}%)  '
          f'[scan took {time.time() - t0:.0f}s]')

    if args.dry_run or dup_count == 0:
        conn.close()
        return

    conn.execute('CREATE INDEX temp.idx_dups ON dups(id)')
    deleted = 0
    while True:
        batch = [r[0] for r in conn.execute(
            f'SELECT id FROM dups LIMIT {args.batch}').fetchall()]
        if not batch:
            break
        with conn:  # one short write transaction per batch
            conn.executemany('DELETE FROM lap_times WHERE id = ?',
                             ((i,) for i in batch))
            conn.executemany('DELETE FROM dups WHERE id = ?',
                             ((i,) for i in batch))
        deleted += len(batch)
        # Keep the WAL bounded; PASSIVE never blocks the live parser.
        conn.execute('PRAGMA wal_checkpoint(PASSIVE)')
        print(f'  deleted {deleted:,}/{dup_count:,} '
              f'({time.time() - t0:.0f}s elapsed)', flush=True)

    after = conn.execute('SELECT COUNT(*) FROM lap_times').fetchone()[0]
    inv_after = {
        'sessions': conn.execute(
            'SELECT COUNT(DISTINCT session_id) FROM lap_times').fetchone()[0],
        'session_karts': conn.execute(
            'SELECT COUNT(*) FROM (SELECT DISTINCT session_id, kart_number FROM lap_times)'
        ).fetchone()[0],
        'best_lap_triples': conn.execute(
            'SELECT COUNT(*) FROM (SELECT DISTINCT session_id, kart_number, best_lap FROM lap_times)'
        ).fetchone()[0],
    }
    print(f'  rows: {before:,} -> {after:,}')
    ok = True
    for key, b in inv_before.items():
        a = inv_after[key]
        # New live rows may ADD sessions/karts/values while we run; they must
        # never DECREASE.
        status = 'OK' if a >= b else 'VIOLATION'
        if a < b:
            ok = False
        print(f'  invariant {key}: {b:,} -> {a:,}  {status}')
    if not ok:
        sys.exit('INVARIANT VIOLATION — restore from backup and investigate')

    if args.vacuum:
        print('  vacuuming...')
        t1 = time.time()
        conn.execute('VACUUM')
        print(f'  vacuum done in {time.time() - t1:.0f}s')
    conn.close()
    print(f'done in {time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
