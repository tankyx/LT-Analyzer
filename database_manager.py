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
                # Fresh-install schema. Historically location/length_meters/
                # description/is_active/provider were added by external
                # migrations, which left fresh installs missing them. Now part
                # of the CREATE so a clean DB has everything; ALTER-adds below
                # still handle in-place migration of older DBs.
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS tracks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        track_name TEXT NOT NULL UNIQUE,
                        timing_url TEXT NOT NULL,
                        websocket_url TEXT,
                        column_mappings TEXT DEFAULT '{}',
                        location TEXT,
                        length_meters INTEGER,
                        description TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        provider TEXT NOT NULL DEFAULT 'apex',
                        pusher_key TEXT,
                        pusher_cluster TEXT,
                        pusher_site TEXT,
                        pusher_channel_suffix TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Migration ALTERs for older DBs that pre-date some columns.
                # Each ALTER guarded by a PRAGMA check so re-running is safe.
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(tracks)")
                columns = [col[1] for col in cursor.fetchall()]
                if 'column_mappings' not in columns:
                    conn.execute("ALTER TABLE tracks ADD COLUMN column_mappings TEXT DEFAULT '{}'")
                if 'location' not in columns:
                    conn.execute("ALTER TABLE tracks ADD COLUMN location TEXT")
                if 'length_meters' not in columns:
                    conn.execute("ALTER TABLE tracks ADD COLUMN length_meters INTEGER")
                if 'description' not in columns:
                    conn.execute("ALTER TABLE tracks ADD COLUMN description TEXT")
                if 'is_active' not in columns:
                    conn.execute("ALTER TABLE tracks ADD COLUMN is_active BOOLEAN DEFAULT 1")
                # provider: which live-timing backend feeds this track.
                # 'apex' (default, existing behaviour) — Apex Timing pipe-delimited
                # websocket, websocket_url is the wss://host:port/ feed.
                # 'alphahub' — alphaRaceHub Pusher feed; websocket_url stores the
                # public live page URL (e.g. https://alpharacehub.com/buckmore/live)
                # which the parser scrapes for its Pusher key, site slug, and the
                # private channel suffix needed to subscribe.
                if 'provider' not in columns:
                    conn.execute("ALTER TABLE tracks ADD COLUMN provider TEXT NOT NULL DEFAULT 'apex'")
                # Cached Pusher config for provider=alphahub tracks. Populated
                # by AlphaHubParser the first time it successfully scrapes the
                # live page. Subsequent reconnects (and even fresh process
                # starts) build the AlphaHubConfig directly from these columns
                # instead of re-poking alpharacehub.com — which previously
                # tripped its per-IP rate limiter whenever many parsers
                # restarted in sync. Cleared (set NULL) on Pusher auth 401 so
                # the next attempt re-scrapes and refreshes. Doesn't store the
                # at-pst per-session token (kept in-memory; see AlphaHubParser).
                for col in (
                    'pusher_key', 'pusher_cluster',
                    'pusher_site', 'pusher_channel_suffix',
                ):
                    if col not in columns:
                        conn.execute(f"ALTER TABLE tracks ADD COLUMN {col} TEXT")
                # pusher_cookies: JSON-encoded {name: value} of the cookies
                # alpharacehub.com set on the page scrape — specifically
                # `<site>-pst`, `.AspNetCore.Culture`, `__cf_bm`. Pusher auth
                # validates `<site>-pst` server-side, so if we persist it we
                # can skip the page scrape on the next process start entirely
                # (where the 20-req-per-IP Cloudflare cap was tripping us).
                # Refreshed whenever a new scrape succeeds; left alone on
                # restart so cold starts hit ZERO alpharacehub HTTP for
                # already-warmed venues.
                if 'pusher_cookies' not in columns:
                    conn.execute("ALTER TABLE tracks ADD COLUMN pusher_cookies TEXT")

                # Physical-layout definitions per track. A single karting venue
                # often runs multiple configs whose lap times differ 10%+; the
                # fairness analytics bucket sessions into layouts to avoid
                # mixing them. Bands are inclusive-of-min, exclusive-of-max.
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS track_layouts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        track_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        min_field_best REAL,
                        max_field_best REAL,
                        is_default INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
                        UNIQUE(track_id, name)
                    )
                ''')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_track_layouts_track ON track_layouts(track_id)')

                # Create trigger to update updated_at timestamp
                conn.execute('''
                    CREATE TRIGGER IF NOT EXISTS update_tracks_timestamp
                    AFTER UPDATE ON tracks
                    BEGIN
                        UPDATE tracks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
                    END
                ''')
                conn.execute('''
                    CREATE TRIGGER IF NOT EXISTS update_track_layouts_timestamp
                    AFTER UPDATE ON track_layouts
                    BEGIN
                        UPDATE track_layouts SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
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
                  is_active: bool = True, provider: str = 'apex') -> Dict:
        """Add a new track to the database"""
        self.ensure_table_exists()  # Ensure table exists before operation
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                mappings_json = json.dumps(column_mappings or {})
                cursor.execute('''
                    INSERT INTO tracks (track_name, timing_url, websocket_url, column_mappings,
                                        location, length_meters, description, is_active, provider)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (track_name, timing_url, websocket_url, mappings_json,
                      location, length_meters, description, is_active, provider))

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
                    'provider': provider,
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
                           location, length_meters, description, is_active, provider,
                           pusher_key, pusher_cluster, pusher_site, pusher_channel_suffix,
                           pusher_cookies,
                           created_at, updated_at
                    FROM tracks
                    ORDER BY track_name
                ''')

                tracks = []
                for row in cursor.fetchall():
                    mappings = {}
                    raw_mappings = row['column_mappings']
                    if raw_mappings:
                        try:
                            mappings = json.loads(raw_mappings)
                        except (json.JSONDecodeError, TypeError) as e:
                            self.logger.warning(
                                f"Track {row['id']}: invalid column_mappings JSON, falling back to data-type detection: {e}"
                            )

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
                        'provider': (row['provider'] or 'apex'),
                        'pusher_key': row['pusher_key'],
                        'pusher_cluster': row['pusher_cluster'],
                        'pusher_site': row['pusher_site'],
                        'pusher_channel_suffix': row['pusher_channel_suffix'],
                        'pusher_cookies': row['pusher_cookies'],
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
                           location, length_meters, description, is_active, provider,
                           created_at, updated_at
                    FROM tracks
                    WHERE id = ?
                ''', (track_id,))

                row = cursor.fetchone()
                if row:
                    mappings = {}
                    raw_mappings = row['column_mappings']
                    if raw_mappings:
                        try:
                            mappings = json.loads(raw_mappings)
                        except (json.JSONDecodeError, TypeError) as e:
                            self.logger.warning(
                                f"Track {row['id']}: invalid column_mappings JSON, falling back to data-type detection: {e}"
                            )

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
                        'provider': (row['provider'] or 'apex'),
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
                     is_active: Optional[bool] = None, provider: Optional[str] = None) -> Dict:
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

                if provider is not None:
                    update_fields.append("provider = ?")
                    params.append(provider)

                if not update_fields:
                    return {'error': 'No fields to update'}

                # Validate column names before building the query. Each entry is
                # "col = ?" constructed from a hardcoded whitelist above; extract
                # the column and assert it's in the known set so future additions
                # can't inject arbitrary SQL via parameter name confusion.
                _VALID_TRACK_COLS = {
                    'track_name', 'timing_url', 'websocket_url', 'column_mappings',
                    'location', 'length_meters', 'description', 'is_active', 'provider',
                }
                for field in update_fields:
                    col = field.split(' = ', 1)[0]
                    if col not in _VALID_TRACK_COLS:
                        raise ValueError(f'Invalid column in update: {col!r}')

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
    
    def update_pusher_config(self, track_id: int, *, pusher_key: Optional[str] = None,
                             pusher_cluster: Optional[str] = None,
                             pusher_site: Optional[str] = None,
                             pusher_channel_suffix: Optional[str] = None,
                             pusher_cookies: Optional[str] = None) -> bool:
        """Persist (or clear, by passing None) the discovered Pusher config for
        an AlphaHub track so reconnects + restarts can skip the live-page
        scrape. Used by AlphaHubHub after a successful first discovery and
        also to invalidate on Pusher auth 401.

        `pusher_cookies` is a JSON-encoded dict of cookie name → value
        captured from the scrape. The next process start can hydrate the
        site's requests.Session from this and skip the page scrape entirely
        — the big win that gets us under Cloudflare's per-IP cap."""
        self.ensure_table_exists()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    UPDATE tracks
                       SET pusher_key = ?, pusher_cluster = ?,
                           pusher_site = ?, pusher_channel_suffix = ?,
                           pusher_cookies = ?
                     WHERE id = ?
                ''', (pusher_key, pusher_cluster, pusher_site,
                      pusher_channel_suffix, pusher_cookies, track_id))
                conn.commit()
                return True
        except Exception as e:
            self.logger.warning(f"Track {track_id}: pusher_config update failed: {e}")
            return False

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

    # ------------------------------------------------------------------
    # Layouts
    # ------------------------------------------------------------------
    def _layout_row_to_dict(self, row) -> Dict:
        return {
            'id': row['id'],
            'track_id': row['track_id'],
            'name': row['name'],
            'min_field_best': row['min_field_best'],
            'max_field_best': row['max_field_best'],
            'is_default': bool(row['is_default']),
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        }

    def get_layouts_for_track(self, track_id: int) -> List[Dict]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, track_id, name, min_field_best, max_field_best,
                           is_default, created_at, updated_at
                      FROM track_layouts
                     WHERE track_id = ?
                     ORDER BY is_default DESC, min_field_best ASC, name ASC
                ''', (track_id,))
                return [self._layout_row_to_dict(r) for r in cursor.fetchall()]
        except Exception as e:
            self.logger.error(f"Error listing layouts for track {track_id}: {e}")
            return []

    def get_layout_by_id(self, layout_id: int) -> Optional[Dict]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, track_id, name, min_field_best, max_field_best,
                           is_default, created_at, updated_at
                      FROM track_layouts WHERE id = ?
                ''', (layout_id,))
                row = cursor.fetchone()
                return self._layout_row_to_dict(row) if row else None
        except Exception as e:
            self.logger.error(f"Error getting layout {layout_id}: {e}")
            return None

    def add_layout(self, track_id: int, name: str,
                   min_field_best: Optional[float] = None,
                   max_field_best: Optional[float] = None,
                   is_default: bool = False) -> Dict:
        if not name or not name.strip():
            return {'error': 'Layout name is required'}
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if is_default:
                    cursor.execute(
                        'UPDATE track_layouts SET is_default = 0 WHERE track_id = ?',
                        (track_id,)
                    )
                cursor.execute('''
                    INSERT INTO track_layouts (track_id, name, min_field_best,
                                               max_field_best, is_default)
                    VALUES (?, ?, ?, ?, ?)
                ''', (track_id, name.strip(), min_field_best, max_field_best,
                      1 if is_default else 0))
                layout_id = cursor.lastrowid
                conn.commit()
                return self.get_layout_by_id(layout_id) or {'error': 'insert failed'}
        except sqlite3.IntegrityError as e:
            return {'error': f'Layout name already exists for this track: {e}'}
        except Exception as e:
            self.logger.error(f"Error adding layout: {e}")
            return {'error': str(e)}

    def update_layout(self, layout_id: int,
                      name: Optional[str] = None,
                      min_field_best: Optional[float] = None,
                      max_field_best: Optional[float] = None,
                      is_default: Optional[bool] = None,
                      clear_min: bool = False,
                      clear_max: bool = False) -> Dict:
        try:
            existing = self.get_layout_by_id(layout_id)
            if not existing:
                return {'error': 'Layout not found'}
            fields = []
            params: list = []
            if name is not None:
                if not name.strip():
                    return {'error': 'Layout name cannot be empty'}
                fields.append('name = ?')
                params.append(name.strip())
            if clear_min:
                fields.append('min_field_best = NULL')
            elif min_field_best is not None:
                fields.append('min_field_best = ?')
                params.append(min_field_best)
            if clear_max:
                fields.append('max_field_best = NULL')
            elif max_field_best is not None:
                fields.append('max_field_best = ?')
                params.append(max_field_best)
            if is_default is not None:
                fields.append('is_default = ?')
                params.append(1 if is_default else 0)
            if not fields:
                return {'error': 'No fields to update'}

            # Validate column names (same defence-in-depth as update_track).
            _VALID_LAYOUT_COLS = {'name', 'min_field_best', 'max_field_best', 'is_default'}
            for f in fields:
                col = f.split(' = ', 1)[0]
                if col not in _VALID_LAYOUT_COLS:
                    raise ValueError(f'Invalid column in layout update: {col!r}')

            params.append(layout_id)
            with sqlite3.connect(self.db_path) as conn:
                if is_default:
                    conn.execute(
                        'UPDATE track_layouts SET is_default = 0 WHERE track_id = ? AND id != ?',
                        (existing['track_id'], layout_id)
                    )
                conn.execute(
                    f"UPDATE track_layouts SET {', '.join(fields)} WHERE id = ?",
                    params
                )
                conn.commit()
            return self.get_layout_by_id(layout_id) or {'error': 'update failed'}
        except sqlite3.IntegrityError as e:
            return {'error': f'Layout name already exists for this track: {e}'}
        except Exception as e:
            self.logger.error(f"Error updating layout {layout_id}: {e}")
            return {'error': str(e)}

    def delete_layout(self, layout_id: int) -> Dict:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM track_layouts WHERE id = ?', (layout_id,))
                if cursor.rowcount == 0:
                    return {'error': 'Layout not found'}
                conn.commit()
                return {'message': 'Layout deleted successfully'}
        except Exception as e:
            self.logger.error(f"Error deleting layout {layout_id}: {e}")
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