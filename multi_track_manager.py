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
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_times_session_time
                    ON lap_times(session_id, timestamp DESC)
                ''')

                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_times_session_kart
                    ON lap_times(session_id, kart_number, timestamp DESC)
                ''')

                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_times_team_session
                    ON lap_times(team_name, session_id)
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
            except Exception:
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
                        SELECT DISTINCT kart_number, RunTime, last_lap, best_lap, pit_stops
                        FROM lap_times
                        WHERE session_id = ?
                        ORDER BY timestamp DESC
                    ''', (session_id,))
                    rows = cursor.fetchall()
                    self.previous_state_cache[session_id] = {}
                    for row in rows:
                        kart_num, runtime, last_lap, best_lap, pit_stops = row
                        # Only keep the most recent state for each kart
                        if kart_num not in self.previous_state_cache[session_id]:
                            self.previous_state_cache[session_id][kart_num] = {
                                'RunTime': runtime,
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

                current_records.append((
                    session_id,
                    timestamp,
                    position,
                    kart,
                    row.get('Team', ''),
                    row.get('Last Lap', ''),
                    row.get('Best Lap', ''),
                    row.get('Gap', ''),
                    runtime,
                    pit_stops
                ))

                # Check for new laps using in-memory cache
                if kart and kart in previous_state:
                    prev_runtime = previous_state[kart]['RunTime']
                    prev_last_lap = previous_state[kart]['last_lap']
                    current_last_lap = row.get('Last Lap', '')

                    if runtime != prev_runtime and current_last_lap and current_last_lap != prev_last_lap:
                        lap_history_records.append((
                            session_id,
                            timestamp,
                            kart,
                            row.get('Team', ''),
                            runtime,
                            current_last_lap,
                            position,
                            pit_stops  # Use the already parsed pit_stops value
                        ))

                # Update cache with current state
                if kart:
                    self.previous_state_cache[session_id][kart] = {
                        'RunTime': runtime,
                        'last_lap': row.get('Last Lap', ''),
                        'best_lap': row.get('Best Lap', ''),
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

                # Periodically clean up old session caches (every 10 commits)
                if len(current_records) > 0 and session_id % 10 == 0:
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
        Each team gets their position, lap times, pit stops, runtime, and gaps to other teams.
        """
        if not self.socketio or standings_df.empty:
            return

        try:
            # Convert standings to list of dicts for easier processing
            teams = standings_df.to_dict('records')

            # Process each team
            for idx, team in enumerate(teams):
                team_name = team.get('Team', '')
                if not team_name:
                    continue

                # Extract team data
                position_str = team.get('Position', '')
                position = int(position_str) if position_str and str(position_str).isdigit() else idx + 1

                kart = team.get('Kart', '')
                status = team.get('Status', 'On Track')
                last_lap = team.get('Last Lap', '')
                best_lap = team.get('Best Lap', '')
                runtime = team.get('RunTime', '')
                pit_stops = team.get('Pit Stops', '0')
                gap_str = team.get('Gap', '')

                # Calculate gaps
                gap_to_leader = gap_str if gap_str else '0.000' if position == 1 else ''
                gap_to_front = None
                gap_to_behind = None

                # Parse gap values for calculations
                def parse_gap(gap_string):
                    """Convert gap string like '+12.456' or '12.456' to float"""
                    if not gap_string or gap_string in ['LEADER', 'Leader', '']:
                        return 0.0
                    # Remove + sign and convert to float
                    try:
                        return float(gap_string.replace('+', '').strip())
                    except (ValueError, AttributeError):
                        return 0.0

                current_gap = parse_gap(gap_str)

                # Calculate gap to front (team ahead)
                if position > 1 and idx > 0:
                    front_team = teams[idx - 1]
                    front_gap = parse_gap(front_team.get('Gap', ''))
                    gap_diff = current_gap - front_gap
                    gap_to_front = f"+{gap_diff:.3f}" if gap_diff > 0 else f"{gap_diff:.3f}"

                # Calculate gap to behind (team behind)
                if idx < len(teams) - 1:
                    behind_team = teams[idx + 1]
                    behind_gap = parse_gap(behind_team.get('Gap', ''))
                    gap_diff = behind_gap - current_gap
                    gap_to_behind = f"-{gap_diff:.3f}" if gap_diff > 0 else f"{gap_diff:.3f}"

                # Count total laps from database
                try:
                    with self.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT COUNT(DISTINCT lap_number)
                            FROM lap_history
                            WHERE session_id = ? AND team_name = ?
                        ''', (session_id, team_name))
                        result = cursor.fetchone()
                        total_laps = result[0] if result else 0
                except Exception as e:
                    self.logger.error(f"Error getting lap count for {team_name}: {e}")
                    total_laps = 0

                # Prepare team-specific update payload
                team_update = {
                    'track_id': self.track_id,
                    'track_name': self.track_name,
                    'team_name': team_name,
                    'position': position,
                    'kart': kart,
                    'status': status,
                    'last_lap': last_lap,
                    'best_lap': best_lap,
                    'total_laps': total_laps,
                    'runtime': runtime,
                    'gap_to_leader': gap_to_leader,
                    'gap_to_front': gap_to_front,
                    'gap_to_behind': gap_to_behind,
                    'pit_stops': pit_stops,
                    'session_id': session_id,
                    'timestamp': timestamp
                }

                # Emit to team-specific room
                room = f'team_track_{self.track_id}_{team_name}'
                self.socketio.emit('team_specific_update', team_update, room=room)
                self.logger.debug(f"Emitted team update to room {room} for position {position}")

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
        Check if session should change based on leader's lap number.
        Returns the current session_id to use for data storage, or None if no session should be active.
        """
        current_lap = self.extract_lap_number(leader_gap)
        current_time = datetime.now()

        # If we can't determine lap number, don't create a session
        # Wait until we see Tour 1 to start tracking
        if current_lap is None:
            return self.current_session_id  # Return existing session or None

        # Detect new session start (lap resets to 1)
        if current_lap == 1:
            # Only create new session if:
            # 1. No current session exists, OR
            # 2. Previous lap was > 1 (actual reset), OR
            # 3. Current session was marked as ended
            if (self.current_session_id is None or
                (self.current_leader_lap is not None and self.current_leader_lap > 1) or
                self.session_ended):

                self.logger.info(f"Track {self.track_id}: Detected new session start (lap reset to 1)")
                self.current_session_id = self.create_new_session()
                self.current_leader_lap = 1
                self.last_lap_change_time = current_time
                self.session_ended = False
                return self.current_session_id

        # Track lap progression
        if current_lap != self.current_leader_lap:
            # Lap number changed - racing is active
            self.current_leader_lap = current_lap
            self.last_lap_change_time = current_time
            self.session_ended = False
        else:
            # Same lap number - check if it's been stale too long
            if self.last_lap_change_time:
                time_on_same_lap = (current_time - self.last_lap_change_time).total_seconds()

                if time_on_same_lap > self.STALE_LAP_THRESHOLD and not self.session_ended:
                    self.logger.info(f"Track {self.track_id}: Session ended (lap {current_lap} stale for {time_on_same_lap:.0f}s)")
                    self.session_ended = True

        # Return current session (may be None if no session started yet)
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
