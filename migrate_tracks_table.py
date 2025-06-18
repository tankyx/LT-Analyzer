#!/usr/bin/env python3
import sqlite3

def migrate_tracks_table():
    """Update tracks table to match new admin requirements"""
    conn = sqlite3.connect('race_data.db')
    cursor = conn.cursor()
    
    # Check if the tracks table exists with the old schema
    cursor.execute("""
        SELECT sql FROM sqlite_master 
        WHERE type='table' AND name='tracks'
    """)
    
    existing_schema = cursor.fetchone()
    
    if existing_schema:
        # Create temporary table with new schema
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT,
                length_meters INTEGER,
                description TEXT,
                timing_url TEXT,
                websocket_url TEXT,
                column_mappings TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Copy data from old table if it exists
        try:
            cursor.execute('''
                INSERT INTO tracks_new (name, timing_url, websocket_url, column_mappings)
                SELECT track_name, timing_url, websocket_url, column_mappings
                FROM tracks
            ''')
            
            # Drop old table
            cursor.execute('DROP TABLE tracks')
        except sqlite3.OperationalError:
            # Old table might not exist or have different columns
            pass
        
        # Rename new table
        cursor.execute('DROP TABLE IF EXISTS tracks')
        cursor.execute('ALTER TABLE tracks_new RENAME TO tracks')
    else:
        # Create tracks table with new schema
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT,
                length_meters INTEGER,
                description TEXT,
                timing_url TEXT,
                websocket_url TEXT,
                column_mappings TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    
    conn.commit()
    conn.close()
    print("Tracks table migration complete")

if __name__ == "__main__":
    migrate_tracks_table()