#!/usr/bin/env python3
"""
Recover sprint races from sessions corrupted by the parser-merge bug.

For each excluded session in race_sessions, scan lap_times in chronological
order and detect bursts of new lap data — each burst corresponds to one real
race. Reassign lap_times (and lap_history) rows from the merged session_id
to fresh session_ids, one per detected burst.

Usage:
  python recover_merged_sessions.py --track 1 --preview
  python recover_merged_sessions.py --track 1 --apply
  python recover_merged_sessions.py --track 1 --apply --session 170
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timedelta

# Tunables — calibrated for sprint formats (10–25 min races, 30+ drivers).
ACTIVE_THRESHOLD = 5    # new (team, last_lap) pairs per minute to count as "racing"
IDLE_RUN = 3            # consecutive idle minutes that close a burst
MIN_BURST_MINS = 5      # discard fragments shorter than this


def detect_bursts(rows):
    """Walk chronological lap_times rows. Yield (start_ts, end_ts) for each burst.

    rows: list of (timestamp, team_name, last_lap), already sorted by timestamp.
    """
    if not rows:
        return []

    # Per-minute novelty: count new (team, last_lap) pairs first seen that minute.
    seen = set()
    minute_new_count = {}
    minute_first_ts = {}
    minute_last_ts = {}
    for ts, team, lap in rows:
        if not team or not lap:
            continue
        m = ts[:16]  # 'YYYY-MM-DDTHH:MM'
        pair = (team, lap)
        if pair not in seen:
            seen.add(pair)
            minute_new_count[m] = minute_new_count.get(m, 0) + 1
        if m not in minute_first_ts:
            minute_first_ts[m] = ts
        minute_last_ts[m] = ts

    if not minute_new_count:
        return []

    # Walk minutes contiguously between first and last; missing minutes count
    # as idle (parser was offline).
    minutes_with_data = sorted(minute_new_count.keys())
    first = datetime.fromisoformat(minutes_with_data[0])
    last = datetime.fromisoformat(minutes_with_data[-1])

    bursts = []
    current = None  # {'start_min': str, 'last_active_min': str, 'idle': int}
    cur = first
    while cur <= last:
        m_str = cur.strftime('%Y-%m-%dT%H:%M')
        active = minute_new_count.get(m_str, 0) >= ACTIVE_THRESHOLD
        if active:
            if current is None:
                current = {'start_min': m_str, 'last_active_min': m_str, 'idle': 0}
            else:
                current['last_active_min'] = m_str
                current['idle'] = 0
        else:
            if current is not None:
                current['idle'] += 1
                if current['idle'] >= IDLE_RUN:
                    bursts.append(_finalize_burst(current, minute_first_ts, minute_last_ts))
                    current = None
        cur += timedelta(minutes=1)
    if current is not None:
        bursts.append(_finalize_burst(current, minute_first_ts, minute_last_ts))

    # Apply minimum-duration filter
    return [b for b in bursts if b is not None and b[2] >= MIN_BURST_MINS]


def _finalize_burst(state, first_ts, last_ts):
    start = first_ts.get(state['start_min'], state['start_min'])
    end = last_ts.get(state['last_active_min'], state['last_active_min'])
    try:
        dur_min = (datetime.fromisoformat(state['last_active_min'])
                   - datetime.fromisoformat(state['start_min'])).total_seconds() / 60 + 1
    except Exception:
        dur_min = 0
    return (start, end, dur_min)


def get_excluded_sessions(conn):
    return conn.execute("""
        SELECT session_id, name, track FROM race_sessions
        WHERE is_excluded = 1
        ORDER BY session_id ASC
    """).fetchall()


def fetch_session_rows(conn, session_id):
    return conn.execute("""
        SELECT timestamp, team_name, last_lap FROM lap_times
        WHERE session_id = ?
          AND last_lap IS NOT NULL AND last_lap != ''
          AND team_name IS NOT NULL AND team_name != ''
        ORDER BY timestamp ASC
    """, (session_id,)).fetchall()


def apply_recovery(conn, source_sid, source_name, track_name, bursts):
    """Create one new session per burst and reassign rows."""
    cur = conn.cursor()
    created = []
    for start_ts, end_ts, dur_min in bursts:
        new_name = f'{track_name} - {start_ts[:16].replace("T", " ")} (recovered #{source_sid})'
        cur.execute('''
            INSERT INTO race_sessions (start_time, name, track, layout_id, is_excluded)
            VALUES (?, ?, ?, NULL, 0)
        ''', (start_ts, new_name, track_name))
        new_sid = cur.lastrowid
        cur.execute('''
            UPDATE lap_times SET session_id = ?
            WHERE session_id = ? AND timestamp BETWEEN ? AND ?
        ''', (new_sid, source_sid, start_ts, end_ts))
        lt = cur.rowcount
        cur.execute('''
            UPDATE lap_history SET session_id = ?
            WHERE session_id = ? AND timestamp BETWEEN ? AND ?
        ''', (new_sid, source_sid, start_ts, end_ts))
        lh = cur.rowcount
        created.append({'sid': new_sid, 'start': start_ts, 'end': end_ts, 'dur': dur_min, 'lap_times_rows': lt, 'lap_history_rows': lh})
    conn.commit()
    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--track', type=int, required=True)
    ap.add_argument('--session', type=int, default=None, help='only operate on a single session_id')
    ap.add_argument('--preview', action='store_true', help='show what would happen, do not write')
    ap.add_argument('--apply', action='store_true', help='write changes (mutually exclusive with --preview)')
    args = ap.parse_args()
    if not (args.preview or args.apply):
        ap.error('pass --preview or --apply')
    if args.preview and args.apply:
        ap.error('--preview and --apply are mutually exclusive')

    db_path = f'race_data_track_{args.track}.db'
    with sqlite3.connect(db_path) as conn:
        excluded = get_excluded_sessions(conn)
        if args.session is not None:
            excluded = [e for e in excluded if e[0] == args.session]
        if not excluded:
            print(f'No excluded sessions to process on track {args.track}.')
            return
        print(f'Track {args.track}: {len(excluded)} excluded session(s) to process')
        total_recovered = 0
        for sid, name, track in excluded:
            rows = fetch_session_rows(conn, sid)
            bursts = detect_bursts(rows)
            print(f'\nsession #{sid} ({len(rows):>8} lap_times rows): detected {len(bursts)} burst(s)')
            for start, end, dur in bursts:
                print(f'    {start[:19]} → {end[:19]}   duration={dur:>6.1f}m')
            if args.apply and bursts:
                created = apply_recovery(conn, sid, name, track, bursts)
                for c in created:
                    print(f'    → created session #{c["sid"]}  '
                          f'lap_times rows reassigned: {c["lap_times_rows"]}, '
                          f'lap_history rows reassigned: {c["lap_history_rows"]}')
                total_recovered += len(created)
        if args.apply:
            print(f'\nTotal recovered sessions: {total_recovered}')


if __name__ == '__main__':
    main()
