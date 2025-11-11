#!/usr/bin/env python3
"""
Script to split lap_times data into sessions by detecting:
1. Session starts: When leader goes to "Tour 1" / "Lap 1"
2. Session ends: When lap progression stops (same lap for >5 minutes)
3. Uses time gaps as fallback for data without lap counters
"""

import sqlite3
from datetime import datetime, timedelta
import sys

def get_track_db_connection(track_id):
    """Get database connection for a specific track"""
    db_path = f'/home/ubuntu/LT-Analyzer/race_data_track_{track_id}.db'
    return sqlite3.connect(db_path)

def find_lap_based_sessions(cursor, stale_lap_minutes=2):
    """
    Find sessions by analyzing lap counter progression.
    A session ends when the lap number doesn't change for > stale_lap_minutes.
    The session end time is estimated as (last_lap_start + typical_lap_duration).

    Returns list of (start_time, end_time) tuples.
    """
    # Get all lap numbers from leader over time
    cursor.execute("""
        SELECT DISTINCT
            timestamp,
            CASE
                WHEN gap LIKE 'Tour %' THEN CAST(SUBSTR(gap, 6) AS INTEGER)
                WHEN gap LIKE 'Lap %' THEN CAST(SUBSTR(gap, 5) AS INTEGER)
                ELSE NULL
            END as lap_number
        FROM lap_times
        WHERE position = 1
            AND (gap LIKE 'Tour %' OR gap LIKE 'Lap %')
        ORDER BY timestamp
    """)

    lap_data = [(row[0], row[1]) for row in cursor.fetchall() if row[1] is not None]

    if not lap_data:
        return []

    sessions = []
    current_session_start = None
    current_lap = None
    last_lap_change = None
    lap_change_times = []  # Track when laps change to calculate average lap duration

    for timestamp, lap_number in lap_data:
        ts = datetime.fromisoformat(timestamp)

        # Detect session start (lap resets to 1)
        if lap_number == 1 and (current_lap is None or current_lap > 1):
            # If we had a previous session, close it
            if current_session_start and last_lap_change:
                # Calculate average lap duration from lap changes
                if len(lap_change_times) >= 2:
                    durations = [(lap_change_times[i+1] - lap_change_times[i]).total_seconds()
                                for i in range(len(lap_change_times)-1)]
                    avg_lap_seconds = sum(durations) / len(durations)
                    # Estimate session end as last lap start + 30% of average lap duration
                    # (race likely ended before the last lap was fully completed)
                    estimated_end = datetime.fromisoformat(last_lap_change) + timedelta(seconds=avg_lap_seconds * 0.3)
                    sessions.append((current_session_start, estimated_end.isoformat()))
                else:
                    # Fallback: use last lap change time + 60 seconds
                    estimated_end = datetime.fromisoformat(last_lap_change) + timedelta(seconds=60)
                    sessions.append((current_session_start, estimated_end.isoformat()))

            # Start new session
            current_session_start = timestamp
            current_lap = 1
            last_lap_change = timestamp
            lap_change_times = [ts]
            continue

        # Track lap progression
        if lap_number != current_lap:
            current_lap = lap_number
            last_lap_change = timestamp
            lap_change_times.append(ts)
        else:
            # Same lap number - check if it's been stale for too long
            if last_lap_change:
                time_on_same_lap = (ts - datetime.fromisoformat(last_lap_change)).total_seconds() / 60

                # If lap has been stuck for > threshold, session ended
                if time_on_same_lap > stale_lap_minutes and current_session_start:
                    # Calculate average lap duration
                    if len(lap_change_times) >= 2:
                        durations = [(lap_change_times[i+1] - lap_change_times[i]).total_seconds()
                                    for i in range(len(lap_change_times)-1)]
                        avg_lap_seconds = sum(durations) / len(durations)
                        # Estimate session end as last lap start + 30% of average lap duration
                        estimated_end = datetime.fromisoformat(last_lap_change) + timedelta(seconds=avg_lap_seconds * 0.3)
                        sessions.append((current_session_start, estimated_end.isoformat()))
                    else:
                        # Fallback: use last lap change time + 60 seconds
                        estimated_end = datetime.fromisoformat(last_lap_change) + timedelta(seconds=60)
                        sessions.append((current_session_start, estimated_end.isoformat()))

                    current_session_start = None
                    current_lap = None
                    last_lap_change = None
                    lap_change_times = []

    # Close final session if still open
    if current_session_start and last_lap_change:
        if len(lap_change_times) >= 2:
            durations = [(lap_change_times[i+1] - lap_change_times[i]).total_seconds()
                        for i in range(len(lap_change_times)-1)]
            avg_lap_seconds = sum(durations) / len(durations)
            estimated_end = datetime.fromisoformat(last_lap_change) + timedelta(seconds=avg_lap_seconds * 0.3)
            sessions.append((current_session_start, estimated_end.isoformat()))
        else:
            estimated_end = datetime.fromisoformat(last_lap_change) + timedelta(seconds=60)
            sessions.append((current_session_start, estimated_end.isoformat()))

    return sessions

def find_time_gap_sessions(cursor, start_time=None, end_time=None, gap_threshold_minutes=3):
    """
    Find sessions based on time gaps and activity levels.
    Optionally limit to a specific time range.
    Uses minute-by-minute activity to detect racing sessions vs breaks.
    """
    if start_time and end_time:
        cursor.execute("""
            SELECT substr(timestamp, 1, 16) as minute,
                   MIN(timestamp) as first_ts,
                   MAX(timestamp) as last_ts,
                   COUNT(*) as record_count
            FROM lap_times
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY minute
            ORDER BY minute
        """, (start_time, end_time))
    else:
        cursor.execute("""
            SELECT substr(timestamp, 1, 16) as minute,
                   MIN(timestamp) as first_ts,
                   MAX(timestamp) as last_ts,
                   COUNT(*) as record_count
            FROM lap_times
            GROUP BY minute
            ORDER BY minute
        """)

    minute_data = cursor.fetchall()

    if not minute_data:
        return []

    sessions = []
    current_session_start = None
    last_active_minute = None

    # Activity threshold: >50 records/minute = active racing
    ACTIVITY_THRESHOLD = 50

    for minute, first_ts, last_ts, count in minute_data:
        is_active = count > ACTIVITY_THRESHOLD

        if is_active:
            if current_session_start is None:
                # Start new session
                current_session_start = first_ts
                last_active_minute = last_ts
            else:
                # Continue session
                last_active_minute = last_ts
        else:
            # Low activity minute
            if current_session_start and last_active_minute:
                # Check if we should end the session
                curr_time = datetime.fromisoformat(first_ts)
                last_time = datetime.fromisoformat(last_active_minute)
                gap_minutes = (curr_time - last_time).total_seconds() / 60

                if gap_minutes >= gap_threshold_minutes:
                    # End session
                    sessions.append((current_session_start, last_active_minute))
                    current_session_start = None
                    last_active_minute = None

    # Close final session if still open
    if current_session_start and last_active_minute:
        sessions.append((current_session_start, last_active_minute))

    return sessions

def find_uncovered_ranges(cursor, lap_based_sessions):
    """Find time ranges not covered by lap-based sessions"""
    if not lap_based_sessions:
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM lap_times")
        result = cursor.fetchone()
        if result[0] and result[1]:
            return [(result[0], result[1])]
        return []

    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM lap_times")
    overall_start, overall_end = cursor.fetchone()

    if not overall_start or not overall_end:
        return []

    uncovered = []

    # Before first lap session
    first_lap_start = lap_based_sessions[0][0]
    if overall_start < first_lap_start:
        cursor.execute("""
            SELECT MAX(timestamp)
            FROM lap_times
            WHERE timestamp < ?
        """, (first_lap_start,))
        end_before = cursor.fetchone()[0]
        if end_before:
            uncovered.append((overall_start, end_before))

    # Gaps between lap sessions
    for i in range(len(lap_based_sessions) - 1):
        current_end = lap_based_sessions[i][1]
        next_start = lap_based_sessions[i + 1][0]

        cursor.execute("""
            SELECT MIN(timestamp), MAX(timestamp)
            FROM lap_times
            WHERE timestamp > ? AND timestamp < ?
        """, (current_end, next_start))
        gap_start, gap_end = cursor.fetchone()

        if gap_start and gap_end:
            uncovered.append((gap_start, gap_end))

    # After last lap session
    last_lap_end = lap_based_sessions[-1][1]
    if overall_end > last_lap_end:
        cursor.execute("""
            SELECT MIN(timestamp)
            FROM lap_times
            WHERE timestamp > ?
        """, (last_lap_end,))
        start_after = cursor.fetchone()[0]
        if start_after:
            uncovered.append((start_after, overall_end))

    return uncovered

def find_all_sessions(cursor):
    """
    Find all sessions using activity-based detection.
    Primary method: Activity patterns (high records/minute = racing)
    Secondary: Lap progression data where available
    """
    print("\n🔍 Finding sessions (activity-based detection)...")

    # Use activity-based detection with 3-minute gap threshold
    activity_sessions = find_time_gap_sessions(cursor, gap_threshold_minutes=3)

    if not activity_sessions:
        print("   ❌ No sessions found!")
        return []

    print(f"   ✓ {len(activity_sessions)} sessions detected from activity patterns")

    all_sessions = []
    for start, end in activity_sessions:
        all_sessions.append((start, end, 'activity'))

    print(f"\n✅ Total: {len(all_sessions)} sessions:")
    for idx, (start, end, method) in enumerate(all_sessions, 1):
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        duration = end_dt - start_dt
        print(f"   🏁 Session {idx}: {start} to {end} (duration: {duration}, method: {method})")

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
    """Create session records in race_sessions table"""
    print("\n📝 Creating session records...")

    cursor.execute("DELETE FROM race_sessions")
    print("   Cleared existing sessions")

    session_map = {}

    for idx, (start_time, end_time, method) in enumerate(sessions, 1):
        start_dt = datetime.fromisoformat(start_time)
        session_name = f"{track_name} - {start_dt.strftime('%Y-%m-%d %H:%M')}"

        stats = get_session_stats(cursor, start_time, end_time)
        records, teams, first_ts, last_ts = stats

        cursor.execute("""
            INSERT INTO race_sessions (start_time, name, track)
            VALUES (?, ?, ?)
        """, (start_time, session_name, track_name))

        session_id = cursor.lastrowid
        session_map[(start_time, end_time)] = session_id

        icon = "🏁" if method == 'lap_progression' else "⏱️"
        duration = datetime.fromisoformat(last_ts) - datetime.fromisoformat(first_ts)
        print(f"   {icon} Session {session_id}: {session_name}")
        print(f"      Records: {records}, Teams: {teams}, Duration: {duration}")

    return session_map

def update_lap_times(cursor, session_map):
    """Update lap_times with session IDs"""
    print("\n🔄 Updating lap_times with session IDs...")

    cursor.execute("UPDATE lap_times SET session_id = NULL")
    print("   Cleared all existing session IDs")

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

    cursor.execute("SELECT COUNT(*) FROM lap_times WHERE session_id IS NULL")
    unassigned = cursor.fetchone()[0]

    if unassigned > 0:
        print(f"\n   ⚠️  WARNING: {unassigned} records not assigned")
    else:
        print(f"\n   ✓ All records assigned to sessions")

    print(f"\n✅ Total records updated: {total_updated}")
    return total_updated

def split_track_sessions(track_id, track_name, dry_run=False):
    """Main function to split sessions for a track"""
    print(f"\n{'='*60}")
    print(f"🏁 Processing Track {track_id}: {track_name}")
    print(f"{'='*60}")

    conn = get_track_db_connection(track_id)
    cursor = conn.cursor()

    try:
        sessions = find_all_sessions(cursor)

        if not sessions:
            print("❌ No sessions found!")
            return

        session_map = create_sessions(cursor, sessions, track_name)
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

    parser = argparse.ArgumentParser(description='Split racing data into sessions')
    parser.add_argument('--track-id', type=int, help='Process specific track ID')
    parser.add_argument('--dry-run', action='store_true', help='Analyze without committing')
    parser.add_argument('--all', action='store_true', help='Process all tracks')

    args = parser.parse_args()

    print("🏎️  LT-Analyzer Session Splitter (Final)")
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
