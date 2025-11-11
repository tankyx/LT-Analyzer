"""
Migrate historical data from race_data.db to race_data_track_1.db

This script copies all data from the original race_data.db (355MB) to the
new track-specific database format.
"""

import sqlite3
import os
from datetime import datetime


def migrate_data():
    """Migrate all data from race_data.db to race_data_track_1.db"""

    source_db = 'race_data.db'
    target_db = 'race_data_track_1.db'

    # Check if source exists
    if not os.path.exists(source_db):
        print(f"ERROR: Source database {source_db} not found!")
        return False

    print(f"Starting migration from {source_db} to {target_db}")
    print(f"Source database size: {os.path.getsize(source_db) / (1024*1024):.2f} MB")

    if os.path.exists(target_db):
        backup_name = f"{target_db}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"Target database exists, backing up to {backup_name}")
        os.rename(target_db, backup_name)

    try:
        # Connect to both databases
        source_conn = sqlite3.connect(source_db)
        target_conn = sqlite3.connect(target_db)

        source_cursor = source_conn.cursor()
        target_cursor = target_conn.cursor()

        # Create tables in target database
        print("Creating tables in target database...")

        target_cursor.execute('''
            CREATE TABLE IF NOT EXISTS race_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT,
                name TEXT,
                track TEXT
            )
        ''')

        target_cursor.execute('''
            CREATE TABLE IF NOT EXISTS lap_times (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                timestamp TEXT,
                position INTEGER,
                kart_number INTEGER,
                team_name TEXT,
                last_lap TEXT,
                best_lap TEXT,
                gap TEXT,
                RunTime TEXT,
                pit_stops INTEGER,
                FOREIGN KEY (session_id) REFERENCES race_sessions(session_id)
            )
        ''')

        target_cursor.execute('''
            CREATE TABLE IF NOT EXISTS lap_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                timestamp TEXT,
                kart_number INTEGER,
                team_name TEXT,
                lap_number INTEGER,
                lap_time TEXT,
                position_after_lap INTEGER,
                pit_this_lap INTEGER,
                FOREIGN KEY (session_id) REFERENCES race_sessions(session_id)
            )
        ''')

        # Create indices
        print("Creating indices...")
        target_cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_lap_times_session
            ON lap_times(session_id, timestamp)
        ''')

        target_cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_lap_times_team
            ON lap_times(team_name, session_id)
        ''')

        target_cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_lap_history_session
            ON lap_history(session_id, lap_number)
        ''')

        # Migrate race_sessions
        print("Migrating race_sessions table...")
        source_cursor.execute("SELECT * FROM race_sessions")
        sessions = source_cursor.fetchall()
        print(f"  Found {len(sessions)} sessions")

        if sessions:
            # Get column count to build correct placeholder string
            placeholders = ','.join(['?' for _ in range(len(sessions[0]))])
            target_cursor.executemany(
                f"INSERT INTO race_sessions VALUES ({placeholders})",
                sessions
            )

        # Migrate lap_times
        print("Migrating lap_times table (this may take a while)...")
        source_cursor.execute("SELECT COUNT(*) FROM lap_times")
        total_rows = source_cursor.fetchone()[0]
        print(f"  Found {total_rows:,} rows to migrate")

        batch_size = 10000
        offset = 0
        migrated = 0

        while offset < total_rows:
            source_cursor.execute(
                f"SELECT * FROM lap_times LIMIT {batch_size} OFFSET {offset}"
            )
            batch = source_cursor.fetchall()

            if not batch:
                break

            placeholders = ','.join(['?' for _ in range(len(batch[0]))])
            target_cursor.executemany(
                f"INSERT INTO lap_times VALUES ({placeholders})",
                batch
            )

            migrated += len(batch)
            offset += batch_size

            # Commit every batch and show progress
            target_conn.commit()
            progress = (migrated / total_rows) * 100
            print(f"  Progress: {migrated:,}/{total_rows:,} ({progress:.1f}%)")

        # Migrate lap_history
        print("Migrating lap_history table...")
        source_cursor.execute("SELECT COUNT(*) FROM lap_history")
        history_rows = source_cursor.fetchone()[0]
        print(f"  Found {history_rows:,} rows")

        if history_rows > 0:
            source_cursor.execute("SELECT * FROM lap_history")
            history_data = source_cursor.fetchall()

            if history_data:
                placeholders = ','.join(['?' for _ in range(len(history_data[0]))])
                target_cursor.executemany(
                    f"INSERT INTO lap_history VALUES ({placeholders})",
                    history_data
                )

        # Final commit
        target_conn.commit()

        # Verify migration
        print("\nVerifying migration...")
        target_cursor.execute("SELECT COUNT(*) FROM race_sessions")
        target_sessions = target_cursor.fetchone()[0]

        target_cursor.execute("SELECT COUNT(*) FROM lap_times")
        target_laps = target_cursor.fetchone()[0]

        target_cursor.execute("SELECT COUNT(*) FROM lap_history")
        target_history = target_cursor.fetchone()[0]

        print(f"\nMigration Summary:")
        print(f"  race_sessions: {target_sessions:,} rows")
        print(f"  lap_times: {target_laps:,} rows")
        print(f"  lap_history: {target_history:,} rows")
        print(f"\nTarget database size: {os.path.getsize(target_db) / (1024*1024):.2f} MB")

        # Close connections
        source_conn.close()
        target_conn.close()

        print("\n✓ Migration completed successfully!")
        return True

    except Exception as e:
        print(f"\nERROR during migration: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("=" * 60)
    print("Historical Data Migration Script")
    print("=" * 60)
    print()

    confirm = input("This will migrate data from race_data.db to race_data_track_1.db.\nContinue? (yes/no): ")

    if confirm.lower() in ['yes', 'y']:
        success = migrate_data()
        if success:
            print("\nMigration complete! You can now use the new multi-track architecture.")
            print("The original race_data.db file has been preserved.")
        else:
            print("\nMigration failed. Please check the errors above.")
    else:
        print("Migration cancelled.")
