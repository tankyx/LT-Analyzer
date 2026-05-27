"""
Multi-Track Parser Manager
Manages multiple WebSocket parsers, one per track, writing to separate databases
"""

import asyncio
import sqlite3
import logging
import threading
from typing import Dict, List, Optional
from datetime import datetime
import json
import pandas as pd
from apex_timing_websocket import ApexTimingWebSocketParser


class MultiTrackManager:
    """Manages multiple track parsers running concurrently"""

    def __init__(self, socketio=None):
        self.parsers: Dict[int, ApexTimingWebSocketParser] = {}
        self.tasks: Dict[int, asyncio.Task] = {}
        self.active = False
        self.logger = logging.getLogger(__name__)
        self.socketio = socketio

    def get_database_path(self, track_id: int) -> str:
        """Get the database file path for a track"""
        return f'race_data_track_{track_id}.db'

    def initialize_track_database(self, track_id: int):
        """Initialize a database file for a specific track"""
        db_path = self.get_database_path(track_id)

        try:
            with sqlite3.connect(db_path, timeout=5.0) as conn:
                # Enable WAL mode for better concurrent access
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS race_sessions (
                        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        start_time TEXT,
                        name TEXT,
                        track TEXT
                    )
                ''')

                # layout_id: physical-layout assignment (NULL until inferred
                # from the session's field-best). Populated lazily by the
                # fairness endpoints so ingestion doesn't depend on track
                # config being present up-front.
                # is_excluded: admin-controlled flag for sessions that
                # shouldn't feed aggregate stats (test events, anomalous
                # data, novice-only sessions whose field median is unreliable).
                # The session and its laps stay in the DB for audit; only
                # analytics-side queries skip is_excluded=1.
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(race_sessions)")
                cols = [c[1] for c in cursor.fetchall()]
                if 'layout_id' not in cols:
                    conn.execute('ALTER TABLE race_sessions ADD COLUMN layout_id INTEGER')
                if 'is_excluded' not in cols:
                    conn.execute('ALTER TABLE race_sessions ADD COLUMN is_excluded INTEGER DEFAULT 0')
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_race_sessions_layout
                    ON race_sessions(layout_id)
                ''')
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_race_sessions_excluded
                    ON race_sessions(is_excluded)
                ''')

                conn.execute('''
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

                conn.execute('''
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

                # Create indices for better query performance
                # lap_times table indexes
                # Note: idx_lap_times_session_time (session_id, timestamp DESC) and
                # idx_lap_times_team_session (team_name, session_id) used to be
                # created here too but they were exact duplicates of
                # idx_lap_times_session and idx_lap_times_team — SQLite can scan
                # an ASC index in either direction, and the team_session pair
                # had identical columns to the team index. Dropped 2026-05-26
                # for ~28% per-DB size reduction.
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_times_session_kart
                    ON lap_times(session_id, kart_number, timestamp DESC)
                ''')

                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_times_team_best
                    ON lap_times(team_name, best_lap)
                ''')

                # lap_history table indexes
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_history_session_team
                    ON lap_history(session_id, team_name, timestamp ASC)
                ''')

                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_history_session_kart
                    ON lap_history(session_id, kart_number, timestamp ASC)
                ''')

                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_history_team
                    ON lap_history(team_name, session_id)
                ''')

                # --- Fleet Tracker (endurance physical-machine tracking) ---
                # The timing feed only exposes team identity; the physical kart
                # a team runs each stint is supplied by the user. Fleet data is
                # PER USER (each user keeps their own roster + mappings), so both
                # tables carry user_id. fleet_karts is a user's registry of
                # physical machines; fleet_assignments is an append-only log
                # mapping a team to a physical kart for a stint of a session.
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS fleet_karts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        label TEXT NOT NULL,
                        notes TEXT,
                        is_active INTEGER DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT
                    )
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS fleet_assignments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        session_id INTEGER NOT NULL,
                        team_name TEXT NOT NULL,
                        kart_number INTEGER,
                        fleet_kart_id INTEGER NOT NULL,
                        stint_index INTEGER NOT NULL,
                        source TEXT NOT NULL DEFAULT 'manual',
                        created_at TEXT NOT NULL,
                        created_by INTEGER,
                        superseded INTEGER DEFAULT 0,
                        FOREIGN KEY (session_id) REFERENCES race_sessions(session_id),
                        FOREIGN KEY (fleet_kart_id) REFERENCES fleet_karts(id)
                    )
                ''')

                # Additive migration for DBs created before fleet went per-user.
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(fleet_karts)")
                kart_cols = [c[1] for c in cursor.fetchall()]
                if 'user_id' not in kart_cols:
                    conn.execute('ALTER TABLE fleet_karts ADD COLUMN user_id INTEGER')
                # lane: which pit-lane the kart sits in while Available (NULL when
                # held by a team or not yet placed). Drives the colored lanes in
                # the kanban board.
                if 'lane' not in kart_cols:
                    conn.execute('ALTER TABLE fleet_karts ADD COLUMN lane INTEGER')
                cursor.execute("PRAGMA table_info(fleet_assignments)")
                if 'user_id' not in [c[1] for c in cursor.fetchall()]:
                    conn.execute('ALTER TABLE fleet_assignments ADD COLUMN user_id INTEGER')

                # A label is unique per user among that user's active karts (so a
                # retired label can be reused, and two users can both have "K7").
                # Drop the old global-unique index if it lingers from v1.
                conn.execute('DROP INDEX IF EXISTS idx_fleet_karts_label')
                conn.execute('''
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_fleet_karts_user_label
                    ON fleet_karts(user_id, label) WHERE is_active = 1
                ''')
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_fleet_assign_user_session
                    ON fleet_assignments(user_id, session_id, team_name, created_at DESC)
                ''')
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_fleet_assign_session_kart
                    ON fleet_assignments(session_id, fleet_kart_id, created_at DESC)
                ''')

            self.logger.info(f"Initialized database for track {track_id}: {db_path}")
        except Exception as e:
            self.logger.error(f"Error initializing database for track {track_id}: {e}")
            raise

    def load_tracks(self) -> List[Dict]:
        """Load all tracks from tracks.db that have websocket URLs"""
        try:
            with sqlite3.connect('tracks.db') as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, track_name, websocket_url, column_mappings
                    FROM tracks
                    WHERE websocket_url IS NOT NULL AND websocket_url != ''
                ''')
                tracks = [dict(row) for row in cursor.fetchall()]
                self.logger.info(f"Loaded {len(tracks)} tracks with WebSocket URLs")
                return tracks
        except Exception as e:
            self.logger.error(f"Error loading tracks: {e}")
            return []

    async def start_track_parser(self, track: Dict):
        """Start a parser for a specific track"""
        track_id = track['id']
        track_name = track['track_name']
        websocket_url = track['websocket_url']

        try:
            # Initialize database for this track
            self.initialize_track_database(track_id)

            # Create a custom parser that uses the track-specific database
            parser = TrackSpecificParser(track_id, track_name, self.get_database_path(track_id), self.socketio, manager=self)

            # Set column mappings if available
            column_mappings = track.get('column_mappings')
            self.logger.debug(f"Track {track_id} column_mappings value: {repr(column_mappings)}")
            if column_mappings:
                try:
                    self.logger.debug(f"Loading column mappings for track {track_id}: {column_mappings}")
                    mappings = json.loads(column_mappings)
                    self.logger.debug(f"Parsed mappings: {mappings}")
                    parser.set_column_mappings(mappings)
                except Exception as e:
                    self.logger.error(f"Error setting column mappings for track {track_id}: {e}")
                    import traceback
                    self.logger.error(traceback.format_exc())
            else:
                self.logger.debug(f"No column mappings for track {track_id}")

            self.parsers[track_id] = parser

            # Start the parser with full monitoring (includes message loop)
            self.logger.info(f"Starting parser for track {track_id} ({track_name}): {websocket_url}")
            await parser.start_monitoring(websocket_url)

        except Exception as e:
            self.logger.error(f"Error starting parser for track {track_id}: {e}")
            if track_id in self.parsers:
                del self.parsers[track_id]

    async def start_all_parsers(self):
        """Start parsers for all configured tracks"""
        tracks = self.load_tracks()

        if not tracks:
            self.logger.warning("No tracks configured with WebSocket URLs")
            return

        self.active = True

        # Create tasks for all tracks
        for track in tracks:
            task = asyncio.create_task(self.start_track_parser(track))
            self.tasks[track['id']] = task

        self.logger.info(f"Started {len(self.tasks)} track parser(s)")

        # Wait for all tasks (they run indefinitely until stopped)
        try:
            await asyncio.gather(*self.tasks.values())
        except asyncio.CancelledError:
            self.logger.info("Parser tasks cancelled")

    async def stop_all_parsers(self):
        """Stop all running parsers"""
        self.active = False
        self.logger.info("Stopping all parsers...")

        # Cancel all tasks
        for track_id, task in self.tasks.items():
            task.cancel()

        # Wait for tasks to finish
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)

        # Cleanup parsers
        for parser in self.parsers.values():
            await parser.cleanup()

        self.parsers.clear()
        self.tasks.clear()
        self.logger.info("All parsers stopped")

    def get_active_tracks(self) -> List[Dict]:
        """Get list of currently active tracks"""
        return [
            {
                'track_id': track_id,
                'is_connected': parser.is_connected,
                'track_name': parser.track_name
            }
            for track_id, parser in self.parsers.items()
        ]

    def get_all_tracks_status(self) -> List[Dict]:
        """Get session status for all tracks"""
        tracks_status = []
        for track_id, parser in self.parsers.items():
            status = {
                'track_id': track_id,
                'track_name': parser.track_name,
                'active': parser.session_active_status if hasattr(parser, 'session_active_status') else False,
                'last_update': parser.last_data_time.isoformat() if parser.last_data_time else None,
                'is_connected': parser.is_connected
            }

            # Try to get teams count from current standings
            try:
                if hasattr(parser, 'get_current_standings'):
                    standings = parser.get_current_standings()
                    if standings is not None and not standings.empty:
                        status['teams_count'] = len(standings)
                    else:
                        status['teams_count'] = 0
                else:
                    status['teams_count'] = 0
            except Exception as e:
                self.logger.warning(
                    f"Track {track_id}: failed to read current standings for status: {e}"
                )
                status['teams_count'] = 0

            tracks_status.append(status)

        return tracks_status

    def broadcast_all_tracks_status(self):
        """Broadcast status of all tracks to the all_tracks room"""
        if self.socketio:
            try:
                tracks_status = self.get_all_tracks_status()
                self.socketio.emit('all_tracks_status', {
                    'tracks': tracks_status,
                    'timestamp': datetime.now().isoformat()
                }, room='all_tracks')
                self.logger.debug(f"Broadcasted status for {len(tracks_status)} tracks to all_tracks room")
            except Exception as e:
                self.logger.error(f"Error broadcasting all tracks status: {e}")


class TrackSpecificParser(ApexTimingWebSocketParser):
    """Extended parser that writes to a track-specific database"""

    def __init__(self, track_id: int, track_name: str, db_path: str, socketio=None, manager=None):
        # Set attributes BEFORE calling super().__init__() so setup_database() can use them
        self.track_id = track_id
        self.track_name = track_name
        self.db_path = db_path
        self.socketio = socketio
        self.manager = manager  # Reference to MultiTrackManager for broadcasting all tracks status
        self.logger = logging.getLogger(f"{__name__}.Track{track_id}")

        # No-session detection
        self.last_data_time = None
        self.session_active_status = None  # None = unknown, True = active, False = inactive
        # If we go this long between lap updates we treat the next data as a
        # new race event, even if the lap number didn't reset to 1 (the
        # parser may have reconnected mid-race after a websocket drop).
        # Set to 30 min: longer than realistic intermissions/format changes
        # within a single event, much shorter than the typical multi-hour
        # gap between race meetings.
        self.SESSION_GAP_THRESHOLD = 1800
        self.no_session_timeout = 120  # seconds (2 minutes without data = no session)
        self.check_interval = 30  # check every 30 seconds
        self.monitor_thread = None
        self.monitor_stop_event = threading.Event()

        # Automatic session detection
        self.current_session_id = None
        self.current_leader_lap = None
        self.last_lap_change_time = None
        self.STALE_LAP_THRESHOLD = 300  # 5 minutes in seconds
        self.session_ended = False  # Track if current session has ended

        # In-memory cache for previous state (performance optimization)
        # Structure: {session_id: {kart_number: {'RunTime': int, 'last_lap': str, 'best_lap': str, 'pit_stops': int}}}
        self.previous_state_cache = {}
        # Counter for write commits, used to drive periodic cache cleanup.
        self._commit_count = 0

        # Now call parent init which will call setup_database()
        super().__init__()

    def setup_database(self):
        """Override to use track-specific database"""
        # Database is already initialized by MultiTrackManager
        # Don't create tables here, just log
        self.logger.debug(f"Using database: {self.db_path}")

    def cleanup_old_cache_sessions(self, keep_last_n=2):
        """Clean up old session data from cache to prevent memory bloat"""
        if len(self.previous_state_cache) > keep_last_n:
            # Keep only the most recent N sessions
            sessions_to_keep = sorted(self.previous_state_cache.keys(), reverse=True)[:keep_last_n]
            sessions_to_remove = [sid for sid in self.previous_state_cache.keys() if sid not in sessions_to_keep]
            for sid in sessions_to_remove:
                del self.previous_state_cache[sid]
            if sessions_to_remove:
                self.logger.debug(f"Track {self.track_id}: Cleaned up {len(sessions_to_remove)} old sessions from cache")

    def start_session_monitoring(self):
        """Start periodic check for session activity in a background thread"""
        import time
        try:
            while not self.monitor_stop_event.is_set():
                # Wait for check_interval seconds or until stop event is set
                if self.monitor_stop_event.wait(self.check_interval):
                    break
                self.check_session_status()
        except Exception as e:
            self.logger.error(f"Error in session monitoring: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def check_session_status(self):
        """Check if session is active based on data reception"""
        now = datetime.now()
        status_changed = False

        if self.last_data_time is None:
            # No data received yet
            if self.session_active_status != False:
                self.session_active_status = False
                status_changed = True
                if self.socketio:
                    room = f'track_{self.track_id}'
                    try:
                        self.socketio.emit('session_status', {
                            'track_id': self.track_id,
                            'track_name': self.track_name,
                            'active': False,
                            'message': 'No active session',
                            'timestamp': now.isoformat()
                        }, room=room)
                        self.logger.info(f"No session detected for track {self.track_id} ({self.track_name})")
                    except Exception as e:
                        self.logger.error(f"Error emitting session_status: {e}")

                # Broadcast all tracks status update
                if self.manager:
                    self.manager.broadcast_all_tracks_status()
            return

        # Check time since last data
        time_since_data = (now - self.last_data_time).total_seconds()

        if time_since_data > self.no_session_timeout:
            # Session is inactive
            if self.session_active_status != False:
                self.session_active_status = False
                status_changed = True
                if self.socketio:
                    room = f'track_{self.track_id}'
                    try:
                        self.socketio.emit('session_status', {
                            'track_id': self.track_id,
                            'track_name': self.track_name,
                            'active': False,
                            'message': 'No active session',
                            'timestamp': now.isoformat()
                        }, room=room)
                        self.logger.info(f"Session inactive for track {self.track_id} ({self.track_name}) - no data for {time_since_data:.0f}s")
                    except Exception as e:
                        self.logger.error(f"Error emitting session_status: {e}")
        else:
            # Session is active
            if self.session_active_status != True:
                self.session_active_status = True
                status_changed = True
                if self.socketio:
                    room = f'track_{self.track_id}'
                    try:
                        self.socketio.emit('session_status', {
                            'track_id': self.track_id,
                            'track_name': self.track_name,
                            'active': True,
                            'message': 'Session active',
                            'timestamp': now.isoformat()
                        }, room=room)
                        self.logger.info(f"Session active for track {self.track_id} ({self.track_name})")
                    except Exception as e:
                        self.logger.error(f"Error emitting session_status: {e}")

        # Broadcast all tracks status update if status changed
        if status_changed and self.manager:
            self.manager.broadcast_all_tracks_status()

    async def start_monitoring(self, ws_url: str):
        """Start WebSocket monitoring with message loop and session tracking"""
        # Session ID will be determined dynamically based on lap progression
        reconnect_delay = 5

        # Start session monitoring thread
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_stop_event.clear()
            self.monitor_thread = threading.Thread(
                target=self.start_session_monitoring,
                name=f"SessionMonitor-Track{self.track_id}",
                daemon=True
            )
            self.monitor_thread.start()
            self.logger.info(f"Started session monitoring thread for track {self.track_id} ({self.track_name})")

        # Start WebSocket connection and message loop
        while True:
            try:
                # Connect to WebSocket
                if not await self.connect_websocket(ws_url):
                    self.logger.warning(f"Track {self.track_id}: Retrying connection in {reconnect_delay} seconds...")
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 60)  # Exponential backoff
                    continue

                reconnect_delay = 5  # Reset on successful connection

                # Send initial message to request data (some WebSocket servers require this)
                try:
                    await self.websocket.send("init")
                    self.logger.debug(f"Track {self.track_id}: Sent init message to WebSocket")
                except Exception as e:
                    self.logger.warning(f"Track {self.track_id}: Could not send init message: {e}")

                # Listen for messages
                self.logger.info(f"Track {self.track_id} ({self.track_name}): Listening for WebSocket messages...")
                message_count = 0
                async for message in self.websocket:
                    message_count += 1
                    try:
                        # Log the message at debug level
                        self.logger.debug(f"Track {self.track_id} WebSocket message #{message_count}: {len(message)} bytes")

                        # Log message content for debugging (sample every 20 messages)
                        if message_count % 20 == 0:
                            self.logger.debug(f"Track {self.track_id} message sample: {message[:200]}")

                        # Split message by newlines as it contains multiple commands
                        lines = message.strip().split('\n')

                        for i, line in enumerate(lines):
                            if not line.strip():
                                continue

                            # Parse each command line
                            parsed = self.parse_websocket_message(line)
                            if not parsed:
                                continue

                            command = parsed['command']

                            # Log commands for debugging (sample every 50 messages to avoid spam)
                            if message_count % 50 == 0 or command == 'update':
                                self.logger.debug(f"Track {self.track_id}: Command '{command}' param='{parsed.get('parameter', '')}' value_len={len(parsed.get('value', ''))}")

                            # Process different message types
                            if command == 'init':
                                self.process_init_message(parsed)
                            elif command == 'grid':
                                self.process_grid_message(parsed)
                            elif command == 'update':
                                self.process_update_message(parsed)
                            elif command == 'css':
                                self.process_css_message(parsed)
                            elif command == 'title1':
                                self.session_info['title1'] = parsed['value']
                            elif command == 'title2':
                                self.session_info['title2'] = parsed['value']
                            elif command == 'title':
                                self.process_title_message(parsed)
                            elif command == 'clear':
                                # Clear data for the specified element
                                if parsed['parameter'] == 'grid':
                                    self.grid_data.clear()
                                    self.row_map.clear()
                            elif command == 'com':
                                # Comment/info message
                                self.session_info['comment'] = parsed['value']
                            elif command == 'msg':
                                # Message (best lap info etc)
                                self.session_info['message'] = parsed['value']
                            elif command == 'track':
                                # Track info
                                self.session_info['track'] = parsed['value']
                            elif command.startswith('r') and 'c' in command:
                                # This is a cell update command (e.g. r114c10|ti|17.821)
                                # The cell ID is the command, not a parameter
                                # Restructure to call process_update_message correctly
                                self.process_update_message({
                                    'command': 'update',
                                    'parameter': command,  # Cell ID like r114c10
                                    'value': f"{parsed['parameter']}|{parsed['value']}"  # type|value like ti|17.821
                                })

                        # After processing all lines, store the data
                        df = self.get_current_standings()
                        if not df.empty:
                            # Determine session_id based on leader's lap progression
                            leader_gap = ''
                            if 'Position' in df.columns and 'Gap' in df.columns:
                                leader_row = df[df['Position'].astype(str) == '1']
                                if not leader_row.empty:
                                    leader_gap = leader_row.iloc[0].get('Gap', '')

                            session_id = self.check_and_update_session(leader_gap)

                            # Only store data if we have an active session, OR create one for mid-session starts
                            if session_id is not None:
                                self.store_lap_data(session_id, df)
                                self.session_active_status = True
                                self.last_data_time = datetime.now()
                            else:
                                # No session detected - create one automatically for mid-session starts
                                self.logger.info(f"Track {self.track_id}: No session start detected, creating mid-session session")
                                session_id = self.create_new_session()
                                self.current_session_id = session_id
                                self.current_leader_lap = 1  # Assume racing lap 1 when we start monitoring
                                self.session_ended = False
                                self.session_active_status = True
                                self.last_data_time = datetime.now()
                                self.store_lap_data(session_id, df)

                    except Exception as e:
                        self.logger.error(f"Track {self.track_id}: Error processing message: {e}")
                        import traceback
                        self.logger.error(traceback.format_exc())

            except Exception as e:
                import websockets
                if isinstance(e, websockets.exceptions.ConnectionClosed):
                    self.logger.warning(f"Track {self.track_id}: WebSocket connection closed: {e}")
                else:
                    self.logger.error(f"Track {self.track_id}: WebSocket error: {e}")
                    import traceback
                    self.logger.error(traceback.format_exc())
                self.is_connected = False
                await asyncio.sleep(reconnect_delay)

    async def connect_websocket(self, ws_url: str):
        """Override to just connect without starting message loop"""
        # Call parent's connect_websocket
        return await super().connect_websocket(ws_url)

    async def cleanup(self):
        """Override cleanup to stop monitoring thread"""
        # Stop monitoring thread
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_stop_event.set()
            self.monitor_thread.join(timeout=5)

        # Call parent cleanup if it exists
        if hasattr(super(), 'cleanup'):
            await super().cleanup()

    def get_db_connection(self):
        """Get connection to track-specific database with WAL mode and timeout"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            # Enable WAL mode for better concurrent access
            conn.execute("PRAGMA journal_mode=WAL")
            # Set busy timeout to 5 seconds
            conn.execute("PRAGMA busy_timeout=5000")
            return conn
        except Exception as e:
            self.logger.error(f"Error connecting to database {self.db_path}: {e}")
            raise

    def store_lap_data(self, session_id: int, df):
        """Override to use track-specific database"""
        if df.empty:
            return

        # Update last data time for session monitoring
        self.last_data_time = datetime.now()

        timestamp = datetime.now().isoformat()
        current_records = []
        lap_history_records = []

        # Get previous state from cache, initialize if needed
        if session_id not in self.previous_state_cache:
            # First time seeing this session, initialize cache from DB
            try:
                with self.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT DISTINCT kart_number, RunTime, position, last_lap, best_lap, pit_stops
                        FROM lap_times
                        WHERE session_id = ?
                        ORDER BY timestamp DESC
                    ''', (session_id,))
                    rows = cursor.fetchall()
                    self.previous_state_cache[session_id] = {}
                    for row in rows:
                        kart_num, runtime, position_seed, last_lap, best_lap, pit_stops = row
                        # Only keep the most recent state for each kart
                        if kart_num not in self.previous_state_cache[session_id]:
                            self.previous_state_cache[session_id][kart_num] = {
                                'RunTime': runtime,
                                'position': position_seed,
                                'last_lap': last_lap,
                                'best_lap': best_lap,
                                'pit_stops': pit_stops
                            }
                    self.logger.debug(f"Track {self.track_id}: Initialized cache for session {session_id} with {len(self.previous_state_cache[session_id])} karts")
            except Exception as e:
                self.logger.warning(f"Track {self.track_id}: Error initializing cache: {e}")
                self.previous_state_cache[session_id] = {}

        previous_state = self.previous_state_cache.get(session_id, {})

        for _, row in df.iterrows():
            try:
                position = int(row['Position']) if row.get('Position', '').strip() else None
                kart = int(row['Kart']) if row.get('Kart', '').strip() else None
                # Parse RunTime from MM:SS format to seconds
                runtime_str = row.get('RunTime', '0')
                if ':' in runtime_str:
                    parts = runtime_str.split(':')
                    runtime = int(parts[0]) * 60 + int(parts[1])
                else:
                    runtime = int(runtime_str) if runtime_str.strip() else 0

                # Handle Pit Stops - can be count (e.g. "3") or time (e.g. "00:22")
                pit_stops_str = row.get('Pit Stops', '0').strip()
                if ':' in pit_stops_str:
                    # This is pit time in MM:SS format, store as 0 for count
                    pit_stops = 0
                else:
                    # This is a count
                    pit_stops = int(pit_stops_str) if pit_stops_str and pit_stops_str.isdigit() else 0

                last_lap_val = row.get('Last Lap', '')
                best_lap_val = row.get('Best Lap', '')

                # Phase: write-dedup. lap_times used to be a per-tick snapshot
                # (~44M rows per active track in 7 months because most ticks
                # carry no new information — just gap/runtime drift). Only
                # insert when something query-relevant actually changed: the
                # team's position, last lap completed, best lap, or pit stop
                # count. The first sighting of a kart in a session is always
                # recorded as a baseline.
                should_record = True
                if kart and kart in previous_state:
                    prev = previous_state[kart]
                    if (position == prev.get('position') and
                            last_lap_val == prev.get('last_lap') and
                            best_lap_val == prev.get('best_lap') and
                            pit_stops == prev.get('pit_stops')):
                        should_record = False

                if should_record:
                    current_records.append((
                        session_id,
                        timestamp,
                        position,
                        kart,
                        row.get('Team', ''),
                        last_lap_val,
                        best_lap_val,
                        row.get('Gap', ''),
                        runtime,
                        pit_stops
                    ))

                # Check for new laps using in-memory cache
                if kart and kart in previous_state:
                    prev_runtime = previous_state[kart].get('RunTime')
                    prev_last_lap = previous_state[kart].get('last_lap')

                    if runtime != prev_runtime and last_lap_val and last_lap_val != prev_last_lap:
                        lap_history_records.append((
                            session_id,
                            timestamp,
                            kart,
                            row.get('Team', ''),
                            runtime,
                            last_lap_val,
                            position,
                            pit_stops  # Use the already parsed pit_stops value
                        ))

                # Update cache with current state. `position` was added in
                # the write-dedup pass so we can compare it on the next tick.
                if kart:
                    self.previous_state_cache[session_id][kart] = {
                        'RunTime': runtime,
                        'position': position,
                        'last_lap': last_lap_val,
                        'best_lap': best_lap_val,
                        'pit_stops': pit_stops
                    }

            except Exception as e:
                self.logger.warning(f"Track {self.track_id}: Error processing row: {e}")
                self.logger.warning(f"Track {self.track_id}: Row data: {dict(row)}")
                import traceback
                self.logger.warning(f"Track {self.track_id}: Traceback: {traceback.format_exc()}")
                continue

        if current_records:
            try:
                with self.get_db_connection() as conn:
                    conn.executemany('''
                        INSERT INTO lap_times
                        (session_id, timestamp, position, kart_number, team_name,
                        last_lap, best_lap, gap, RunTime, pit_stops)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', current_records)

                    if lap_history_records:
                        conn.executemany('''
                            INSERT INTO lap_history
                            (session_id, timestamp, kart_number, team_name,
                            lap_number, lap_time, position_after_lap, pit_this_lap)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', lap_history_records)

                    conn.commit()
                    self.logger.debug(f"Track {self.track_id}: Stored {len(current_records)} records, {len(lap_history_records)} lap history records")

                # Periodically clean up old session caches (every 10 commits).
                # Previously used `session_id % 10 == 0` which triggered at most
                # once per 10 new sessions — effectively never during a single race.
                self._commit_count += 1
                if self._commit_count % 10 == 0:
                    self.cleanup_old_cache_sessions(keep_last_n=2)

                # Broadcast update to Socket.IO room for this track
                if self.socketio:
                    try:
                        # Get current standings
                        standings_df = self.get_current_standings()
                        if not standings_df.empty:
                            teams_data = standings_df.to_dict('records')

                            # Emit to track-specific room
                            room = f'track_{self.track_id}'
                            self.socketio.emit('track_update', {
                                'track_id': self.track_id,
                                'track_name': self.track_name,
                                'teams': teams_data,
                                'session_id': session_id,
                                'timestamp': timestamp
                            }, room=room)
                            self.logger.debug(f"Emitted update to room {room} with {len(teams_data)} teams")

                            # Emit team-specific updates to individual team rooms
                            self.emit_team_specific_updates(standings_df, session_id, timestamp)

                    except Exception as emit_error:
                        self.logger.error(f"Error emitting Socket.IO update: {emit_error}")

            except Exception as e:
                self.logger.error(f"Error storing lap data: {e}")

    def emit_team_specific_updates(self, standings_df: pd.DataFrame, session_id: int, timestamp: str):
        """
        Emit team-specific updates to individual team rooms.
        Each team gets position, gap to leader, relative gaps to front/behind,
        lap times, pit stops, and status.
        """
        if not self.socketio or standings_df.empty:
            return

        try:
            teams = standings_df.to_dict('records')

            def parse_gap(gap_string):
                """Convert gap string like '+12.456' or '12.456' to float"""
                if not gap_string or gap_string in ('LEADER', 'Leader', ''):
                    return 0.0
                try:
                    return float(gap_string.replace('+', '').strip())
                except (ValueError, AttributeError):
                    return 0.0

            for idx, team in enumerate(teams):
                team_name = team.get('Team', '')
                if not team_name:
                    continue

                position_str = team.get('Position', '')
                position = int(position_str) if position_str and str(position_str).isdigit() else idx + 1
                gap_str = team.get('Gap', '')
                current_gap = parse_gap(gap_str)

                # Gap to front: difference between our gap-to-leader and front car's gap-to-leader
                if position > 1 and idx > 0:
                    front_gap = parse_gap(teams[idx - 1].get('Gap', ''))
                    diff = current_gap - front_gap
                    gap_to_front = f"{diff:.3f}"
                else:
                    gap_to_front = '-'

                # Gap to behind: difference between behind car's gap-to-leader and ours
                if idx < len(teams) - 1:
                    behind_gap = parse_gap(teams[idx + 1].get('Gap', ''))
                    diff = behind_gap - current_gap
                    gap_to_behind = f"{diff:.3f}"
                else:
                    gap_to_behind = '-'

                team_update = {
                    'Position': str(position),
                    'Gap': gap_str,
                    'gap_to_front': gap_to_front,
                    'gap_to_behind': gap_to_behind,
                    'Last Lap': team.get('Last Lap', ''),
                    'Best Lap': team.get('Best Lap', ''),
                    'Pit Stops': team.get('Pit Stops', '0'),
                    'Status': team.get('Status', 'On Track'),
                }

                room = f'team_track_{self.track_id}_{team_name}'
                self.socketio.emit('team_specific_update', team_update, room=room)

        except Exception as e:
            self.logger.error(f"Error emitting team-specific updates: {e}")

    def extract_lap_number(self, gap_value: str) -> Optional[int]:
        """Extract lap number from gap field (e.g., 'Tour 5' -> 5)"""
        if not gap_value:
            return None

        try:
            if gap_value.startswith('Tour '):
                return int(gap_value[5:])
            elif gap_value.startswith('Lap '):
                return int(gap_value[4:])
        except (ValueError, IndexError):
            pass

        return None

    def check_and_update_session(self, leader_gap: str) -> Optional[int]:
        """
        Decide which session_id to write to.

        Triggers a new session when ANY of:
          (a) no session yet,
          (b) leader's lap reset to 1 from a higher number (classic boundary),
          (c) the old session was already flagged ended (5-minute lap-stale),
          (d) more than SESSION_GAP_THRESHOLD elapsed since the last lap update
              (websocket reconnect after a long quiet — new race may already
              be mid-flight, so we can't rely on seeing lap=1).

        Without (d), reconnects after multi-hour gaps silently appended new
        race data onto stale session_ids, producing the "merged-week"
        sessions in the historical data.
        """
        current_lap = self.extract_lap_number(leader_gap)
        current_time = datetime.now()

        # Without a lap number we have nothing to anchor on; preserve current
        # session and wait for the next packet that includes one.
        if current_lap is None:
            return self.current_session_id

        # (d) Long activity gap → new race event, regardless of current lap.
        if (self.current_session_id is not None
                and self.last_lap_change_time is not None
                and not self.session_ended):
            gap_seconds = (current_time - self.last_lap_change_time).total_seconds()
            if gap_seconds > self.SESSION_GAP_THRESHOLD:
                self.logger.info(
                    f"Track {self.track_id}: gap of {gap_seconds:.0f}s since last lap update "
                    f"(>{self.SESSION_GAP_THRESHOLD}s) — closing session #{self.current_session_id}"
                )
                self.session_ended = True

        # Open a new session if any of the boundary conditions hold.
        lap_reset_from_higher = (
            current_lap == 1
            and self.current_leader_lap is not None
            and self.current_leader_lap > 1
        )
        needs_new_session = (
            self.current_session_id is None
            or lap_reset_from_higher
            or self.session_ended
        )

        if needs_new_session:
            reason = (
                "no current session" if self.current_session_id is None
                else "lap reset to 1" if lap_reset_from_higher
                else "previous session ended (stale or gap)"
            )
            self.logger.info(
                f"Track {self.track_id}: starting new session ({reason}; "
                f"current_lap={current_lap}, prev_lap={self.current_leader_lap})"
            )
            self.current_session_id = self.create_new_session()
            self.current_leader_lap = current_lap
            self.last_lap_change_time = current_time
            self.session_ended = False
            return self.current_session_id

        # Continuing in the same session — update lap progression.
        if current_lap != self.current_leader_lap:
            self.current_leader_lap = current_lap
            self.last_lap_change_time = current_time
            # session_ended stays False; we already opened a new session
            # above if a real boundary fired.
        else:
            # Same lap — check stale-lap timeout (legacy 5-minute check).
            if self.last_lap_change_time:
                time_on_same_lap = (current_time - self.last_lap_change_time).total_seconds()
                if time_on_same_lap > self.STALE_LAP_THRESHOLD and not self.session_ended:
                    self.logger.info(
                        f"Track {self.track_id}: lap {current_lap} stale for {time_on_same_lap:.0f}s — "
                        f"session #{self.current_session_id} marked ended"
                    )
                    self.session_ended = True

        return self.current_session_id

    def create_new_session(self) -> int:
        """Create a new session and return its ID"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()

                timestamp = datetime.now().isoformat()
                session_name = f"{self.track_name} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

                cursor.execute('''
                    INSERT INTO race_sessions (start_time, name, track)
                    VALUES (?, ?, ?)
                ''', (timestamp, session_name, self.track_name))

                session_id = cursor.lastrowid
                conn.commit()

                self.logger.info(f"Track {self.track_id}: Created new session {session_id}: {session_name}")
                return session_id

        except Exception as e:
            self.logger.error(f"Track {self.track_id}: Error creating new session: {e}")
            return 1  # Fallback

    def create_or_get_session(self, session_name: str, track_name: str) -> int:
        """Override to use track-specific database"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()

                # Check if there's an active session
                cursor.execute('''
                    SELECT session_id FROM race_sessions
                    WHERE name = ? AND track = ?
                    ORDER BY session_id DESC LIMIT 1
                ''', (session_name, track_name))

                result = cursor.fetchone()

                if result:
                    session_id = result[0]
                    self.logger.info(f"Using existing session {session_id}")
                else:
                    # Create new session
                    cursor.execute('''
                        INSERT INTO race_sessions (start_time, name, track)
                        VALUES (?, ?, ?)
                    ''', (datetime.now().isoformat(), session_name, track_name))
                    session_id = cursor.lastrowid
                    conn.commit()
                    self.logger.info(f"Created new session {session_id}")

                return session_id
        except Exception as e:
            self.logger.error(f"Error creating/getting session: {e}")
            return 1  # Fallback
