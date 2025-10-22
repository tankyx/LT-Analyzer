import sqlite3
import os
from typing import List, Dict, Optional
import logging

class TrackDatabase:
    """
    Manages persistent track data in a separate database (tracks.db).
    This database is independent from race_data.db and should never be cleared.
    """
    def __init__(self, db_path='tracks.db'):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.init_database()
    
    def init_database(self):
        """Initialize the database with tracks table"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Create tracks table
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS tracks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        track_name TEXT NOT NULL UNIQUE,
                        timing_url TEXT NOT NULL,
                        websocket_url TEXT,
                        column_mappings TEXT DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Add column_mappings column if it doesn't exist (for existing databases)
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(tracks)")
                columns = [col[1] for col in cursor.fetchall()]
                if 'column_mappings' not in columns:
                    conn.execute("ALTER TABLE tracks ADD COLUMN column_mappings TEXT DEFAULT '{}'")
                
                # Create trigger to update updated_at timestamp
                conn.execute('''
                    CREATE TRIGGER IF NOT EXISTS update_tracks_timestamp 
                    AFTER UPDATE ON tracks
                    BEGIN
                        UPDATE tracks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
                    END
                ''')
                
                conn.commit()
                self.logger.info(f"Database initialized with tracks table in {self.db_path}")
                
                # Verify table was created
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracks'")
                if cursor.fetchone():
                    self.logger.info(f"Tracks table verified successfully in {self.db_path}")
                else:
                    self.logger.error(f"Failed to create tracks table in {self.db_path}")
                    
        except Exception as e:
            self.logger.error(f"Error initializing database: {e}")
            print(f"ERROR: Failed to initialize tracks table: {e}")
            raise
    
    def ensure_table_exists(self):
        """Ensure the tracks table exists before any operation"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracks'")
                if not cursor.fetchone():
                    self.logger.warning("Tracks table not found, creating it now...")
                    self.init_database()
        except Exception as e:
            self.logger.error(f"Error checking table existence: {e}")
            raise
    
    def add_track(self, track_name: str, timing_url: str, websocket_url: Optional[str] = None,
                  column_mappings: Optional[Dict] = None, location: Optional[str] = None,
                  length_meters: Optional[int] = None, description: Optional[str] = None,
                  is_active: bool = True) -> Dict:
        """Add a new track to the database"""
        self.ensure_table_exists()  # Ensure table exists before operation
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                mappings_json = json.dumps(column_mappings or {})
                cursor.execute('''
                    INSERT INTO tracks (track_name, timing_url, websocket_url, column_mappings,
                                        location, length_meters, description, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (track_name, timing_url, websocket_url, mappings_json,
                      location, length_meters, description, is_active))

                track_id = cursor.lastrowid
                conn.commit()

                return {
                    'id': track_id,
                    'track_name': track_name,
                    'timing_url': timing_url,
                    'websocket_url': websocket_url,
                    'column_mappings': column_mappings or {},
                    'location': location,
                    'length_meters': length_meters,
                    'description': description,
                    'is_active': is_active,
                    'message': 'Track added successfully'
                }
        except sqlite3.IntegrityError:
            return {'error': 'Track with this name already exists'}
        except Exception as e:
            self.logger.error(f"Error adding track: {e}")
            return {'error': str(e)}
    
    def get_all_tracks(self) -> List[Dict]:
        """Get all tracks from the database"""
        self.ensure_table_exists()  # Ensure table exists before operation
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, track_name, timing_url, websocket_url, column_mappings,
                           location, length_meters, description, is_active,
                           created_at, updated_at
                    FROM tracks
                    ORDER BY track_name
                ''')

                tracks = []
                for row in cursor.fetchall():
                    mappings = {}
                    try:
                        if row['column_mappings']:
                            mappings = json.loads(row['column_mappings'])
                    except:
                        pass

                    tracks.append({
                        'id': row['id'],
                        'track_name': row['track_name'],
                        'timing_url': row['timing_url'],
                        'websocket_url': row['websocket_url'],
                        'column_mappings': mappings,
                        'location': row['location'],
                        'length_meters': row['length_meters'],
                        'description': row['description'],
                        'is_active': row['is_active'],
                        'created_at': row['created_at'],
                        'updated_at': row['updated_at']
                    })

                return tracks
        except Exception as e:
            self.logger.error(f"Error getting tracks: {e}")
            return []
    
    def get_track_by_id(self, track_id: int) -> Optional[Dict]:
        """Get a specific track by ID"""
        self.ensure_table_exists()  # Ensure table exists before operation
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, track_name, timing_url, websocket_url, column_mappings,
                           location, length_meters, description, is_active,
                           created_at, updated_at
                    FROM tracks
                    WHERE id = ?
                ''', (track_id,))

                row = cursor.fetchone()
                if row:
                    mappings = {}
                    try:
                        if row['column_mappings']:
                            mappings = json.loads(row['column_mappings'])
                    except:
                        pass

                    return {
                        'id': row['id'],
                        'track_name': row['track_name'],
                        'timing_url': row['timing_url'],
                        'websocket_url': row['websocket_url'],
                        'column_mappings': mappings,
                        'location': row['location'],
                        'length_meters': row['length_meters'],
                        'description': row['description'],
                        'is_active': row['is_active'],
                        'created_at': row['created_at'],
                        'updated_at': row['updated_at']
                    }
                return None
        except Exception as e:
            self.logger.error(f"Error getting track: {e}")
            return None
    
    def update_track(self, track_id: int, track_name: Optional[str] = None,
                     timing_url: Optional[str] = None, websocket_url: Optional[str] = None,
                     column_mappings: Optional[Dict] = None, location: Optional[str] = None,
                     length_meters: Optional[int] = None, description: Optional[str] = None,
                     is_active: Optional[bool] = None) -> Dict:
        """Update a track's information"""
        self.ensure_table_exists()  # Ensure table exists before operation
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Build update query dynamically based on provided fields
                update_fields = []
                params = []

                if track_name is not None:
                    update_fields.append("track_name = ?")
                    params.append(track_name)

                if timing_url is not None:
                    update_fields.append("timing_url = ?")
                    params.append(timing_url)

                if websocket_url is not None:
                    update_fields.append("websocket_url = ?")
                    params.append(websocket_url)

                if column_mappings is not None:
                    update_fields.append("column_mappings = ?")
                    params.append(json.dumps(column_mappings))

                if location is not None:
                    update_fields.append("location = ?")
                    params.append(location)

                if length_meters is not None:
                    update_fields.append("length_meters = ?")
                    params.append(length_meters)

                if description is not None:
                    update_fields.append("description = ?")
                    params.append(description)

                if is_active is not None:
                    update_fields.append("is_active = ?")
                    params.append(is_active)

                if not update_fields:
                    return {'error': 'No fields to update'}

                params.append(track_id)
                query = f"UPDATE tracks SET {', '.join(update_fields)} WHERE id = ?"

                cursor.execute(query, params)

                if cursor.rowcount == 0:
                    return {'error': 'Track not found'}

                conn.commit()
                return {'message': 'Track updated successfully'}

        except sqlite3.IntegrityError:
            return {'error': 'Track with this name already exists'}
        except Exception as e:
            self.logger.error(f"Error updating track: {e}")
            return {'error': str(e)}
    
    def delete_track(self, track_id: int) -> Dict:
        """Delete a track from the database"""
        self.ensure_table_exists()  # Ensure table exists before operation
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM tracks WHERE id = ?', (track_id,))
                
                if cursor.rowcount == 0:
                    return {'error': 'Track not found'}
                
                conn.commit()
                return {'message': 'Track deleted successfully'}
                
        except Exception as e:
            self.logger.error(f"Error deleting track: {e}")
            return {'error': str(e)}


# Initialize database when module is imported
if __name__ == "__main__":
    # Test the database
    db = TrackDatabase()
    
    # Add some example tracks
    print("Adding example tracks...")
    print(db.add_track("Karting Mariembourg", "https://www.apex-timing.com/live-timing/karting-mariembourg/index.html", "ws://www.apex-timing.com:8585/"))
    print(db.add_track("Circuit Zolder", "https://www.apex-timing.com/live-timing/circuit-zolder/index.html", "ws://www.apex-timing.com:8586/"))
    
    # List all tracks
    print("\nAll tracks:")
    for track in db.get_all_tracks():
        print(f"- {track['track_name']}: {track['timing_url']}")