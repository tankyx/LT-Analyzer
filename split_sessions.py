#!/usr/bin/env python3
"""
Script to split lap_times data into separate sessions based on time gaps.
Creates new session records and updates lap_times accordingly.
"""

import sqlite3
from datetime import datetime, timedelta
import sys

def get_track_db_connection(track_id):
    """Get database connection for a specific track"""
    db_path = f'/home/ubuntu/LT-Analyzer/race_data_track_{track_id}.db'
    return sqlite3.connect(db_path)

def analyze_time_gaps(cursor, gap_threshold_minutes=120):
    """
    Analyze timestamps to find natural session boundaries.
    Returns list of (start_time, end_time) tuples for each session.
    """
    print(f"\n🔍 Analyzing time gaps (threshold: {gap_threshold_minutes} minutes)...")

    # Get all distinct timestamps ordered
    cursor.execute("""
        SELECT DISTINCT timestamp
        FROM lap_times
        ORDER BY timestamp
    """)

    timestamps = [row[0] for row in cursor.fetchall()]

    if not timestamps:
        print("❌ No data found!")
        return []

    print(f"   Found {len(timestamps)} distinct timestamps")
    print(f"   First: {timestamps[0]}")
    print(f"   Last: {timestamps[-1]}")

    # Find session boundaries based on time gaps
    sessions = []
    current_session_start = timestamps[0]

    for i in range(1, len(timestamps)):
        prev_time = datetime.fromisoformat(timestamps[i-1])
        curr_time = datetime.fromisoformat(timestamps[i])
        gap_minutes = (curr_time - prev_time).total_seconds() / 60

        # If gap is larger than threshold, start new session
        if gap_minutes > gap_threshold_minutes:
            # Close previous session
            sessions.append((current_session_start, timestamps[i-1]))
            print(f"   📅 Session boundary found: {gap_minutes:.0f} minute gap")
            print(f"      Session ended: {timestamps[i-1]}")
            print(f"      New session starts: {timestamps[i]}")

            # Start new session
            current_session_start = timestamps[i]

    # Add the final session
    sessions.append((current_session_start, timestamps[-1]))

    print(f"\n✅ Found {len(sessions)} sessions:")
    for idx, (start, end) in enumerate(sessions, 1):
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        duration = end_dt - start_dt
        print(f"   Session {idx}: {start} to {end} (duration: {duration})")

    return sessions

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

    for idx, (start_time, end_time) in enumerate(sessions, 1):
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

        print(f"   ✓ Session {session_id}: {session_name}")
        print(f"      Records: {records}, Teams: {teams}")

    return session_map

def update_lap_times(cursor, session_map):
    """Update lap_times records with correct session_id"""
    print("\n🔄 Updating lap_times with session IDs...")

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

    print(f"\n✅ Total records updated: {total_updated}")
    return total_updated

def split_track_sessions(track_id, track_name, gap_threshold_minutes=120, dry_run=False):
    """
    Main function to split sessions for a track.

    Args:
        track_id: Track database ID
        track_name: Name of the track
        gap_threshold_minutes: Minimum gap to consider a new session (default: 2 hours)
        dry_run: If True, don't commit changes
    """
    print(f"\n{'='*60}")
    print(f"🏁 Processing Track {track_id}: {track_name}")
    print(f"{'='*60}")

    conn = get_track_db_connection(track_id)
    cursor = conn.cursor()

    try:
        # Analyze and find sessions
        sessions = analyze_time_gaps(cursor, gap_threshold_minutes)

        if not sessions:
            print("❌ No sessions found!")
            return

        if len(sessions) == 1:
            print("ℹ️  Only one continuous session found, no splitting needed")

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

    parser = argparse.ArgumentParser(description='Split racing data into sessions based on time gaps')
    parser.add_argument('--track-id', type=int, help='Process specific track ID only')
    parser.add_argument('--gap-minutes', type=int, default=120,
                       help='Minimum gap in minutes to start new session (default: 120)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Analyze and show what would be done without committing')
    parser.add_argument('--all', action='store_true',
                       help='Process all tracks')

    args = parser.parse_args()

    print("🏎️  LT-Analyzer Session Splitter")
    print("="*60)

    if args.all:
        tracks = get_all_tracks()
        print(f"\n📋 Processing {len(tracks)} tracks...")

        for track_id, track_name in tracks:
            try:
                split_track_sessions(track_id, track_name, args.gap_minutes, args.dry_run)
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
        split_track_sessions(args.track_id, track_name, args.gap_minutes, args.dry_run)

    else:
        print("❌ Please specify --track-id <id> or --all")
        parser.print_help()
        sys.exit(1)

    print("\n" + "="*60)
    print("✅ Session splitting complete!")

if __name__ == '__main__':
    main()
