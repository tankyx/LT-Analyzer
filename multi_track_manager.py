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
            if track.get('column_mappings'):
                try:
                    mappings = json.loads(track['column_mappings'])
                    parser.set_column_mappings(mappings)
                except:
                    pass

            self.parsers[track_id] = parser

            # Start the parser
            self.logger.info(f"Starting parser for track {track_id} ({track_name}): {websocket_url}")
            await parser.connect_websocket(websocket_url)

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

    async def connect_websocket(self, ws_url: str):
        """Override to start session monitoring after connection"""
        # Call parent's connect_websocket
        await super().connect_websocket(ws_url)

        # Start session monitoring thread
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_stop_event.clear()
            self.monitor_thread = threading.Thread(
                target=self.start_session_monitoring,
                name=f"SessionMonitor-Track{self.track_id}",
                daemon=True
            )
            self.monitor_thread.start()
            self.logger.info(f"Started session monitoring for track {self.track_id} ({self.track_name})")

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
                    int(row.get('Pit Stops', '0'))
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
                                int(row.get('Pit Stops', '0'))
                            ))

            except Exception as e:
                self.logger.warning(f"Error processing row {row}: {e}")
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
                    self.logger.debug(f"Stored {len(current_records)} records, {len(lap_history_records)} lap history records")

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
