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
            with sqlite3.connect(db_path) as conn:
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
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_times_session
                    ON lap_times(session_id, timestamp)
                ''')

                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_times_team
                    ON lap_times(team_name, session_id)
                ''')

                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_lap_history_session
                    ON lap_history(session_id, lap_number)
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

        # Now call parent init which will call setup_database()
        super().__init__()

    def setup_database(self):
        """Override to use track-specific database"""
        # Database is already initialized by MultiTrackManager
        # Don't create tables here, just log
        self.logger.debug(f"Using database: {self.db_path}")

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
        # Create/get session ID
        session_id = self.create_or_get_session(f"{self.track_name} - Live Session", self.track_name)
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
        """Get connection to track-specific database"""
        try:
            return sqlite3.connect(self.db_path)
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

        try:
            with self.get_db_connection() as conn:
                import pandas as pd
                previous_state = pd.read_sql_query('''
                    SELECT kart_number, RunTime, last_lap, best_lap, pit_stops
                    FROM lap_times
                    WHERE session_id = ?
                    ORDER BY timestamp DESC
                ''', conn, params=(session_id,))
        except:
            import pandas as pd
            previous_state = pd.DataFrame()

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

                # Check for new laps
                if not previous_state.empty:
                    prev_kart_state = previous_state[previous_state['kart_number'] == kart]
                    if not prev_kart_state.empty:
                        prev_runtime = prev_kart_state.iloc[0]['RunTime']
                        prev_last_lap = prev_kart_state.iloc[0]['last_lap']
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
