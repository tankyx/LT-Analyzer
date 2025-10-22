#!/usr/bin/env python3
import sqlite3
import json

def migrate_tracks():
    """Migrate tracks from tracks.db to race_data.db"""
    
    # Connect to both databases
    old_conn = sqlite3.connect('tracks.db')
    old_cursor = old_conn.cursor()
    
    new_conn = sqlite3.connect('race_data.db')
    new_cursor = new_conn.cursor()
    
    # Get all tracks from old database
    old_cursor.execute('SELECT * FROM tracks')
    tracks = old_cursor.fetchall()
    
    print(f"Found {len(tracks)} tracks to migrate")
    
    # Get column names from old tracks table
    old_cursor.execute('PRAGMA table_info(tracks)')
    columns = old_cursor.fetchall()
    column_names = [col[1] for col in columns]
    print(f"Old columns: {column_names}")
    
    # Migrate each track
    for track in tracks:
        track_dict = dict(zip(column_names, track))
        
        # Map old column names to new ones
        column_mappings = json.loads(track_dict.get('column_mappings', '{}'))
        
        try:
            # Handle old column names
            track_name = track_dict.get('track_name', track_dict.get('name', 'Unknown'))
            
            new_cursor.execute('''
                INSERT INTO tracks (name, location, timing_url, websocket_url, 
                                  column_mappings, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                track_name,
                '',  # location doesn't exist in old schema
                track_dict.get('timing_url', ''),
                track_dict.get('websocket_url', ''),
                json.dumps(column_mappings),
                1,  # is_active = True
                track_dict.get('created_at', '2025-06-16 12:00:00'),
                track_dict.get('updated_at', '2025-06-16 12:00:00')
            ))
            print(f"Migrated track: {track_name}")
        except Exception as e:
            print(f"Failed to migrate track: {e}")
    
    new_conn.commit()
    
    # Close connections
    old_conn.close()
    new_conn.close()
    
    print("Migration complete!")

if __name__ == "__main__":
    migrate_tracks()