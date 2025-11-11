#!/usr/bin/env python3
"""
Script to split lap_times data into separate sessions based on lap counter resets.
A new session starts when the leader goes back to lap 1 (Tour 1 / Lap 1).
"""

import sqlite3
from datetime import datetime, timedelta
import sys

def get_track_db_connection(track_id):
    """Get database connection for a specific track"""
    db_path = f'/home/ubuntu/LT-Analyzer/race_data_track_{track_id}.db'
    return sqlite3.connect(db_path)

def find_lap_one_occurrences(cursor):
    """
    Find all timestamps where the leader (position=1) is on lap 1.
    Returns list of timestamps.
    """
    cursor.execute("""
        SELECT DISTINCT timestamp
        FROM lap_times
        WHERE position = 1
            AND (gap LIKE 'Tour 1' OR gap LIKE 'Lap 1')
        ORDER BY timestamp
    """)

    return [row[0] for row in cursor.fetchall()]

def group_lap_one_timestamps(timestamps, max_gap_seconds=300):
    """
    Group consecutive "lap 1" timestamps that are close together (same session start).
    Returns list of (first_timestamp_in_group) representing session starts.

    Args:
        timestamps: List of ISO timestamp strings
        max_gap_seconds: Max gap to consider part of same session start (default: 5 minutes)
    """
    if not timestamps:
        return []

    session_starts = []
    current_group_start = timestamps[0]

    for i in range(1, len(timestamps)):
        prev_time = datetime.fromisoformat(timestamps[i-1])
        curr_time = datetime.fromisoformat(timestamps[i])
        gap_seconds = (curr_time - prev_time).total_seconds()

        # If gap is larger than threshold, previous group ended, new group starts
        if gap_seconds > max_gap_seconds:
            session_starts.append(current_group_start)
            current_group_start = timestamps[i]

    # Add the final group
    session_starts.append(current_group_start)

    return session_starts

def find_time_gap_sessions(cursor, gap_threshold_minutes=120):
    """
    Fallback: Find sessions based on time gaps (for data without lap counters).
    Returns list of (start_time, end_time) tuples.
    """
    print(f"\n   ⚠️  No lap counter data - using time gap method (threshold: {gap_threshold_minutes} min)...")

    # Get all distinct timestamps ordered
    cursor.execute("""
        SELECT DISTINCT timestamp
        FROM lap_times
        ORDER BY timestamp
    """)

    timestamps = [row[0] for row in cursor.fetchall()]

    if not timestamps:
        return []

    # Find session boundaries based on time gaps
    sessions = []
    current_session_start = timestamps[0]

    for i in range(1, len(timestamps)):
        prev_time = datetime.fromisoformat(timestamps[i-1])
        curr_time = datetime.fromisoformat(timestamps[i])
        gap_minutes = (curr_time - prev_time).total_seconds() / 60

        # If gap is larger than threshold, start new session
        if gap_minutes > gap_threshold_minutes:
            sessions.append((current_session_start, timestamps[i-1]))
            current_session_start = timestamps[i]

    # Add the final session
    sessions.append((current_session_start, timestamps[-1]))

    return sessions

def find_uncovered_ranges(cursor, lap_based_sessions):
    """
    Find time ranges that are NOT covered by lap-based sessions.
    Returns list of (start_time, end_time) tuples for uncovered ranges.
    """
    if not lap_based_sessions:
        # No lap-based sessions, entire database is uncovered
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM lap_times")
        result = cursor.fetchone()
        if result[0] and result[1]:
            return [(result[0], result[1])]
        return []

    # Get overall data range
    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM lap_times")
    overall_start, overall_end = cursor.fetchone()

    if not overall_start or not overall_end:
        return []

    uncovered = []

    # Check if there's data before first lap-based session
    first_lap_session_start = lap_based_sessions[0][0]
    if overall_start < first_lap_session_start:
        # Get last timestamp before first lap session
        cursor.execute("""
            SELECT MAX(timestamp)
            FROM lap_times
            WHERE timestamp < ?
        """, (first_lap_session_start,))
        end_before = cursor.fetchone()[0]
        if end_before:
            uncovered.append((overall_start, end_before))

    # Check gaps between lap-based sessions
    for i in range(len(lap_based_sessions) - 1):
        current_end = lap_based_sessions[i][1]
        next_start = lap_based_sessions[i + 1][0]

        # Check if there's a significant gap with data
        cursor.execute("""
            SELECT MIN(timestamp), MAX(timestamp)
            FROM lap_times
            WHERE timestamp > ? AND timestamp < ?
        """, (current_end, next_start))
        gap_start, gap_end = cursor.fetchone()

        if gap_start and gap_end:
            uncovered.append((gap_start, gap_end))

    # Check if there's data after last lap-based session
    last_lap_session_end = lap_based_sessions[-1][1]
    if overall_end > last_lap_session_end:
        # Get first timestamp after last lap session
        cursor.execute("""
            SELECT MIN(timestamp)
            FROM lap_times
            WHERE timestamp > ?
        """, (last_lap_session_end,))
        start_after = cursor.fetchone()[0]
        if start_after:
            uncovered.append((start_after, overall_end))

    return uncovered

def split_range_by_time_gaps(cursor, start_time, end_time, gap_threshold_minutes=120):
    """
    Split a specific time range into sessions based on time gaps.
    Returns list of (start_time, end_time) tuples.
    """
    cursor.execute("""
        SELECT DISTINCT timestamp
        FROM lap_times
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp
    """, (start_time, end_time))

    timestamps = [row[0] for row in cursor.fetchall()]

    if not timestamps:
        return []

    sessions = []
    current_session_start = timestamps[0]

    for i in range(1, len(timestamps)):
        prev_time = datetime.fromisoformat(timestamps[i-1])
        curr_time = datetime.fromisoformat(timestamps[i])
        gap_minutes = (curr_time - prev_time).total_seconds() / 60

        if gap_minutes > gap_threshold_minutes:
            sessions.append((current_session_start, timestamps[i-1]))
            current_session_start = timestamps[i]

    # Add final session
    sessions.append((current_session_start, timestamps[-1]))

    return sessions

def find_session_boundaries(cursor):
    """
    Find session boundaries using hybrid approach:
    1. Use lap counter resets where available
    2. Use time gaps for data without lap counters
    Returns list of (start_time, end_time, method) tuples for each session.
    """
    print("\n🔍 Finding session boundaries (hybrid approach)...")

    # Step 1: Find lap-based sessions
    lap_one_times = find_lap_one_occurrences(cursor)
    lap_based_sessions = []

    if lap_one_times:
        print(f"   Found {len(lap_one_times)} 'lap 1' records")

        session_starts = group_lap_one_timestamps(lap_one_times, max_gap_seconds=300)
        print(f"   Detected {len(session_starts)} lap-based session starts")

        for i in range(len(session_starts)):
            start_time = session_starts[i]

            if i + 1 < len(session_starts):
                next_start = session_starts[i + 1]
                cursor.execute("""
                    SELECT MAX(timestamp)
                    FROM lap_times
                    WHERE timestamp < ?
                """, (next_start,))
                end_time = cursor.fetchone()[0]
            else:
                cursor.execute("SELECT MAX(timestamp) FROM lap_times")
                end_time = cursor.fetchone()[0]

            if end_time:
                lap_based_sessions.append((start_time, end_time, 'lap_counter'))

        print(f"   ✓ {len(lap_based_sessions)} sessions from lap counter resets")

    # Step 2: Find uncovered ranges and split by time gaps
    uncovered_ranges = find_uncovered_ranges(cursor, lap_based_sessions)
    time_based_sessions = []

    if uncovered_ranges:
        print(f"   Found {len(uncovered_ranges)} uncovered time range(s)")

        for start, end in uncovered_ranges:
            range_sessions = split_range_by_time_gaps(cursor, start, end, gap_threshold_minutes=120)
            for session_start, session_end in range_sessions:
                time_based_sessions.append((session_start, session_end, 'time_gap'))

        print(f"   ✓ {len(time_based_sessions)} sessions from time gaps")

    # Combine and sort all sessions
    all_sessions = lap_based_sessions + time_based_sessions
    all_sessions.sort(key=lambda x: x[0])  # Sort by start time

    if not all_sessions:
        print("   ❌ No sessions found!")
        return []

    print(f"\n✅ Total: {len(all_sessions)} sessions:")
    for idx, (start, end, method) in enumerate(all_sessions, 1):
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        duration = end_dt - start_dt
        method_icon = "🏁" if method == 'lap_counter' else "⏱️"
        print(f"   {method_icon} Session {idx}: {start} to {end} (duration: {duration}, method: {method})")

    return all_sessions

def get_session_stats(cursor, start_time, end_time):
    """Get statistics for a session time range"""
    cursor.execute("""
        SELECT
            COUNT(*) as records,
            COUNT(DISTINCT team_name) as teams,
            MIN(timestamp) as first_ts,
            MAX(timestamp) as last_ts
        FROM lap_times
        WHERE timestamp >= ? AND timestamp <= ?
    """, (start_time, end_time))

    return cursor.fetchone()

def create_sessions(cursor, sessions, track_name):
    """
    Create session records in race_sessions table.
    Returns mapping of (start_time, end_time) -> session_id
    """
    print("\n📝 Creating session records...")

    # Clear existing sessions
    cursor.execute("DELETE FROM race_sessions")
    print("   Cleared existing sessions")

    session_map = {}

    for idx, (start_time, end_time, method) in enumerate(sessions, 1):
        start_dt = datetime.fromisoformat(start_time)

        # Generate session name based on date and time
        session_name = f"{track_name} - {start_dt.strftime('%Y-%m-%d %H:%M')}"

        # Get stats for this session
        stats = get_session_stats(cursor, start_time, end_time)
        records, teams, first_ts, last_ts = stats

        # Insert session
        cursor.execute("""
            INSERT INTO race_sessions (start_time, name, track)
            VALUES (?, ?, ?)
        """, (start_time, session_name, track_name))

        session_id = cursor.lastrowid
        session_map[(start_time, end_time)] = session_id

        method_icon = "🏁" if method == 'lap_counter' else "⏱️"
        print(f"   {method_icon} Session {session_id}: {session_name}")
        print(f"      Records: {records}, Teams: {teams}, Duration: {datetime.fromisoformat(last_ts) - datetime.fromisoformat(first_ts)}")

    return session_map

def update_lap_times(cursor, session_map):
    """Update lap_times records with correct session_id"""
    print("\n🔄 Updating lap_times with session IDs...")

    # First, clear all session_ids
    cursor.execute("UPDATE lap_times SET session_id = NULL")
    print(f"   Cleared all existing session IDs")

    total_updated = 0

    for (start_time, end_time), session_id in session_map.items():
        cursor.execute("""
            UPDATE lap_times
            SET session_id = ?
            WHERE timestamp >= ? AND timestamp <= ?
        """, (session_id, start_time, end_time))

        updated = cursor.rowcount
        total_updated += updated
        print(f"   ✓ Session {session_id}: Updated {updated} records")

    # Count records without session_id
    cursor.execute("SELECT COUNT(*) FROM lap_times WHERE session_id IS NULL")
    unassigned = cursor.fetchone()[0]

    if unassigned > 0:
        print(f"\n   ⚠️  WARNING: {unassigned} records not assigned to any session")
    else:
        print(f"\n   ✓ All records assigned to sessions")

    print(f"\n✅ Total records updated: {total_updated}")
    return total_updated

def split_track_sessions(track_id, track_name, dry_run=False):
    """
    Main function to split sessions for a track based on lap counter resets.

    Args:
        track_id: Track database ID
        track_name: Name of the track
        dry_run: If True, don't commit changes
    """
    print(f"\n{'='*60}")
    print(f"🏁 Processing Track {track_id}: {track_name}")
    print(f"{'='*60}")

    conn = get_track_db_connection(track_id)
    cursor = conn.cursor()

    try:
        # Find sessions based on lap counter resets
        sessions = find_session_boundaries(cursor)

        if not sessions:
            print("❌ No sessions found! (No lap counter data)")
            return

        if len(sessions) == 1:
            print("ℹ️  Only one session found")

        # Create session records
        session_map = create_sessions(cursor, sessions, track_name)

        # Update lap_times
        total_updated = update_lap_times(cursor, session_map)

        if dry_run:
            print("\n⚠️  DRY RUN - Rolling back changes")
            conn.rollback()
        else:
            print("\n💾 Committing changes...")
            conn.commit()
            print("✅ Done!")

        return sessions

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise
    finally:
        conn.close()

def get_all_tracks():
    """Get all tracks from tracks.db"""
    conn = sqlite3.connect('/home/ubuntu/LT-Analyzer/tracks.db')
    cursor = conn.cursor()

    cursor.execute("SELECT id, track_name FROM tracks ORDER BY id")
    tracks = cursor.fetchall()

    conn.close()
    return tracks

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Split racing data into sessions based on lap counter resets')
    parser.add_argument('--track-id', type=int, help='Process specific track ID only')
    parser.add_argument('--dry-run', action='store_true',
                       help='Analyze and show what would be done without committing')
    parser.add_argument('--all', action='store_true',
                       help='Process all tracks')

    args = parser.parse_args()

    print("🏎️  LT-Analyzer Session Splitter (Lap-Based)")
    print("="*60)

    if args.all:
        tracks = get_all_tracks()
        print(f"\n📋 Processing {len(tracks)} tracks...")

        for track_id, track_name in tracks:
            try:
                split_track_sessions(track_id, track_name, args.dry_run)
            except Exception as e:
                print(f"❌ Failed to process track {track_id}: {e}")
                continue

    elif args.track_id:
        # Get track name
        conn = sqlite3.connect('/home/ubuntu/LT-Analyzer/tracks.db')
        cursor = conn.cursor()
        cursor.execute("SELECT track_name FROM tracks WHERE id = ?", (args.track_id,))
        result = cursor.fetchone()
        conn.close()

        if not result:
            print(f"❌ Track ID {args.track_id} not found!")
            sys.exit(1)

        track_name = result[0]
        split_track_sessions(args.track_id, track_name, args.dry_run)

    else:
        print("❌ Please specify --track-id <id> or --all")
        parser.print_help()
        sys.exit(1)

    print("\n" + "="*60)
    print("✅ Session splitting complete!")

if __name__ == '__main__':
    main()
