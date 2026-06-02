import asyncio
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime, timedelta
from collections import deque
import random
import math
import hashlib
import hmac
import secrets
import sqlite3
from functools import wraps

import bcrypt
from flask import Flask, has_request_context, jsonify, request, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.middleware.proxy_fix import ProxyFix

from apex_timing_websocket import ApexTimingWebSocketParser
from database_manager import TrackDatabase
from email_service import (
    get_email_sender,
    send_password_reset_email,
    send_verification_email,
    send_welcome_email,
)
from multi_track_manager import MultiTrackManager
from turnstile import require_turnstile


def _parse_cors_origins():
    raw = os.environ.get('CORS_ORIGINS', '')
    origins = [o.strip() for o in raw.split(',') if o.strip()]
    if not origins:
        # Fallback for local dev only; production MUST set CORS_ORIGINS.
        origins = ['http://localhost:3000']
    return origins


CORS_ORIGINS = _parse_cors_origins()

# Flask secret key: must be stable across restarts so sessions survive deploys.
# Fail loudly if not configured in production to avoid silently regenerating on every restart.
_secret = os.environ.get('FLASK_SECRET_KEY')
if not _secret:
    if os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError('FLASK_SECRET_KEY environment variable is required in production')
    _secret = secrets.token_hex(32)
    print('WARNING: FLASK_SECRET_KEY not set — generated an ephemeral key. Sessions will not survive restart.')

# Initialize Flask app
app = Flask(__name__)
app.secret_key = _secret
# Trust nginx's X-Forwarded-{For,Proto} so request.remote_addr is the real
# client IP (rate-limit keys depend on this) and request.scheme reflects HTTPS.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
_SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=_SESSION_COOKIE_SECURE,
    PREFERRED_URL_SCHEME='https',
)
CORS(app,
     origins=CORS_ORIGINS,
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# Initialize SocketIO — mirror the HTTP CORS whitelist (no wildcards).
socketio = SocketIO(
    app,
    cors_allowed_origins=CORS_ORIGINS,
    async_mode='threading',
    logger=False,
    engineio_logger=False,
    ping_interval=25,  # Send ping every 25 seconds
    ping_timeout=60    # Wait 60 seconds for pong response
)


# -- Password hashing helpers ------------------------------------------------
# bcrypt is the canonical store. Legacy SHA256 hashes (64 hex chars) are
# transparently accepted at login and upgraded to bcrypt on successful auth.

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def _looks_like_bcrypt(stored: str) -> bool:
    return isinstance(stored, str) and stored.startswith(('$2a$', '$2b$', '$2y$'))


def verify_password(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    if _looks_like_bcrypt(stored_hash):
        try:
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        except (ValueError, TypeError):
            return False
    # Legacy SHA256 (64 hex chars). Constant-time compare.
    legacy = hashlib.sha256(password.encode('utf-8')).hexdigest()
    return hmac.compare_digest(legacy, stored_hash)

# Initialize track database
track_db = TrackDatabase()

REQUIRED_PIT_STOPS = 7
PIT_STOP_TIME = 158
DEFAULT_LAP_TIME = 90.0  # Default lap time in seconds when no data available

# Simulation configuration
SIMULATION_MODE = False
NUM_TEAMS = 40
TRACK_LENGTH_METERS = 1375  # Typical karting track length
BASE_LAP_TIME_SECONDS = 73  # Base lap time around 1'13 (73 seconds)
LAP_TIME_VARIANCE = 1.0     # Variance in seconds to add randomness
MAX_RACE_TIME_SECONDS = 60 * 60 * 3  # 3 hours race
PIT_STOP_INTERVAL_MIN = 9  # Min laps between pit stops
PIT_STOP_INTERVAL_MAX = 47  # Max laps between pit stops
PIT_STOP_DURATION = 35      # Pit stop duration in seconds (more realistic)
PIT_STOP_CHANCE = 0.001      # Random chance of an early pit stop per lap

race_data = {
    'teams': [],
    'session_info': {},
    'last_update': None,
    'my_team': None,
    'monitored_teams': [],
    'delta_times': {},
    'gap_history': {},
    'pit_config': {
        'required_stops': REQUIRED_PIT_STOPS,
        'pit_time': PIT_STOP_TIME,
        'default_lap_time': DEFAULT_LAP_TIME
    },
    'race_time': 0,
    'is_running': False,
    'simulation_mode': SIMULATION_MODE,
    'timing_url': None  # Store the timing URL
}

# Create our parser
parser = None
update_thread = None
stop_event = threading.Event()
simulation_teams = []

# Multi-track manager for monitoring all tracks simultaneously
multi_track_manager = None
multi_track_loop = None
multi_track_thread = None

# WebSocket tracking
connected_clients = set()
connected_clients_lock = threading.Lock()
last_race_data_hash = None


# --- Tiny in-process TTL cache (Phase 3) -----------------------------------
# Used to wrap expensive read endpoints (top-teams, cross-track-sessions,
# search-all). Single-process Werkzeug means a plain dict + lock suffices.
# When we move to multi-worker gunicorn this needs to become Redis or similar.

_query_cache: dict = {}
_query_cache_lock = threading.Lock()
QUERY_CACHE_TTL_SECONDS = int(os.environ.get('QUERY_CACHE_TTL_SECONDS', '60'))
_query_cache_stats = {'hits': 0, 'misses': 0, 'evictions': 0}


def _cache_get(key: str):
    with _query_cache_lock:
        entry = _query_cache.get(key)
        if entry is None:
            _query_cache_stats['misses'] += 1
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del _query_cache[key]
            _query_cache_stats['evictions'] += 1
            _query_cache_stats['misses'] += 1
            return None
        _query_cache_stats['hits'] += 1
        return value


def _cache_put(key: str, value, ttl: int | None = None):
    expires_at = time.time() + (ttl if ttl is not None else QUERY_CACHE_TTL_SECONDS)
    with _query_cache_lock:
        _query_cache[key] = (expires_at, value)


def _cache_invalidate_prefix(prefix: str):
    """Drop any entry whose key starts with `prefix`. Use after admin writes
    that would otherwise serve stale data (e.g. delete-best-lap, mass-delete)."""
    with _query_cache_lock:
        for k in [k for k in _query_cache if k.startswith(prefix)]:
            del _query_cache[k]


def _internal_error(exc: Exception, context: str = 'request'):
    """Log full error server-side, return a generic JSON error to the client.

    Avoids leaking SQL errors, stack frames, or file paths to API consumers.
    UnknownTrackError is surfaced as a proper 404 instead of a masked 500.
    """
    # Surface domain errors that already carry a user-facing message.
    # Defined at module scope below; referenced by name to sidestep import order.
    if isinstance(exc, UnknownTrackError):
        return jsonify({'error': str(exc)}), 404

    app.logger.error('%s failed: %s', context, exc, exc_info=True)
    # Also print for pm2 capture even if app.logger isn't configured.
    print(f'[ERROR] {context}: {exc}')
    traceback.print_exc()
    return jsonify({'error': 'An internal error occurred'}), 500

# WebSocket connection handlers
@socketio.on('connect')
def handle_connect(auth=None):
    """Handle client connection.

    If the connecting client carries a valid session cookie (web dashboard
    or a logged-in Android device), auto-join that user to their personal
    `user_{id}` room. Per-user events like pit_alert emit to that room so
    only the operator who set the alert is notified — not every device
    that happens to be monitoring the same team.

    Anonymous Socket.IO connections still work (e.g. read-only viewers),
    they just miss any user-targeted events until they log in and
    reconnect.
    """
    print(f"Client connected: {request.sid}")
    with connected_clients_lock:
        connected_clients.add(request.sid)
    join_room('race_updates')

    # Per-user room join, best-effort. session.get reads the signed Flask
    # session cookie so Socket.IO connections from the dashboard (same
    # origin) AND from the Android app (which authenticates via
    # POST /api/auth/login and passes the session cookie on connect)
    # both land here.
    user_id = None
    try:
        session_id = session.get('session_id')
        user = verify_session(session_id) if session_id else None
        if user:
            user_id = user['id']
            join_room(f'user_{user_id}')
            print(f"  -> identified as user_id={user_id} ({user['username']}); joined user_{user_id}")
            # Send an explicit confirmation event so the Android client can
            # log which user-id it's bound to (useful for debugging "why am
            # I not getting pit alerts" reports).
            emit('session_identified', {
                'user_id': user_id,
                'username': user['username'],
                'room': f'user_{user_id}',
            })
    except Exception as e:
        print(f"  -> session lookup failed: {e}")

    # Send current race data on connect. As of Phase 2 we no longer ship
    # my_team / monitored_teams / pit_config / delta_times / gap_history in
    # the broadcast payload — those are per-user and live behind /api/me/prefs.
    # The frontend hydrates them from there on track change.
    emit('race_data_update', {
        'teams': race_data['teams'],
        'session_info': race_data['session_info'],
        'last_update': race_data['last_update'],
        'simulation_mode': race_data['simulation_mode'],
        'timing_url': race_data['timing_url'],
        'is_running': race_data['is_running'],
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f"Client disconnected: {request.sid}")
    with connected_clients_lock:
        connected_clients.discard(request.sid)
    leave_room('race_updates')
    leave_room('standings_stream')

@socketio.on('join_track')
def handle_join_track(data):
    """Handle client joining a track-specific room.

    After joining, emit a snapshot of the track's current standings so the
    client doesn't show empty/stale data while waiting for the next periodic
    broadcast (which only fires when the upstream WebSocket pushes new lap
    data — could be a long wait if the track is idle).
    """
    track_id = data.get('track_id')
    if not track_id:
        return
    room = f'track_{track_id}'
    join_room(room)
    print(f"Client {request.sid} joined {room}")
    emit('track_joined', {'track_id': track_id})

    # Best-effort snapshot. Never block the join on this.
    try:
        if multi_track_manager and track_id in multi_track_manager.parsers:
            parser = multi_track_manager.parsers[track_id]
            if hasattr(parser, 'get_current_standings'):
                standings_df = parser.get_current_standings()
                teams_data = standings_df.to_dict('records') if not standings_df.empty else []
                emit('track_update', {
                    'track_id': track_id,
                    'track_name': getattr(parser, 'track_name', None),
                    'teams': teams_data,
                    'session_id': getattr(parser, 'current_session_id', None),
                    'timestamp': datetime.now().isoformat(),
                })
    except Exception as snapshot_err:  # pragma: no cover — defensive
        print(f"join_track snapshot failed for track {track_id}: {snapshot_err}")

@socketio.on('leave_track')
def handle_leave_track(data):
    """Handle client leaving a track-specific room"""
    track_id = data.get('track_id')
    if track_id:
        room = f'track_{track_id}'
        leave_room(room)
        print(f"Client {request.sid} left {room}")

@socketio.on('join_all_tracks')
def handle_join_all_tracks():
    """Handle client joining the all_tracks room for multi-track status updates"""
    join_room('all_tracks')
    print(f"Client {request.sid} joined all_tracks room")

    # Send initial status for all tracks
    global multi_track_manager
    if multi_track_manager:
        tracks_status = multi_track_manager.get_all_tracks_status()
        emit('all_tracks_status', {
            'tracks': tracks_status,
            'timestamp': datetime.now().isoformat()
        })

@socketio.on('leave_all_tracks')
def handle_leave_all_tracks():
    """Handle client leaving the all_tracks room"""
    leave_room('all_tracks')
    print(f"Client {request.sid} left all_tracks room")


@socketio.on('subscribe_user_prefs')
def handle_subscribe_user_prefs(data):
    """Phase 2.5: join a per-user room so the client receives prefs_updated
    notifications when any of their other tabs/devices write new prefs.

    The user_id comes from the client (which already authenticated via HTTP).
    A spoofed user_id only lets someone receive "you should re-fetch" pings
    for that user — the actual prefs themselves still require the HTTP session
    cookie to fetch, so this is informational, not authoritative.
    """
    try:
        user_id = int((data or {}).get('user_id'))
    except (TypeError, ValueError):
        return
    if user_id <= 0:
        return
    room = f'user_prefs_{user_id}'
    join_room(room)
    print(f"Client {request.sid} joined {room}")


@socketio.on('unsubscribe_user_prefs')
def handle_unsubscribe_user_prefs(data):
    try:
        user_id = int((data or {}).get('user_id'))
    except (TypeError, ValueError):
        return
    leave_room(f'user_prefs_{user_id}')

@socketio.on('join_team_room')
def handle_join_team_room(data):
    """Handle client joining a team-specific room for a track"""
    track_id = data.get('track_id')
    team_name = data.get('team_name')

    if not track_id or not team_name:
        emit('team_room_error', {
            'error': 'Both track_id and team_name are required',
            'timestamp': datetime.now().isoformat()
        })
        return

    try:
        # Validate track exists
        track_info = track_db.get_track_by_id(track_id)
        if not track_info:
            emit('team_room_error', {
                'error': f'Track {track_id} not found',
                'timestamp': datetime.now().isoformat()
            })
            return

        # Join the team-specific room (no team validation - allow subscribing
        # before data arrives so clients receive updates as soon as racing starts)
        room = f'team_track_{track_id}_{team_name}'
        join_room(room)
        print(f"Client {request.sid} joined team room: {room}")

        # Send confirmation with team and track info
        emit('team_room_joined', {
            'track_id': track_id,
            'track_name': track_info['track_name'],
            'team_name': team_name,
            'room': room,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        app.logger.exception('Error handling join_team_room')
        print(f"Error handling join_team_room: {e}")
        emit('team_room_error', {
            'error': 'Failed to join team room',
            'timestamp': datetime.now().isoformat()
        })

@socketio.on('leave_team_room')
def handle_leave_team_room(data):
    """Handle client leaving a team-specific room"""
    track_id = data.get('track_id')
    team_name = data.get('team_name')

    if not track_id or not team_name:
        emit('team_room_error', {
            'error': 'Both track_id and team_name are required',
            'timestamp': datetime.now().isoformat()
        })
        return

    room = f'team_track_{track_id}_{team_name}'
    leave_room(room)
    print(f"Client {request.sid} left team room: {room}")

    emit('team_room_left', {
        'track_id': track_id,
        'team_name': team_name,
        'room': room,
        'timestamp': datetime.now().isoformat()
    })

@socketio.on('subscribe_standings')
def handle_standings_subscription(data=None):
    """Handle subscription to standings stream with deltas"""
    print(f"Client {request.sid} subscribed to standings stream")
    join_room('standings_stream')
    
    # Send initial standings with all teams
    standings_data = get_standings_with_deltas()
    emit('standings_update', {
        'type': 'initial',
        'standings': standings_data,
        'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]
    })

@socketio.on('unsubscribe_standings')
def handle_standings_unsubscription():
    """Handle unsubscription from standings stream"""
    print(f"Client {request.sid} unsubscribed from standings stream")
    leave_room('standings_stream')

@socketio.on('request_team_delta')
def handle_team_delta_request(data):
    """Handle request for specific team delta information"""
    team_number = data.get('team_number')
    if not team_number:
        emit('error', {'message': 'Team number required'})
        return
    
    # Get delta info for specific team
    delta_info = get_team_delta_info(str(team_number))
    emit('team_delta_response', {
        'team_number': team_number,
        'delta_info': delta_info,
        'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]
    })

def emit_race_update(update_type='full', data=None):
    """Emit race data updates to all connected clients"""
    with connected_clients_lock:
        if not connected_clients:
            return
    
    # Only emit if we have actual data to send
    if not race_data.get('teams') and update_type != 'custom':
        return
    
    # Emit standings update to subscribers
    if update_type in ['full', 'teams'] and race_data.get('teams'):
        emit_standings_update()
        
    if update_type == 'full':
        # Phase 2: per-user state (my_team / monitored_teams / pit_config /
        # delta_times / gap_history) is no longer broadcast — it lives behind
        # /api/me/prefs and the frontend hydrates it on track change.
        socketio.emit('race_data_update', {
            'teams': race_data['teams'],
            'session_info': race_data['session_info'],
            'last_update': race_data['last_update'],
            'simulation_mode': race_data['simulation_mode'],
            'timing_url': race_data['timing_url'],
            'is_running': race_data['is_running'],
        }, room='race_updates')
    elif update_type == 'teams' and race_data.get('teams'):
        socketio.emit('teams_update', {
            'teams': race_data['teams'],
            'last_update': race_data['last_update']
        }, room='race_updates')
    # Note: 'gaps' update_type is a no-op after Phase 2. Server no longer
    # computes deltas; frontend derives them client-side from `teams`.
    elif update_type == 'session' and race_data.get('session_info'):
        socketio.emit('session_update', {
            'session_info': race_data['session_info']
        }, room='race_updates')
    elif update_type == 'custom' and data:
        socketio.emit(data['event'], data['payload'], room='race_updates')

# Team class for simulation
class Team:
    def __init__(self, kart_num, team_name, skill_level):
        self.kart_num = kart_num
        self.team_name = team_name
        self.skill_level = skill_level  # 0.9 to 1.1 (1.0 is average)
        self.position = 0
        self.last_position = 0
        self.last_lap = "0:00.000"
        self.best_lap = "0:00.000"
        self.best_lap_seconds = 999
        self.gap = "0.000"
        self.gap_seconds = 0
        self.run_time = "0:00"
        self.run_time_seconds = 0
        self.pit_stops = 0
        self.total_laps = 0
        self.next_pit_in = random.randint(PIT_STOP_INTERVAL_MIN, PIT_STOP_INTERVAL_MAX)
        self.in_pits = False
        self.pit_time_remaining = 0
        self.total_distance = 0
        self.status = "On Track"
        self.status_duration = 0
        self.last_lap_seconds = 0
        self.consistency = random.uniform(0.98, 0.99)
        self.tire_wear = 1.0
        self.fuel_level = 1.0
        self.race_finished = False
        
    def to_dict(self):
        return {
            'Kart': str(self.kart_num),
            'Team': self.team_name,
            'Position': str(self.position),
            'Last Lap': self.last_lap,
            'Best Lap': self.best_lap,
            'Gap': self.gap,
            'RunTime': self.run_time,
            'Pit Stops': str(self.pit_stops),
            'Status': self.status
        }
        
    def format_time(self, seconds):
        """Format seconds to M:SS.sss (e.g. 1:23.456)."""
        minutes = int(seconds // 60)
        seconds_remainder = seconds % 60
        return f"{minutes}:{seconds_remainder:06.3f}"
        
    def format_runtime(self, seconds):
        """Format seconds to MM:SS"""
        minutes = int(seconds // 60)
        seconds_remainder = int(seconds % 60)
        return f"{minutes}:{seconds_remainder:02d}"
        
    def calculate_lap_time(self):
        """Calculate a realistic lap time based on skill and conditions"""
        if self.status_duration > 0:
            self.status_duration -= 1
            if self.status_duration == 0 and self.status in ["Up", "Down", "Pit-out"]:
                self.status = "On Track"
        
        if self.race_finished:
            self.status = "Finished"
            return 999
            
        if self.in_pits:
            return 999  # In pits, no lap time
        
        # Base lap time modified by skill level (72-74 seconds for 1'12-1'14)
        base_time = random.uniform(72, 74) / self.skill_level
        
        # Add some random variation
        variation = random.uniform(-LAP_TIME_VARIANCE, LAP_TIME_VARIANCE)
        
        # Add effects of tire wear and fuel
        tire_effect = (1.0 - self.tire_wear) * 2
        fuel_effect = (1.0 - self.fuel_level) * -0.5
        
        # Calculate lap time
        lap_time = base_time + variation + tire_effect + fuel_effect
        
        # Ensure consistency between laps
        if self.last_lap_seconds > 0:
            lap_time = (lap_time * (1.0 - self.consistency)) + (self.last_lap_seconds * self.consistency)
        
        # Check if pit stop is needed
        self.next_pit_in -= 1
        self.tire_wear -= random.uniform(0.01, 0.03)
        self.fuel_level -= random.uniform(0.02, 0.04)
        
        if self.next_pit_in <= 0 or random.random() < PIT_STOP_CHANCE:
            self.in_pits = True
            self.pit_time_remaining = PIT_STOP_DURATION
            self.pit_stops += 1
            self.status = "Pit-in"
            return 999
        
        return lap_time

    def update_position(self, new_position):
        """Update the team's position and set status accordingly"""
        if new_position != self.position:
            self.position = new_position
            if self.last_position != 0 and not self.in_pits:
                if new_position < self.last_position:
                    self.status = "Up"
                    self.status_duration = 5
                elif new_position > self.last_position:
                    self.status = "Down"
                    self.status_duration = 5
            self.last_position = new_position

# Function to calculate trends in gaps
def calculate_trend(current_gap, previous_gaps):
    """Calculate trend and determine arrow type based on gap change
    Returns: (trend_value, arrow_type)
    trend_value: negative means we're catching up
    arrow_type: 1, 2, or 3 for single, double, triple arrow"""
    # Need at least 2 laps to show a trend
    if len(previous_gaps) < 2:
        return 0, 0
    
    # Calculate average of previous gaps
    avg_previous = sum(previous_gaps) / len(previous_gaps)
    trend = current_gap - avg_previous
    
    # Determine arrow type based on trend magnitude
    if abs(trend) < 0.5:
        arrow = 1
    elif abs(trend) < 1.0:
        arrow = 2
    else:
        arrow = 3
        
    return trend, arrow

# Function to get average lap time from recent race data
def get_average_lap_time(session_id=None, kart_numbers=None, default=None):
    """Calculate average lap time from recent laps in the database
    
    Args:
        session_id: Specific session to calculate from (None for current)
        kart_numbers: List of kart numbers to include (None for all)
        default: Default lap time if no valid data found (uses DEFAULT_LAP_TIME if None)
    
    Returns:
        Average lap time in seconds
    """
    if default is None:
        default = DEFAULT_LAP_TIME
    
    try:
        with sqlite3.connect('race_data.db') as conn:
            query = """
                SELECT lap_time
                FROM lap_history
                WHERE lap_time IS NOT NULL
                AND lap_time != ''
                AND lap_time NOT LIKE '%Tour%'
            """
            params = []

            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)

            if kart_numbers:
                placeholders = ','.join(['?' for _ in kart_numbers])
                query += f" AND kart_number IN ({placeholders})"
                params.extend(kart_numbers)

            query += " ORDER BY id DESC LIMIT 50"
            lap_times = conn.execute(query, params).fetchall()

        if not lap_times:
            return default
        
        # Convert lap times to seconds
        total_seconds = 0
        valid_count = 0
        
        for (lap_time,) in lap_times:
            try:
                # Parse time string to seconds
                if ':' in lap_time:
                    parts = lap_time.split(':')
                    if len(parts) == 2:
                        minutes = int(parts[0])
                        seconds = float(parts[1].replace(',', '.'))
                        lap_seconds = minutes * 60 + seconds
                        # Filter out unrealistic lap times
                        if 50 < lap_seconds < 150:  # Between 50 and 150 seconds
                            total_seconds += lap_seconds
                            valid_count += 1
                else:
                    lap_seconds = float(lap_time.replace(',', '.'))
                    if 50 < lap_seconds < 150:
                        total_seconds += lap_seconds
                        valid_count += 1
            except Exception:
                continue

        if valid_count > 0:
            avg_lap_time = total_seconds / valid_count
            return round(avg_lap_time, 1)
        return default

    except Exception as e:
        print(f"Error calculating average lap time: {e}")
        return default

# Store previous delta values for change detection
previous_deltas = {}


def parse_time_to_seconds(time_str):
    """Convert a time string (MM:SS.sss or SS.sss) to seconds.

    Returns float('inf') for empty/None input; raises ValueError on malformed.
    Commas are tolerated as decimal separators (some Apex feeds emit them).
    """
    if not time_str:
        return float('inf')
    s = time_str.replace(',', '.')
    if ':' in s:
        parts = s.split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    return float(s)


def _safe_parse_time(time_str, default=float('inf')):
    try:
        return parse_time_to_seconds(time_str)
    except (ValueError, TypeError):
        return default


def get_standings_with_deltas():
    """Get current standings with P-1 and P+1 deltas for all teams"""
    teams = race_data.get('teams', [])
    if not teams:
        return []

    # Check if this is a qualification or session (not a race)
    session_info = race_data.get('session_info', {})
    session_type = session_info.get('title2', '') or session_info.get('title1', '') or session_info.get('title', '')
    is_qualification = any(keyword in session_type.lower() for keyword in ['qualification', 'session', 'practice', 'qualify'])

    # Sort teams by position
    sorted_teams = sorted(teams, key=lambda t: int(t.get('Position', '999') or '999'))

    # Resolve the average lap time ONCE per call. Previously this was queried
    # per lapped team inside the loop, opening race_data.db O(n) times.
    avg_lap_cache = None

    def _avg_lap():
        nonlocal avg_lap_cache
        if avg_lap_cache is None:
            avg_lap_cache = get_average_lap_time()
        return avg_lap_cache

    standings = []
    for i, team in enumerate(sorted_teams):
        position = int(team.get('Position', '0') or '0')
        kart_num = team.get('Kart', '')

        # Get current team's gap/best lap
        if is_qualification:
            current_gap = _safe_parse_time(team.get('Best Lap', ''))
        else:
            # Normal race mode - use gap
            if position == 1:
                current_gap = 0.0
            else:
                gap_str = team.get('Gap', '0')
                if 'Tour' in gap_str:
                    # Lapped - use average lap time
                    laps_behind = int(gap_str.split()[0])
                    current_gap = laps_behind * _avg_lap()
                else:
                    current_gap = _safe_parse_time(gap_str, default=0.0)

        # Calculate delta to P-1 (team ahead)
        delta_p_minus_1 = None
        if i > 0:  # Not the leader
            prev_team = sorted_teams[i-1]
            if is_qualification:
                prev_gap = _safe_parse_time(prev_team.get('Best Lap', ''))
            else:
                # Normal race mode - use gap
                prev_gap = 0.0
                prev_position = prev_team.get('Position', '0') or '0'
                if int(prev_position) > 1:
                    prev_gap_str = prev_team.get('Gap', '0')
                    if 'Tour' in prev_gap_str:
                        prev_laps = int(prev_gap_str.split()[0])
                        prev_gap = prev_laps * _avg_lap()
                    else:
                        prev_gap = _safe_parse_time(prev_gap_str, default=0.0)

            if current_gap != float('inf') and prev_gap != float('inf'):
                delta_p_minus_1 = round(current_gap - prev_gap, 3)

        # Calculate delta to P+1 (team behind)
        delta_p_plus_1 = None
        if i < len(sorted_teams) - 1:  # Not the last place
            next_team = sorted_teams[i+1]
            if is_qualification:
                next_gap = _safe_parse_time(next_team.get('Best Lap', ''))
            else:
                next_gap_str = next_team.get('Gap', '0')
                next_gap = 0.0
                if 'Tour' in next_gap_str:
                    next_laps = int(next_gap_str.split()[0])
                    next_gap = next_laps * _avg_lap()
                else:
                    next_gap = _safe_parse_time(next_gap_str, default=0.0)

            if current_gap != float('inf') and next_gap != float('inf'):
                delta_p_plus_1 = round(next_gap - current_gap, 3)
        
        standings.append({
            'position': position,
            'kart_number': kart_num,
            'team_name': team.get('Team', ''),
            'gap': team.get('Gap', '0'),
            'gap_seconds': current_gap,
            'delta_p_minus_1': delta_p_minus_1,  # Gap to car ahead
            'delta_p_plus_1': delta_p_plus_1,    # Gap to car behind
            'last_lap': team.get('Last Lap', ''),
            'best_lap': team.get('Best Lap', ''),
            'pit_stops': team.get('Pit Stops', '0'),
            'status': team.get('Status', 'On Track')
        })
    
    return standings

def get_team_delta_info(kart_number):
    """Get detailed delta information for a specific team"""
    standings = get_standings_with_deltas()
    
    for standing in standings:
        if standing['kart_number'] == kart_number:
            return standing
    
    return None

# Store previous standings for change detection
previous_standings = {}

def emit_standings_update():
    """Emit standings update to all subscribed clients"""
    global previous_standings
    
    standings = get_standings_with_deltas()
    if not standings:
        return
    
    # Detect changes in standings
    changed_teams = []
    for standing in standings:
        kart_num = standing['kart_number']
        if kart_num in previous_standings:
            prev = previous_standings[kart_num]
            # Check for significant changes
            position_changed = standing['position'] != prev.get('position')
            delta_p_minus_changed = (
                standing['delta_p_minus_1'] is not None and 
                prev.get('delta_p_minus_1') is not None and
                abs(standing['delta_p_minus_1'] - prev['delta_p_minus_1']) > 0.1
            )
            delta_p_plus_changed = (
                standing['delta_p_plus_1'] is not None and 
                prev.get('delta_p_plus_1') is not None and
                abs(standing['delta_p_plus_1'] - prev['delta_p_plus_1']) > 0.1
            )
            
            if position_changed or delta_p_minus_changed or delta_p_plus_changed:
                changed_teams.append({
                    'kart_number': kart_num,
                    'position': standing['position'],
                    'position_change': standing['position'] - prev.get('position', standing['position']),
                    'delta_p_minus_1': standing['delta_p_minus_1'],
                    'delta_p_plus_1': standing['delta_p_plus_1'],
                    'delta_p_minus_change': (standing['delta_p_minus_1'] - prev.get('delta_p_minus_1', 0)) if standing['delta_p_minus_1'] is not None and prev.get('delta_p_minus_1') is not None else None,
                    'delta_p_plus_change': (standing['delta_p_plus_1'] - prev.get('delta_p_plus_1', 0)) if standing['delta_p_plus_1'] is not None and prev.get('delta_p_plus_1') is not None else None
                })
        else:
            # New team
            changed_teams.append({
                'kart_number': kart_num,
                'position': standing['position'],
                'position_change': 0,
                'delta_p_minus_1': standing['delta_p_minus_1'],
                'delta_p_plus_1': standing['delta_p_plus_1'],
                'delta_p_minus_change': None,
                'delta_p_plus_change': None
            })
    
    # Update previous standings
    previous_standings = {s['kart_number']: s for s in standings}
    
    # Emit update to standings stream subscribers
    socketio.emit('standings_update', {
        'type': 'update',
        'standings': standings,
        'changes': changed_teams,
        'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]
    }, room='standings_stream')

# Function to calculate delta times between teams
# calculate_delta_times is retained for the legacy single-track simulator path
# only. As of Phase 2 the dashboard computes head-to-head deltas client-side
# from the per-track `teams` payload, so this function isn't on the production
# hot path. We keep it to avoid breaking /api/start-simulation.
def calculate_delta_times(teams, my_team_kart, monitored_karts):
    """Calculate delta times between my team and monitored teams"""
    global race_data, PIT_STOP_TIME, REQUIRED_PIT_STOPS, previous_deltas
    
    if not my_team_kart or not teams:
        return {}

    my_team = next((team for team in teams if team.get('Kart') == my_team_kart), None)
    if not my_team:
        return {}
    
    # Check if this is a qualification or session (not a race)
    session_info = race_data.get('session_info', {})
    session_type = session_info.get('title2', '') or session_info.get('title1', '') or session_info.get('title', '')
    is_qualification = any(keyword in session_type.lower() for keyword in ['qualification', 'session', 'practice', 'qualify'])

    deltas = {}
    try:
        my_pit_stops = int(my_team.get('Pit Stops', '0') or '0')
        my_remaining_stops = max(0, REQUIRED_PIT_STOPS - my_pit_stops)

        # parse_time_to_seconds is defined at module scope (see above).

        # Cache of get_average_lap_time() results for this call. Lazy so we only
        # pay the DB hit if a branch actually needs it.
        _avg_lap_cache = {}

        def _cached_avg(kart_numbers_tuple=None):
            if kart_numbers_tuple in _avg_lap_cache:
                return _avg_lap_cache[kart_numbers_tuple]
            value = get_average_lap_time(
                kart_numbers=list(kart_numbers_tuple) if kart_numbers_tuple else None
            )
            _avg_lap_cache[kart_numbers_tuple] = value
            return value

        # In qualification/practice, use best lap times instead of gaps
        if is_qualification:
            # Get my team's best lap time
            my_best_lap = my_team.get('Best Lap', '')
            if my_best_lap:
                try:
                    my_base_gap = parse_time_to_seconds(my_best_lap)
                except Exception:
                    my_base_gap = float('inf')  # No valid lap time
            else:
                my_base_gap = float('inf')  # No lap set
            my_laps_behind = 0
        else:
            # Normal race mode - use gap times
            # Check if my team is in position 1
            my_laps_behind = 0
            if my_team.get('Position') == '1':
                my_base_gap = 0.0
            else:
                gap_str = my_team.get('Gap', '0')
                # Handle lapped teams (e.g., "1 Tour", "2 Tours")
                if 'Tour' in gap_str:
                    # My team is lapped - extract number of laps
                    my_laps_behind = int(gap_str.split()[0])
                    # Use a default lap time since we're lapped
                    my_base_gap = my_laps_behind * 90.0
                else:
                    # Handle normal gap (could be MM:SS.sss or SS.sss)
                    try:
                        my_base_gap = parse_time_to_seconds(gap_str)
                    except Exception:
                        my_base_gap = 0.0
        
        # Initialize gap history for new karts
        for kart in monitored_karts:
            if kart not in race_data['gap_history']:
                race_data['gap_history'][kart] = {
                    'gaps': deque(maxlen=10),  # Store last 10 gaps
                    'adjusted_gaps': deque(maxlen=10),  # Store adjusted gaps
                    'last_update': None
                }
        
        # Remove history for karts no longer monitored
        for kart in list(race_data['gap_history'].keys()):
            if kart not in monitored_karts:
                del race_data['gap_history'][kart]
        
        for kart in monitored_karts:
            monitored_team = next((team for team in teams if team.get('Kart') == kart), None)
            if monitored_team:
                try:
                    # Calculate gap between monitored team and my team
                    mon_pit_stops = int(monitored_team.get('Pit Stops', '0') or '0')
                    mon_remaining_stops = max(0, REQUIRED_PIT_STOPS - mon_pit_stops)

                    # parse_time_to_seconds is module-level; no redefinition here.

                    # Count laps difference between my team and monitored team
                    def count_lap_difference(my_pos, mon_pos):
                        """Count how many lapped teams are between positions"""
                        if my_pos == mon_pos:
                            return 0
                        
                        start_pos = min(my_pos, mon_pos)
                        end_pos = max(my_pos, mon_pos)
                        lap_diff = 0
                        
                        # Check all teams between the two positions
                        for t in teams:
                            team_pos = int(t.get('Position', '0') or '0')
                            if start_pos < team_pos < end_pos:
                                team_gap = t.get('Gap', '0')
                                if 'Tour' in team_gap:
                                    # This team is lapped
                                    lap_diff += int(team_gap.split()[0])
                        
                        return lap_diff

                    my_position = int(my_team.get('Position', '0') or '0')
                    mon_position = int(monitored_team.get('Position', '0') or '0')
                    
                    # In qualification/practice, use best lap times
                    if is_qualification:
                        # Get monitored team's best lap time
                        mon_best_lap = monitored_team.get('Best Lap', '')
                        if mon_best_lap:
                            try:
                                mon_base_gap = parse_time_to_seconds(mon_best_lap)
                            except Exception:
                                mon_base_gap = float('inf')  # No valid lap time
                        else:
                            mon_base_gap = float('inf')  # No lap set
                    else:
                        # Normal race mode - use position-based gaps
                        # If position is 1, gap is 0
                        if mon_position == 1:
                            mon_base_gap = 0.0
                        else:
                            gap_str = monitored_team.get('Gap', '0')
                            # Handle lapped teams and special cases
                            if 'Tour' in gap_str:
                                # Check if this is P1 showing total laps (e.g., "Tour 56")
                                if mon_position == 1:
                                    # This is the winner showing total laps completed
                                    mon_base_gap = 0.0
                                    mon_laps_behind = 0
                                else:
                                    # This is laps behind the leader (e.g., "1 Tour", "2 Tours")
                                    mon_laps_behind = int(gap_str.split()[0])
                                    
                                    # Check if there are lapped teams between us
                                    laps_between = count_lap_difference(my_position, mon_position)
                                    
                                    # Calculate actual lap difference
                                    if my_position < mon_position:
                                        # Monitored team is behind us
                                        actual_lap_diff = mon_laps_behind - my_laps_behind - laps_between
                                    else:
                                        # Monitored team is ahead of us
                                        actual_lap_diff = mon_laps_behind - my_laps_behind + laps_between
                                    
                                    # If actual_lap_diff is 0, we're on the same lap
                                    if actual_lap_diff == 0:
                                        # We're on the same lap, use the position difference
                                        # Find the time gap to the closest non-lapped team
                                        mon_base_gap = my_base_gap  # Start with same base
                                    else:
                                        # Calculate gap based on lap difference, prefer team-specific avg.
                                        avg_lap_time = _cached_avg()
                                        team_karts = (int(my_team.get('Kart', '0') or '0'), int(monitored_team.get('Kart', '0') or '0'))
                                        team_avg = _cached_avg(team_karts)
                                        if team_avg != 90.0:
                                            avg_lap_time = team_avg

                                        mon_base_gap = my_base_gap + (actual_lap_diff * avg_lap_time)
                            else:
                                # Gap is in seconds (time format)
                                try:
                                    mon_base_gap = parse_time_to_seconds(gap_str)
                                    
                                    # Check if there are lapped teams between us
                                    laps_between = count_lap_difference(my_position, mon_position)
                                    
                                    # If there are lapped teams between us, account for lap difference
                                    if laps_between > 0:
                                        avg_lap_time = _cached_avg()
                                        team_karts = (int(my_team.get('Kart', '0') or '0'), int(monitored_team.get('Kart', '0') or '0'))
                                        team_avg = _cached_avg(team_karts)
                                        if team_avg != 90.0:
                                            avg_lap_time = team_avg
                                        
                                        if my_position < mon_position:
                                            # Monitored team is behind us with lapped teams in between
                                            mon_base_gap += laps_between * avg_lap_time
                                        else:
                                            # Monitored team is ahead of us with lapped teams in between
                                            mon_base_gap -= laps_between * avg_lap_time
                                    # If no lapped teams between us, we're on same lap - use gap as is
                                except Exception:
                                    mon_base_gap = 0.0
                    
                    # Calculate gap based on session type
                    if is_qualification:
                        # In qualification, gap is simply the difference in best lap times
                        if my_base_gap == float('inf') or mon_base_gap == float('inf'):
                            # One or both teams haven't set a valid lap time
                            real_gap = 0.0 if my_base_gap == mon_base_gap else float('inf')
                        else:
                            real_gap = mon_base_gap - my_base_gap
                        real_gap = round(real_gap, 3)
                        # No pit stop adjustments in qualification
                        adjusted_gap = real_gap
                    else:
                        # Normal race mode - calculate with pit stops
                        # Calculate regular gap with pit stop compensation for completed stops
                        # Using standard 150 second compensation as base (this is what Apex Timing shows)
                        real_gap = (mon_base_gap - my_base_gap) + ((mon_pit_stops - my_pit_stops) * 150)
                        real_gap = round(real_gap, 3)
                        
                        # Calculate adjusted gap accounting for remaining required pit stops
                        adjusted_gap = real_gap + ((mon_remaining_stops - my_remaining_stops) * PIT_STOP_TIME)
                        adjusted_gap = round(adjusted_gap, 3)
                    
                    # Update gap history
                    gap_history = race_data['gap_history'][kart]
                    last_lap = monitored_team.get('Last Lap')
                    
                    # Only update history when we see a new lap
                    if last_lap and last_lap != gap_history['last_update']:
                        gap_history['gaps'].append(real_gap)
                        gap_history['adjusted_gaps'].append(adjusted_gap)
                        gap_history['last_update'] = last_lap
                    
                    # Get gaps as list for calculations
                    gaps = list(gap_history['gaps'])
                    adjusted_gaps = list(gap_history['adjusted_gaps'] if 'adjusted_gaps' in gap_history else [])
                    
                    # Calculate trends for regular gap
                    trend_1, arrow_1 = calculate_trend(real_gap, gaps[-2:] if len(gaps) >= 2 else [])
                    trend_5, arrow_5 = calculate_trend(real_gap, gaps[-5:] if len(gaps) >= 5 else [])
                    trend_10, arrow_10 = calculate_trend(real_gap, gaps[-10:] if len(gaps) >= 10 else [])
                    
                    # Calculate trends for adjusted gap
                    adj_trend_1, adj_arrow_1 = calculate_trend(adjusted_gap, adjusted_gaps[-2:] if len(adjusted_gaps) >= 2 else [])
                    adj_trend_5, adj_arrow_5 = calculate_trend(adjusted_gap, adjusted_gaps[-5:] if len(adjusted_gaps) >= 5 else [])
                    adj_trend_10, adj_arrow_10 = calculate_trend(adjusted_gap, adjusted_gaps[-10:] if len(adjusted_gaps) >= 10 else [])
                    
                    deltas[kart] = {
                        'gap': real_gap,
                        'adjusted_gap': adjusted_gap,
                        'team_name': monitored_team.get('Team', ''),
                        'position': int(monitored_team.get('Position', '0') or '0'),
                        'last_lap': last_lap,
                        'best_lap': monitored_team.get('Best Lap', ''),
                        'pit_stops': str(mon_pit_stops),
                        'remaining_stops': mon_remaining_stops,
                        'trends': {
                            'lap_1': {'value': trend_1, 'arrow': arrow_1},
                            'lap_5': {'value': trend_5, 'arrow': arrow_5},
                            'lap_10': {'value': trend_10, 'arrow': arrow_10}
                        },
                        'adjusted_trends': {
                            'lap_1': {'value': adj_trend_1, 'arrow': adj_arrow_1},
                            'lap_5': {'value': adj_trend_5, 'arrow': adj_arrow_5},
                            'lap_10': {'value': adj_trend_10, 'arrow': adj_arrow_10}
                        }
                    }
                except (ValueError, TypeError, AttributeError) as e:
                    print(f"Error calculating delta for kart {kart}: {e}")
                    continue
    except Exception as e:
        print(f"Error calculating deltas: {e}")
        return {}
    
    # Store the delta times in race_data for future reference
    race_data['delta_times'] = deltas
    
    # Check for significant changes and emit targeted updates
    changed_deltas = {}
    for kart, delta_info in deltas.items():
        if kart in previous_deltas:
            prev_delta = previous_deltas[kart]
            # Check if gap changed by more than 0.1 seconds
            gap_changed = abs(delta_info['gap'] - prev_delta.get('gap', 0)) > 0.1
            adj_gap_changed = abs(delta_info['adjusted_gap'] - prev_delta.get('adjusted_gap', 0)) > 0.1
            
            if gap_changed or adj_gap_changed:
                changed_deltas[kart] = {
                    'kart': kart,
                    'team_name': delta_info['team_name'],
                    'gap': delta_info['gap'],
                    'adjusted_gap': delta_info['adjusted_gap'],
                    'gap_change': delta_info['gap'] - prev_delta.get('gap', 0),
                    'adj_gap_change': delta_info['adjusted_gap'] - prev_delta.get('adjusted_gap', 0),
                    'position': delta_info['position'],
                    'trends': delta_info['trends']
                }
        else:
            # New monitored team
            changed_deltas[kart] = {
                'kart': kart,
                'team_name': delta_info['team_name'],
                'gap': delta_info['gap'],
                'adjusted_gap': delta_info['adjusted_gap'],
                'gap_change': 0,
                'adj_gap_change': 0,
                'position': delta_info['position'],
                'trends': delta_info['trends']
            }
    
    # Update previous deltas
    previous_deltas = deltas.copy()
    
    # If there are changed deltas, emit a targeted update
    if changed_deltas:
        emit_race_update('custom', {
            'event': 'delta_change',
            'payload': {
                'changed_deltas': changed_deltas,
                'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]  # Include milliseconds
            }
        })
    
    return deltas

# Simulation helper functions
def generate_team_name():
    """Generate realistic team names"""
    prefixes = ["Team", "Racing", "Kart", "Speed", "Apex", "Circuit", "Pro", "Elite", "Turbo", "Drift"]
    names = ["Alpha", "Beta", "Gamma", "Delta", "Omega", "Phoenix", "Falcon", "Tiger", "Eagle", "Dragon", 
             "Viper", "Cobra", "Lightning", "Thunder", "Storm", "Blaze", "Fire", "Ice", "Steel", "Carbon"]
    suffixes = ["Racing", "Karts", "Motorsport", "Team", "Racers", "Crew", "Squad", "Champions", "Masters", "Pros"]
    
    if random.random() < 0.3:  # 30% chance of having a sponsor
        sponsors = ["RedBull", "Monster", "Gulf", "Shell", "Mobil", "Castrol", "Pirelli", "Bridgestone", 
                    "DHL", "GoPro", "Sparco", "OMP", "Alpine", "Alpinestars", "Brembo"]
        return f"{random.choice(sponsors)} {random.choice(names)} {random.choice(suffixes)}"
    
    if random.random() < 0.5:
        return f"{random.choice(prefixes)} {random.choice(names)}"
    else:
        return f"{random.choice(names)} {random.choice(suffixes)}"

def initialize_teams():
    """Initialize teams for simulation"""
    teams = []
    for i in range(1, NUM_TEAMS + 1):
        kart_num = i
        team_name = generate_team_name()
        # Vary skill levels to create different "tiers" of teams
        if i <= 3:  # Top teams
            skill_level = random.uniform(1.08, 1.1)
        elif i <= 7:  # Midfield teams
            skill_level = random.uniform(1.05, 1.07)
        else:  # Backmarker teams
            skill_level = random.uniform(1.02, 1.04)
            
        teams.append(Team(kart_num, team_name, skill_level))
    
    return teams

def update_positions_and_gaps(teams):
    """Update team positions and gaps"""
    # Sort teams by total distance covered
    sorted_teams = sorted(teams, key=lambda t: t.total_distance, reverse=True)
    
    # Update positions
    for i, team in enumerate(sorted_teams):
        team.update_position(i + 1)
    
    # Calculate gaps
    leader = sorted_teams[0]
    leader.gap = "0.000"
    leader.gap_seconds = 0
    
    for team in sorted_teams[1:]:
        distance_diff = leader.total_distance - team.total_distance
        if distance_diff <= 0:
            team.gap = "0.000"
            team.gap_seconds = 0
        else:
            approx_speed = TRACK_LENGTH_METERS / BASE_LAP_TIME_SECONDS
            time_diff = distance_diff / approx_speed
            team.gap = f"{time_diff:.3f}"
            team.gap_seconds = time_diff
    
    return sorted_teams

def check_race_completion(team, race_time, max_race_time):
    """Mark a team as finished if the race time is almost up"""
    if race_time >= max_race_time - 60 and not team.race_finished and not team.in_pits:
        finish_chance = 0.05 * (1.0 / team.position) * ((race_time - (max_race_time - 60)) / 60)
        if random.random() < finish_chance:
            team.race_finished = True
            team.status = "Finished"
            return True
    return False

async def simulate_race():
    """Run race simulation"""
    global race_data, simulation_teams
    
    # Initialize teams
    simulation_teams = initialize_teams()
    race_data['teams'] = [team.to_dict() for team in simulation_teams]
    race_data['race_time'] = 0
    race_data['is_running'] = True
    race_data['simulation_mode'] = True
    race_data['session_info'] = {
        'dyn1': 'Race Simulation',
        'dyn2': 'Virtual Track',
        'light': 'green'
    }
    
    # Initialize gap history for all teams
    for team in simulation_teams:
        race_data['gap_history'][str(team.kart_num)] = {
            'gaps': deque(maxlen=10),
            'adjusted_gaps': deque(maxlen=10),
            'last_update': None
        }
    
    time_step = 1.0
    
    # Main simulation loop
    while race_data['race_time'] < MAX_RACE_TIME_SECONDS and race_data['is_running'] and not stop_event.is_set():
        race_data['race_time'] += time_step
        
        # Process each team
        for team in simulation_teams:
            team.run_time_seconds += time_step
            team.run_time = team.format_runtime(team.run_time_seconds)
            
            check_race_completion(team, race_data['race_time'], MAX_RACE_TIME_SECONDS)
            
            # Process pit stops
            if team.in_pits:
                team.pit_time_remaining -= time_step
                if team.pit_time_remaining <= 10 and team.status != "Pit-out":
                    team.status = "Pit-out"
                    team.status_duration = 15
                if team.pit_time_remaining <= 0:
                    team.in_pits = False
                    team.status = "Pit-out"
                    team.status_duration = 15
                    team.tire_wear = 1.0
                    team.fuel_level = 1.0
                    team.next_pit_in = random.randint(PIT_STOP_INTERVAL_MIN, PIT_STOP_INTERVAL_MAX)
            
            # Randomly stop a kart (mechanical issue)
            if not team.in_pits and not team.race_finished and random.random() < 0.00005:
                team.status = "Stopped"
                team.status_duration = random.randint(30, 120)
            
            # Calculate distance covered
            if not (team.in_pits or team.status == "Stopped" or team.race_finished):
                if team.last_lap_seconds > 0:
                    speed = TRACK_LENGTH_METERS / team.last_lap_seconds
                else:
                    speed = TRACK_LENGTH_METERS / BASE_LAP_TIME_SECONDS
                
                distance_this_step = speed * time_step
                team.total_distance += distance_this_step
                
                # Check if completed a lap
                laps_completed = math.floor(team.total_distance / TRACK_LENGTH_METERS)
                if laps_completed > team.total_laps:
                    team.total_laps = laps_completed
                    lap_time = team.calculate_lap_time()
                    
                    if lap_time < 900:  # Not in pits or stopped
                        team.last_lap_seconds = lap_time
                        team.last_lap = team.format_time(lap_time)
                        
                        if lap_time < team.best_lap_seconds:
                            team.best_lap_seconds = lap_time
                            team.best_lap = team.format_time(lap_time)
        
        # Update positions and gaps
        updated_teams = update_positions_and_gaps(simulation_teams)
        
        # Update team dictionaries
        team_dicts = [team.to_dict() for team in updated_teams]
        race_data['teams'] = team_dicts
        race_data['last_update'] = datetime.now().strftime('%H:%M:%S')
        
        # Emit teams update via WebSocket
        emit_race_update('teams')
        
        # Calculate delta times if my_team is set
        if race_data['my_team'] and race_data['monitored_teams']:
            calculate_delta_times(team_dicts, race_data['my_team'], race_data['monitored_teams'])
            # Emit gap updates if we have monitored teams
            emit_race_update('gaps')
            
        # Sleep to control simulation speed (4x real time)
        await asyncio.sleep(time_step / 4)

# Function to make gap_history serializable for JSON
def get_serializable_race_data():
    """Convert race_data to a JSON-serializable format"""
    serializable_data = {
        'teams': race_data['teams'],
        'session_info': race_data['session_info'],
        'last_update': race_data['last_update'],
        'my_team': race_data['my_team'],
        'monitored_teams': race_data['monitored_teams'],
        'delta_times': race_data['delta_times'],
        'simulation_mode': race_data.get('simulation_mode', False),
        'timing_url': race_data.get('timing_url', None)
    }
    
    # Convert gap_history deques to lists
    serializable_data['gap_history'] = {
        kart: {
            'gaps': list(history['gaps']) if isinstance(history['gaps'], deque) else history['gaps'],
            'last_update': history['last_update']
        }
        for kart, history in race_data['gap_history'].items()
    }
    
    return serializable_data

# Function to update race data in the background
async def update_race_data():
    global race_data, parser
    
    # Check if we're in simulation mode
    if race_data['simulation_mode']:
        print("Starting race simulation...")
        await simulate_race()
        return
    
    # Initialize WebSocket parser
    parser = ApexTimingWebSocketParser()
    
    # WebSocket URL is required
    websocket_url = race_data.get('websocket_url')
    if not websocket_url:
        print("ERROR: WebSocket URL is required")
        race_data['error'] = 'WebSocket URL is required for real data collection'
        race_data['is_running'] = False
        return
    
    print(f"Using WebSocket parser with URL: {websocket_url}")
    
    # Set column mappings if provided
    if race_data.get('column_mappings'):
        parser.set_column_mappings(race_data['column_mappings'])
        print(f"Set column mappings: {race_data['column_mappings']}")
    
    try:
        print("Background update thread started")
        
        # Create a task to monitor the WebSocket
        monitor_task = asyncio.create_task(
            parser.monitor_race_websocket(
                websocket_url,
                session_name="Live Session",
                track=race_data.get('timing_url', 'Unknown Track')
            )
        )
        
        # Update loop to fetch data from parser
        while not stop_event.is_set():
            try:
                # Get current data from the parser
                df, session_info = await parser.get_current_data()
                
                if not df.empty:
                    # Convert DataFrame to list of dictionaries
                    teams_data = df.to_dict('records')
                    race_data['teams'] = teams_data
                    race_data['session_info'] = session_info
                    race_data['last_update'] = datetime.now().strftime('%H:%M:%S')
                    race_data['update_count'] = race_data.get('update_count', 0) + 1
                    
                    # Emit teams and session updates via WebSocket
                    emit_race_update('teams')
                    emit_race_update('session')
                    
                    # Update delta times for monitored teams
                    if race_data['my_team'] and race_data['monitored_teams']:
                        delta_times = calculate_delta_times(
                            teams_data,
                            race_data['my_team'],
                            race_data['monitored_teams']
                        )
                        race_data['delta_times'] = delta_times
                        # Emit gap updates
                        emit_race_update('gaps')
                    
                    # Log updates every 10th update
                    if race_data.get('update_count', 0) % 10 == 0:
                        print(f"Updated data at {race_data['last_update']} - {len(teams_data)} teams")
                
                # Wait 1 second before next update
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"Error updating race data: {e}")
                print(traceback.format_exc())
                await asyncio.sleep(5)  # Wait longer on error
                
    except Exception as e:
        print(f"Error in update thread: {e}")
        print(traceback.format_exc())
    finally:
        # Cancel the monitor task if it's still running
        if 'monitor_task' in locals():
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect WebSocket
        if parser:
            await parser.disconnect_websocket()
        print("Background update thread stopped")

# Start the background update process
def start_update_thread():
    global update_thread, stop_event
    
    # Reset the stop event
    stop_event = threading.Event()  # Create a new event instead of clearing
    
    # Define a wrapper function for asyncio
    def run_async_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(update_race_data())
        except Exception as e:
            print(f"Error in update thread: {e}")
            print(traceback.format_exc())
        finally:
            loop.close()
    
    # Start the thread
    update_thread = threading.Thread(target=run_async_loop, daemon=True)
    update_thread.start()
    print(f"Update thread started, simulation mode: {race_data.get('simulation_mode', False)}")

# Authentication helper functions
def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect('auth.db')
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_auth_schema():
    """Normalize auth.db across versions (legacy 'timestamp' column -> 'attempted_at')
    and create driver_aliases / Phase 1 tables defensively."""
    try:
        with sqlite3.connect('auth.db') as conn:
            cols = [row[1] for row in conn.execute('PRAGMA table_info(login_attempts)').fetchall()]
            if cols and 'attempted_at' not in cols and 'timestamp' in cols:
                conn.execute('ALTER TABLE login_attempts RENAME COLUMN timestamp TO attempted_at')
                print('Migrated login_attempts.timestamp -> attempted_at')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS driver_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL,
                    alias_name TEXT NOT NULL,
                    added_by TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(canonical_name COLLATE NOCASE, alias_name COLLATE NOCASE)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_driver_aliases_canon ON driver_aliases(canonical_name COLLATE NOCASE)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_driver_aliases_alias ON driver_aliases(alias_name COLLATE NOCASE)')

            # --- Phase 1 columns on users (idempotent) -------------------------
            user_cols = {row[1] for row in conn.execute('PRAGMA table_info(users)').fetchall()}
            phase1_cols = [
                ('email_verified', 'email_verified INTEGER NOT NULL DEFAULT 0'),
                ('verification_token', 'verification_token TEXT'),
                ('verification_token_expires', 'verification_token_expires TIMESTAMP'),
                ('password_reset_token', 'password_reset_token TEXT'),
                ('password_reset_expires', 'password_reset_expires TIMESTAMP'),
                ('tos_accepted_at', 'tos_accepted_at TIMESTAMP'),
                ('deleted_at', 'deleted_at TIMESTAMP'),
            ]
            for name, ddl in phase1_cols:
                if name not in user_cols:
                    conn.execute(f'ALTER TABLE users ADD COLUMN {ddl}')

            # Partial unique indexes — fine to re-create with IF NOT EXISTS.
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_verification_token "
                "ON users(verification_token) WHERE verification_token IS NOT NULL"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_password_reset_token "
                "ON users(password_reset_token) WHERE password_reset_token IS NOT NULL"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower "
                "ON users(LOWER(email)) WHERE email IS NOT NULL AND deleted_at IS NULL"
            )

            # Backfill admin email_verified so the verification gate doesn't lock us out.
            conn.execute(
                "UPDATE users SET email_verified = 1 WHERE role = 'admin' AND email_verified = 0"
            )

            # Phase 2.6: cross-device sync of the user's currently-selected track.
            if 'selected_track_id' not in user_cols:
                conn.execute('ALTER TABLE users ADD COLUMN selected_track_id INTEGER')

            # --- New Phase 1 tables -----------------------------------------
            conn.execute('''
                CREATE TABLE IF NOT EXISTS invite_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    uses INTEGER NOT NULL DEFAULT 0,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    note TEXT,
                    FOREIGN KEY (created_by) REFERENCES users(id)
                )
            ''')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code)'
            )
            conn.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id INTEGER,
                    action TEXT NOT NULL,
                    target TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    details TEXT
                )
            ''')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_audit_log_actor '
                'ON audit_log(actor_user_id, timestamp DESC)'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_audit_log_action '
                'ON audit_log(action, timestamp DESC)'
            )
            conn.execute('''
                CREATE TABLE IF NOT EXISTS rate_limit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bucket TEXT NOT NULL,
                    key TEXT NOT NULL,
                    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_rate_limit_bucket_key_time '
                'ON rate_limit_events(bucket, key, occurred_at)'
            )

            # --- Phase 2: per-user track prefs ---------------------------------
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_track_prefs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    my_team TEXT,
                    monitored_teams TEXT,
                    pit_stop_time INTEGER,
                    required_pit_stops INTEGER,
                    default_lap_time REAL,
                    stint_planner_config TEXT,
                    stint_planner_presets TEXT,
                    driver_names TEXT,
                    current_driver_index INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, track_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_user_track_prefs_user '
                'ON user_track_prefs(user_id)'
            )
            # Add stint_assignments column for tables that pre-date this field.
            prefs_cols = {row[1] for row in conn.execute('PRAGMA table_info(user_track_prefs)').fetchall()}
            if 'stint_assignments' not in prefs_cols:
                conn.execute('ALTER TABLE user_track_prefs ADD COLUMN stint_assignments TEXT')
    except sqlite3.Error as e:
        print(f'Warning: auth schema normalization skipped: {e}')


_ensure_auth_schema()

def create_session(user_id):
    """Create a new session for user"""
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=24)

    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO sessions (session_token, user_id, expires_at)
               VALUES (?, ?, ?)''',
            (session_id, user_id, expires_at.isoformat()),
        )

    return session_id


def verify_session(session_id):
    """Verify if session is valid and return user info"""
    if not session_id:
        return None

    with get_db_connection() as conn:
        cursor = conn.execute(
            '''SELECT u.id, u.username, u.role, u.email
               FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.session_token = ? AND s.expires_at > ?''',
            (session_id, datetime.now().isoformat()),
        )
        user = cursor.fetchone()

    return dict(user) if user else None

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_id = session.get('session_id')
        user = verify_session(session_id)
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_id = session.get('session_id')
        user = verify_session(session_id)
        if not user or user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated_function

# Authentication routes
LOGIN_MAX_ATTEMPTS = int(os.environ.get('LOGIN_MAX_ATTEMPTS', '5'))
LOGIN_WINDOW_MINUTES = int(os.environ.get('LOGIN_WINDOW_MINUTES', '15'))

# Phase 1 auth knobs
REGISTRATION_OPEN = os.environ.get('REGISTRATION_OPEN', 'false').lower() == 'true'
VERIFICATION_TOKEN_HOURS = int(os.environ.get('VERIFICATION_TOKEN_HOURS', '48'))
RESET_TOKEN_HOURS = int(os.environ.get('RESET_TOKEN_HOURS', '1'))
ENABLE_TEST_ENDPOINTS = os.environ.get('ENABLE_TEST_ENDPOINTS', 'false').lower() == 'true'

RATE_LIMITS = {
    'register_ip': (int(os.environ.get('RATE_LIMIT_REGISTER_IP_PER_HOUR', '5')), 3600),
    'forgot_password_ip': (int(os.environ.get('RATE_LIMIT_FORGOT_IP_PER_HOUR', '10')), 3600),
    'forgot_password_email': (int(os.environ.get('RATE_LIMIT_FORGOT_EMAIL_PER_HOUR', '3')), 3600),
    'verify_email_ip': (int(os.environ.get('RATE_LIMIT_VERIFY_IP_PER_HOUR', '30')), 3600),
    'resend_verification_ip': (int(os.environ.get('RATE_LIMIT_RESEND_IP_PER_HOUR', '5')), 3600),
    'resend_verification_email': (int(os.environ.get('RATE_LIMIT_RESEND_EMAIL_PER_HOUR', '3')), 3600),
    # Phase 3: throttle the expensive reads. Limits are deliberately generous
    # so a legitimate user using the dashboard isn't blocked; the goal is to
    # catch automated scraping or runaway loops.
    'heavy_read_ip': (int(os.environ.get('RATE_LIMIT_HEAVY_READ_IP_PER_HOUR', '120')), 3600),
}

RESERVED_USERNAMES = {'admin', 'root', 'system', 'support', 'security', 'administrator'}
USERNAME_RE = re.compile(r'^[a-zA-Z0-9_.-]{3,32}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

_email_sender = get_email_sender()


def _rate_limit_hit(bucket: str, key: str, max_events: int | None = None,
                    window_seconds: int | None = None) -> bool:
    """Record a rate-limit event and report whether the bucket is now exhausted.

    Looks up defaults from RATE_LIMITS when max/window not passed. Returns True
    if the count in window has reached `max_events`. Probabilistic GC cleans
    rows older than 24h on ~1% of calls so we don't need a background thread.
    """
    if max_events is None or window_seconds is None:
        defaults = RATE_LIMITS.get(bucket)
        if not defaults:
            return False
        max_events = max_events if max_events is not None else defaults[0]
        window_seconds = window_seconds if window_seconds is not None else defaults[1]
    if max_events <= 0:
        return False
    cutoff = (datetime.now() - timedelta(seconds=window_seconds)).strftime('%Y-%m-%d %H:%M:%S')
    try:
        with sqlite3.connect('auth.db') as conn:
            conn.execute(
                'INSERT INTO rate_limit_events (bucket, key) VALUES (?, ?)',
                (bucket, key or '-'),
            )
            row = conn.execute(
                'SELECT COUNT(*) FROM rate_limit_events '
                'WHERE bucket = ? AND key = ? AND occurred_at > ?',
                (bucket, key or '-', cutoff),
            ).fetchone()
            count = row[0] if row else 0
            if random.random() < 0.01:
                gc_cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
                conn.execute(
                    'DELETE FROM rate_limit_events WHERE occurred_at < ?', (gc_cutoff,)
                )
        return count >= max_events
    except sqlite3.Error as exc:
        # Don't fail the request on rate-limit infrastructure errors — log and pass.
        print(f'[rate_limit] {bucket}/{key}: {exc}')
        return False


def _audit(action: str, *, actor_user_id=None, target=None, details=None):
    """Best-effort append-only audit log. Never raises into the caller."""
    try:
        ip = None
        ua = None
        if has_request_context():
            ip = request.remote_addr
            ua = (request.headers.get('User-Agent') or '')[:512]
        payload = None
        if details is not None:
            try:
                payload = json.dumps(details, default=str)
            except (TypeError, ValueError):
                payload = json.dumps({'_unserialisable': repr(details)[:500]})
        with sqlite3.connect('auth.db') as conn:
            conn.execute(
                'INSERT INTO audit_log (actor_user_id, action, target, ip_address, user_agent, details) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (actor_user_id, action, target, ip, ua, payload),
            )
    except Exception as exc:  # pragma: no cover — defensive
        print(f'[audit] failed to record {action}: {exc}')


CSRF_EXEMPT_PATHS = {
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/forgot-password',
    '/api/auth/reset-password',
    '/api/auth/verify-email',
    '/api/auth/resend-verification',
    '/api/auth/csrf',
}


@app.before_request
def _csrf_guard():
    """Require X-CSRF-Token on unsafe /api/* requests.

    Anonymous endpoints (login/register/forgot/reset/verify/resend/csrf) are
    skipped because they're protected by Turnstile or are themselves token
    issuers. Socket.IO paths are skipped — the connection auth lives in the
    session cookie. SameSite=Lax + this header check keeps us safe from CSRF
    on authenticated endpoints.
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    path = request.path or ''
    if not path.startswith('/api/'):
        return None
    if path in CSRF_EXEMPT_PATHS:
        return None
    if path.startswith('/api/socket.io') or path.startswith('/socket.io'):
        return None
    expected = session.get('csrf_token')
    provided = request.headers.get('X-CSRF-Token', '')
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        return jsonify({'error': 'csrf_failed'}), 403
    return None


def _is_rate_limited(username: str, ip_address: str) -> bool:
    """Return True if (username, ip) has too many recent failed logins."""
    if LOGIN_MAX_ATTEMPTS <= 0:
        return False
    # SQLite's CURRENT_TIMESTAMP writes "YYYY-MM-DD HH:MM:SS" (space separator,
    # no microseconds). Match that format exactly for string comparison.
    cutoff = (datetime.now() - timedelta(minutes=LOGIN_WINDOW_MINUTES)).strftime('%Y-%m-%d %H:%M:%S')
    with sqlite3.connect('auth.db') as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT COUNT(*) FROM login_attempts
               WHERE username = ? AND ip_address = ? AND success = 0
                 AND attempted_at > ?''',
            (username, ip_address, cutoff),
        )
        failures = cursor.fetchone()[0]
    return failures >= LOGIN_MAX_ATTEMPTS





# User management routes (admin only)


# REST API routes
@app.route('/api/race-data')
def get_race_data():
    """Return the current race data as JSON"""
    return jsonify(get_serializable_race_data())

# /api/update-monitoring removed in Phase 2 — superseded by PUT /api/me/prefs/<track_id>.
# /api/update-pit-config removed in Phase 2 — same replacement.

@app.route('/api/start-simulation', methods=['POST'])
@admin_required
def start_simulation():
    """Start the data collection thread"""
    global update_thread, stop_event, race_data
    
    try:
        # Get mode from request (default to real data)
        data = request.json or {}
        simulation_mode = data.get('simulation', False)
        timing_url = data.get('timingUrl', None)
        websocket_url = data.get('websocketUrl', None)  # WebSocket URL
        track_id = data.get('trackId', None)  # Optional track ID
        
        # If track ID is provided, get URLs and column mappings from database
        column_mappings = None
        if track_id and not simulation_mode:
            track = track_db.get_track_by_id(track_id)
            if not track:
                return jsonify({'status': 'error', 'message': 'Track not found'}), 404
            timing_url = track['timing_url']
            websocket_url = track['websocket_url']
            column_mappings = track.get('column_mappings', {})
            print(f"Using track from database: {track['track_name']}")
            if column_mappings:
                print(f"Column mappings: {column_mappings}")
            
            # Check if WebSocket URL is available for this track
            if not websocket_url:
                return jsonify({'status': 'error', 'message': f'Track "{track["track_name"]}" does not have a WebSocket URL configured. Please configure it in Track Manager.'}), 400
        
        # Validate URL if provided and not in simulation mode
        if not simulation_mode and not timing_url:
            return jsonify({'status': 'error', 'message': 'Timing URL or track ID is required for real data mode'}), 400
        
        # Validate WebSocket URL for real data mode
        if not simulation_mode and not websocket_url:
            return jsonify({'status': 'error', 'message': 'WebSocket URL is required for real data mode. Please select a track with WebSocket URL configured or provide one manually.'}), 400
        
        print(f"Starting with simulation mode: {simulation_mode}, URL: {timing_url}, WebSocket URL: {websocket_url}")
        
        # Stop any existing thread
        if update_thread and update_thread.is_alive():
            stop_event.set()
            update_thread.join(timeout=5)
        
        # Reset race data
        race_data['teams'] = []
        race_data['last_update'] = None
        race_data['delta_times'] = {}
        race_data['gap_history'] = {}
        race_data['my_team'] = None
        race_data['monitored_teams'] = []
        race_data['simulation_mode'] = simulation_mode
        race_data['is_running'] = False
        race_data['timing_url'] = timing_url  # Store the URL
        race_data['websocket_url'] = websocket_url  # Store the WebSocket URL
        race_data['column_mappings'] = column_mappings  # Store column mappings
        
        # Start a new thread
        start_update_thread()
        
        mode_text = 'simulation' if simulation_mode else f'real data collection from {timing_url}'
        return jsonify({'status': 'success', 'message': f'Started {mode_text}'})
    except Exception as e:
        print(f"Error in start_simulation: {e}")
        print(traceback.format_exc())
        return _internal_error(e)

@app.route('/api/stop-simulation', methods=['POST'])
@admin_required
def stop_simulation():
    """Stop the data collection thread"""
    global update_thread, stop_event, race_data
    
    race_data['is_running'] = False  # Stop the simulation loop
    
    if update_thread and update_thread.is_alive():
        stop_event.set()
        update_thread.join(timeout=5)
    
    return jsonify({'status': 'success', 'message': 'Data collection stopped'})

# API route to check parser status
@app.route('/api/parser-status')
def parser_status():
    """Check if the parser is running"""
    global update_thread, parser
    
    is_running = update_thread is not None and update_thread.is_alive()
    
    return jsonify({
        'status': 'running' if is_running else 'stopped',
        'last_update': race_data['last_update'],
        'websocket_url': race_data.get('websocket_url', ''),
        'timing_url': race_data.get('timing_url', '')
    })

@app.route('/api/set-parser-mode', methods=['POST'])
@admin_required
def set_parser_mode():
    """Set parser mode (hybrid or playwright-only)"""
    global race_data
    
    data = request.json
    if data and 'useHybrid' in data:
        race_data['use_hybrid_parser'] = data['useHybrid']
        mode = "hybrid (WebSocket + Playwright)" if data['useHybrid'] else "Playwright-only"
        print(f"Parser mode set to: {mode}")
        return jsonify({
            'status': 'success', 
            'message': f'Parser mode set to {mode}',
            'useHybrid': race_data['use_hybrid_parser']
        })
    
    return jsonify({'status': 'error', 'message': 'Invalid request'})

@app.route('/api/parser-status', methods=['GET'])
def get_parser_status():
    """Get current parser status and type"""
    global parser, race_data
    
    status = {
        'is_running': race_data.get('is_running', False),
        'use_hybrid_parser': race_data.get('use_hybrid_parser', True),
        'parser_type': 'none'
    }
    
    if parser:
        if hasattr(parser, 'use_websocket'):
            # It's a hybrid parser
            status['parser_type'] = 'websocket' if parser.use_websocket else 'playwright'
            status['websocket_url'] = parser.ws_url if parser.use_websocket else None
        else:
            # It's a playwright-only parser
            status['parser_type'] = 'playwright'
    
    return jsonify(status)

# For debugging: simulate data
@app.route('/api/simulate-data', methods=['POST'])
@admin_required
def simulate_data():
    """Generate fake race data for testing"""
    global race_data
    
    import random
    from datetime import datetime
    
    # Generate 10 fake teams
    teams = []
    for i in range(1, 11):
        teams.append({
            'Kart': str(i),
            'Team': f"Team {i}",
            'Position': str(i),
            'Last Lap': f"1:{random.randint(37, 45)}.{random.randint(100, 999)}",
            'Best Lap': f"1:{random.randint(35, 40)}.{random.randint(100, 999)}",
            'Pit Stops': str(random.randint(0, 2)),
            'Gap': f"{i * 1.5:.3f}" if i > 1 else "0.000",
            'RunTime': f"{random.randint(10, 30)}:{random.randint(10, 59)}",
            'Status': random.choice(['On Track', 'Pit-in', 'Pit-out', 'Finished'])
        })
    
    race_data['teams'] = teams
    race_data['session_info'] = {
        'dyn1': 'Simulation Mode',
        'dyn2': f'Simulated at {datetime.now().strftime("%H:%M:%S")}',
        'light': random.choice(['green', 'yellow', 'red'])
    }
    race_data['last_update'] = datetime.now().strftime('%H:%M:%S')
    
    return jsonify({'status': 'success', 'message': 'Simulation data generated'})

# Track management API endpoints
@app.route('/api/tracks', methods=['GET'])
def get_tracks():
    """Get all tracks from the database"""
    tracks = track_db.get_all_tracks()
    return jsonify({'tracks': tracks})

@app.route('/api/tracks/active', methods=['GET'])
def get_active_tracks():
    """Get list of currently monitored tracks with their status"""
    global multi_track_manager

    if not multi_track_manager:
        return jsonify({'tracks': []})

    active_tracks = multi_track_manager.get_active_tracks()
    return jsonify({'tracks': active_tracks})

@app.route('/api/tracks/status', methods=['GET'])
def get_all_tracks_status():
    """Get session status for all tracks"""
    global multi_track_manager

    if not multi_track_manager:
        return jsonify({'tracks': []})

    tracks_status = multi_track_manager.get_all_tracks_status()
    return jsonify({'tracks': tracks_status})

@app.route('/api/tracks/<int:track_id>', methods=['GET'])
def get_track(track_id):
    """Get a specific track by ID"""
    track = track_db.get_track_by_id(track_id)
    if track:
        return jsonify(track)
    return jsonify({'error': 'Track not found'}), 404

# Admin track management routes
@app.route('/api/admin/tracks', methods=['GET'])
@admin_required
def admin_get_tracks():
    """Get all tracks with full details (admin only)"""
    # Use track_db which connects to tracks.db
    tracks = track_db.get_all_tracks()

    # Map fields to match admin panel expectations
    mapped_tracks = []
    for track in tracks:
        mapped_tracks.append({
            'id': track['id'],
            'name': track['track_name'],  # Map track_name to name
            'location': track.get('location', ''),
            'length_meters': track.get('length_meters'),
            'description': track.get('description', ''),
            'timing_url': track['timing_url'],
            'websocket_url': track['websocket_url'],
            'column_mappings': track['column_mappings'],
            'is_active': track.get('is_active', True),
            'provider': track.get('provider', 'apex'),
            'created_at': track['created_at'],
            'updated_at': track['updated_at']
        })

    return jsonify(mapped_tracks)

@app.route('/api/admin/tracks', methods=['POST'])
@admin_required
def admin_add_track():
    """Add a new track (admin only)"""
    data = request.json
    if not data or 'name' not in data:
        return jsonify({'error': 'Track name is required'}), 400

    # Use track_db to add the track
    result = track_db.add_track(
        track_name=data['name'],
        timing_url=data.get('timing_url', ''),
        websocket_url=data.get('websocket_url'),
        column_mappings=data.get('column_mappings'),
        location=data.get('location'),
        length_meters=data.get('length_meters'),
        description=data.get('description'),
        is_active=data.get('is_active', True),
        provider=(data.get('provider') or 'apex'),
    )

    if 'error' in result:
        return jsonify({'error': result['error']}), 400

    return jsonify({
        'success': True,
        'track': {
            'id': result['id'],
            'name': data['name']
        }
    }), 201

@app.route('/api/admin/tracks/<int:track_id>', methods=['PUT'])
@admin_required
def admin_update_track(track_id):
    """Update a track (admin only)"""
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Use track_db to update the track
    result = track_db.update_track(
        track_id=track_id,
        track_name=data.get('name'),
        timing_url=data.get('timing_url'),
        websocket_url=data.get('websocket_url'),
        column_mappings=data.get('column_mappings'),
        location=data.get('location'),
        length_meters=data.get('length_meters'),
        description=data.get('description'),
        is_active=data.get('is_active'),
        provider=data.get('provider'),
    )

    if 'error' in result:
        return jsonify({'error': result['error']}), 400

    return jsonify({'success': True})

def _teardown_track_parser(track_id):
    """Best-effort: stop + remove the live parser for a track on the manager's
    event loop, so a deleted track stops being scraped immediately instead of
    lingering until the next backend restart."""
    global multi_track_manager, multi_track_loop
    if not (multi_track_manager and multi_track_loop):
        return False
    try:
        fut = asyncio.run_coroutine_threadsafe(
            multi_track_manager.stop_track_parser(track_id), multi_track_loop)
        return bool(fut.result(timeout=10))
    except Exception as e:
        app.logger.warning(f"Track {track_id}: parser teardown failed: {e}")
        return False


def _restart_track_parser(track_id):
    """Teardown + respawn a single track's parser without restarting the whole
    backend. Used by /api/admin/tracks/<id>/restart-parser to recover stragglers
    that got stuck (e.g. an AlphaHubParser whose requests.Session was flagged
    by Cloudflare bot scoring and is stuck in 429 retry-loop hell).

    The new parser instance gets a fresh requests.Session, fresh startup
    counter slot at the end of the line, and inherits the cached Pusher
    config from tracks.db so it skips the live-page scrape on the in-process
    reconnect path.
    """
    global multi_track_manager, multi_track_loop
    if not (multi_track_manager and multi_track_loop):
        return False
    track = track_db.get_track_by_id(track_id)
    if not track:
        return False
    # Manager.start_track_parser expects the same shape that load_tracks emits.
    track_payload = {
        'id': track['id'],
        'track_name': track['track_name'],
        'websocket_url': track['websocket_url'],
        'column_mappings': track.get('column_mappings'),
        'provider': track.get('provider', 'apex'),
        'pusher_key': track.get('pusher_key'),
        'pusher_cluster': track.get('pusher_cluster'),
        'pusher_site': track.get('pusher_site'),
        'pusher_channel_suffix': track.get('pusher_channel_suffix'),
    }
    try:
        # Stop first (idempotent — returns False if there was nothing to stop).
        fut = asyncio.run_coroutine_threadsafe(
            multi_track_manager.stop_track_parser(track_id), multi_track_loop)
        fut.result(timeout=10)
        # Then respawn the parser task on the same event loop.
        coro = multi_track_manager.start_track_parser(track_payload)
        asyncio.run_coroutine_threadsafe(
            _track_supervisor(track_id, coro), multi_track_loop)
        return True
    except Exception as e:
        app.logger.warning(f"Track {track_id}: parser restart failed: {e}")
        return False


async def _track_supervisor(track_id, coro):
    """Wrap start_track_parser in a task so we can also store the handle in
    manager.tasks (consistent with start_all_parsers). start_track_parser runs
    forever, so we register the task ourselves."""
    task = asyncio.create_task(coro)
    multi_track_manager.tasks[track_id] = task
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


@app.route('/api/admin/tracks/<int:track_id>/restart-parser', methods=['POST'])
@admin_required
def admin_restart_track_parser(track_id):
    """Hot-restart a single track's parser without bouncing the backend.
    Returns 200 on success, 404 if the track doesn't exist, 503 if the
    manager isn't ready, 500 on internal error."""
    global multi_track_manager
    if not multi_track_manager:
        return jsonify({'error': 'multi-track manager not initialized'}), 503
    if not track_db.get_track_by_id(track_id):
        return jsonify({'error': f'unknown track_id {track_id}'}), 404
    ok = _restart_track_parser(track_id)
    return (jsonify({'success': True}), 200) if ok else (jsonify({'error': 'restart failed'}), 500)


@app.route('/api/admin/tracks/<int:track_id>', methods=['DELETE'])
@admin_required
def admin_delete_track(track_id):
    """Delete a track (admin only)"""
    result = track_db.delete_track(track_id)

    if 'error' in result:
        return jsonify({'error': result['error']}), 404

    _teardown_track_parser(track_id)
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Track layouts (admin-managed; public read so fairness UI can populate)
# ---------------------------------------------------------------------------

def _parse_opt_float(payload, key):
    v = payload.get(key) if payload else None
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@app.route('/api/tracks/<int:track_id>/layouts', methods=['GET'])
def list_track_layouts(track_id):
    """List layouts configured for a track. Public so the fairness UI can
    render a layout picker without requiring admin."""
    if not track_db.get_track_by_id(track_id):
        return jsonify({'error': f'Unknown track_id {track_id}'}), 404
    return jsonify({'track_id': track_id, 'layouts': track_db.get_layouts_for_track(track_id)})


@app.route('/api/admin/tracks/<int:track_id>/layouts', methods=['POST'])
@admin_required
def admin_add_track_layout(track_id):
    if not track_db.get_track_by_id(track_id):
        return jsonify({'error': f'Unknown track_id {track_id}'}), 404
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Layout name is required'}), 400
    result = track_db.add_layout(
        track_id=track_id,
        name=name,
        min_field_best=_parse_opt_float(data, 'min_field_best'),
        max_field_best=_parse_opt_float(data, 'max_field_best'),
        is_default=bool(data.get('is_default', False)),
    )
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result), 201


@app.route('/api/admin/layouts/<int:layout_id>', methods=['PUT'])
@admin_required
def admin_update_layout(layout_id):
    data = request.json or {}
    # Allow explicit clearing of bands by passing null / empty string.
    clear_min = 'min_field_best' in data and (data['min_field_best'] in (None, ''))
    clear_max = 'max_field_best' in data and (data['max_field_best'] in (None, ''))
    result = track_db.update_layout(
        layout_id=layout_id,
        name=data.get('name'),
        min_field_best=None if clear_min else _parse_opt_float(data, 'min_field_best'),
        max_field_best=None if clear_max else _parse_opt_float(data, 'max_field_best'),
        is_default=data.get('is_default') if isinstance(data.get('is_default'), bool) else None,
        clear_min=clear_min,
        clear_max=clear_max,
    )
    if 'error' in result:
        status = 404 if result['error'] == 'Layout not found' else 400
        return jsonify(result), status
    return jsonify(result)


@app.route('/api/admin/layouts/<int:layout_id>', methods=['DELETE'])
@admin_required
def admin_delete_layout(layout_id):
    result = track_db.delete_layout(layout_id)
    if 'error' in result:
        return jsonify(result), 404
    return jsonify(result)


# ---------------------------------------------------------------------------
# Session exclusion (admin) — flag a session out of all aggregate analytics.
# Per-session lap data stays in the DB; only the fairness/leaderboard queries
# filter on is_excluded.
# ---------------------------------------------------------------------------

@app.route('/api/admin/tracks/<int:track_id>/sessions/<int:session_id>/exclude', methods=['POST'])
@admin_required
def admin_set_session_exclusion(track_id, session_id):
    """Toggle is_excluded on a single session. Body: {"excluded": true|false}."""
    if not track_db.get_track_by_id(track_id):
        return jsonify({'error': f'Unknown track_id {track_id}'}), 404
    data = request.json or {}
    excluded = 1 if bool(data.get('excluded', True)) else 0
    try:
        with get_track_db_connection(track_id) as conn:
            cur = conn.cursor()
            cur.execute(
                'UPDATE race_sessions SET is_excluded = ? WHERE session_id = ?',
                (excluded, session_id),
            )
            if cur.rowcount == 0:
                return jsonify({'error': f'Session {session_id} not found on track {track_id}'}), 404
            conn.commit()
            row = cur.execute(
                'SELECT session_id, name, start_time, is_excluded FROM race_sessions WHERE session_id = ?',
                (session_id,),
            ).fetchone()
        _audit('admin_session_exclusion',
               actor_user_id=request.current_user['id'],
               target=f'track_{track_id}/session_{session_id}',
               details={'excluded': bool(excluded)})
        return jsonify({
            'track_id': track_id,
            'session_id': row[0],
            'name': row[1],
            'start_time': row[2],
            'is_excluded': bool(row[3]),
        })
    except UnknownTrackError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        app.logger.exception('admin_set_session_exclusion failed')
        return _internal_error(e)


@app.route('/api/admin/tracks/<int:track_id>/sessions/excluded', methods=['GET'])
@admin_required
def admin_list_excluded_sessions(track_id):
    """List sessions on this track currently flagged is_excluded=1."""
    if not track_db.get_track_by_id(track_id):
        return jsonify({'error': f'Unknown track_id {track_id}'}), 404
    try:
        with get_track_db_connection(track_id) as conn:
            rows = conn.execute(
                'SELECT session_id, name, start_time FROM race_sessions WHERE is_excluded = 1 ORDER BY start_time DESC'
            ).fetchall()
        return jsonify({
            'track_id': track_id,
            'excluded': [{'session_id': r[0], 'name': r[1], 'start_time': r[2]} for r in rows],
        })
    except UnknownTrackError as e:
        return jsonify({'error': str(e)}), 404


# ---------------------------------------------------------------------------
# Driver aliases (admin-managed)
# ---------------------------------------------------------------------------



# Test endpoints for simulating track sessions.
# Routes are only registered when ENABLE_TEST_ENDPOINTS=true; in production
# (default) they don't exist at all and return 404.
if ENABLE_TEST_ENDPOINTS:
    @app.route('/api/test/simulate-session/<int:track_id>', methods=['POST'])
    @admin_required
    def simulate_track_session(track_id):
        """Simulate an active session on a track for testing purposes"""
        global multi_track_manager

        if not multi_track_manager:
            return jsonify({'error': 'Multi-track manager not initialized'}), 500

        if track_id not in multi_track_manager.parsers:
            return jsonify({'error': f'Track {track_id} not found'}), 404

        parser = multi_track_manager.parsers[track_id]

        from datetime import datetime
        parser.last_data_time = datetime.now()
        parser.session_active_status = True

        room = f'track_{track_id}'
        socketio.emit('session_status', {
            'track_id': track_id,
            'track_name': parser.track_name,
            'active': True,
            'message': 'Simulated session active',
            'timestamp': datetime.now().isoformat()
        }, room=room)

        multi_track_manager.broadcast_all_tracks_status()

        return jsonify({
            'success': True,
            'message': f'Simulated active session for track {track_id} ({parser.track_name})',
            'track_id': track_id,
            'track_name': parser.track_name
        })

    @app.route('/api/test/stop-session/<int:track_id>', methods=['POST'])
    @admin_required
    def stop_simulated_session(track_id):
        """Stop simulated session on a track"""
        global multi_track_manager

        if not multi_track_manager:
            return jsonify({'error': 'Multi-track manager not initialized'}), 500

        if track_id not in multi_track_manager.parsers:
            return jsonify({'error': f'Track {track_id} not found'}), 404

        parser = multi_track_manager.parsers[track_id]

        parser.last_data_time = None
        parser.session_active_status = False

        from datetime import datetime
        room = f'track_{track_id}'
        socketio.emit('session_status', {
            'track_id': track_id,
            'track_name': parser.track_name,
            'active': False,
            'message': 'Simulated session stopped',
            'timestamp': datetime.now().isoformat()
        }, room=room)

        multi_track_manager.broadcast_all_tracks_status()

        return jsonify({
            'success': True,
            'message': f'Stopped simulated session for track {track_id} ({parser.track_name})',
            'track_id': track_id,
            'track_name': parser.track_name
        })

# Keep original track routes for backwards compatibility
@app.route('/api/tracks', methods=['POST'])
@admin_required
def add_track():
    """Add a new track to the database"""
    data = request.json
    if not data or 'track_name' not in data or 'timing_url' not in data:
        return jsonify({'error': 'track_name and timing_url are required'}), 400
    
    result = track_db.add_track(
        track_name=data['track_name'],
        timing_url=data['timing_url'],
        websocket_url=data.get('websocket_url'),
        column_mappings=data.get('column_mappings')
    )
    
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result), 201

@app.route('/api/tracks/<int:track_id>', methods=['PUT'])
@admin_required
def update_track(track_id):
    """Update a track in the database"""
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    result = track_db.update_track(
        track_id=track_id,
        track_name=data.get('track_name'),
        timing_url=data.get('timing_url'),
        websocket_url=data.get('websocket_url'),
        column_mappings=data.get('column_mappings')
    )
    
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result)

@app.route('/api/tracks/<int:track_id>', methods=['DELETE'])
@admin_required
def delete_track(track_id):
    """Delete a track from the database"""
    result = track_db.delete_track(track_id)

    if 'error' in result:
        return jsonify(result), 404
    _teardown_track_parser(track_id)
    return jsonify(result)

@app.route('/api/reset-race-data', methods=['POST'])
@admin_required
def reset_race_data():
    """Reset all race data when switching tracks"""
    global race_data

    # Preserve configuration settings
    preserved_config = {
        'pit_config': race_data.get('pit_config', {
            'required_stops': REQUIRED_PIT_STOPS,
            'pit_time': PIT_STOP_TIME
        }),
        'my_team': race_data.get('my_team'),
        'monitored_teams': race_data.get('monitored_teams', [])
    }

    # Reset race data
    race_data = {
        'teams': [],
        'session_info': {},
        'last_update': None,
        'my_team': preserved_config['my_team'],
        'monitored_teams': preserved_config['monitored_teams'],
        'delta_times': {},
        'gap_history': {},
        'pit_config': preserved_config['pit_config'],
        'race_time': 0,
        'is_running': False,
        'simulation_mode': False,
        'timing_url': None,
        'websocket_url': None,
        'column_mappings': None
    }

    # Emit reset event to all connected clients
    socketio.emit('race_data_reset', room='race_updates')

    return jsonify({'status': 'success', 'message': 'Race data reset'})

# Team data analysis API endpoints


# ---------------------------------------------------------------------------
# Driver Stats: consistency and kart-fairness
# ---------------------------------------------------------------------------

def _name_tokens(raw):
    """Split a user-supplied name into lowercase tokens for flexible matching."""
    return [t for t in (raw or '').strip().lower().split() if t]


def _name_like_clause(alias_col, tokens):
    """Build 'LOWER(col) LIKE ? AND ...' clause + params for flexible name match."""
    if not tokens:
        return "1=1", []
    clauses = [f"LOWER({alias_col}) LIKE ?"] * len(tokens)
    params = [f"%{t}%" for t in tokens]
    return " AND ".join(clauses), params


_DRIVER_CLASS_PREFIX_RE = re.compile(r'^(HC|JR|G)\s*-\s*', re.IGNORECASE)

# Recognisable test / staff placeholder names to drop from per-driver analytics.
# Matches whole-string against known patterns (APEXTEST, 'test 2', 'equipe test',
# 'pilote test', 'test <N>', 'tet <N>' typo, plain 'test'/'essai'). Anchored with
# ^...$ so real names containing "test" as a substring (e.g. MOTTET) are safe.
_TEST_NAME_RE = re.compile(
    r'^(?:apex\s*test\d*|equipe\s*test[e]?|pilote\s*test|tes?t\s*\d+|test|essai\d*)$',
    re.IGNORECASE,
)


def _is_test_placeholder(name):
    """True for team_name values that are clearly test/staff placeholders."""
    if not name:
        return False
    return bool(_TEST_NAME_RE.match(name.strip()))


def _strip_driver_class_prefix(name):
    """Strip per-driver class tags (Heavy Cup / Junior / Ghost) from a team_name.

    The organizer tags some drivers by category, so "HC - TORLET Corentin" and
    "TORLET Corentin" are the same person racing in different classes. Stripping
    these collapses them onto a single driver for per-driver aggregations. We do
    NOT strip numeric ("1 - ", "2 - ") or Funyo ("F80 - ", "F95 - ") prefixes
    because those identify endurance TEAMS, not individual drivers.
    """
    if not name:
        return name
    return _DRIVER_CLASS_PREFIX_RE.sub('', name).strip()


def _expand_alias_group(name):
    """Return the full list of names that belong to the same alias group as `name`.

    Admin-managed driver_aliases table maps a canonical name to any number of
    alias names. Given an input name, this returns every name in its group
    (canonical plus all aliases), plus the input name itself. Case-insensitive.
    """
    n = (name or '').strip()
    if not n:
        return []
    names = {n}
    try:
        with sqlite3.connect('auth.db') as conn:
            # Canonicals reachable from the input (either input is the canonical
            # directly, or input is an alias of some canonical).
            canons = {
                row[0] for row in conn.execute(
                    '''SELECT canonical_name FROM driver_aliases
                       WHERE canonical_name = ? COLLATE NOCASE
                          OR alias_name     = ? COLLATE NOCASE''',
                    (n, n),
                ).fetchall()
            }
            canons.add(n)
            # All aliases of every canonical in the group
            for c in list(canons):
                for row in conn.execute(
                    'SELECT alias_name FROM driver_aliases WHERE canonical_name = ? COLLATE NOCASE',
                    (c,),
                ).fetchall():
                    names.add(row[0])
                names.add(c)
    except sqlite3.Error as e:
        app.logger.warning(f"alias expansion failed for {n!r}: {e}")
    return list(names)


def _multi_name_clause(alias_col, names):
    """Build a SQL clause that matches if ANY of `names` matches (token-AND within
    each name, OR across names). Returns (clause, params).

    e.g. names=['Tanguy Pedrazzoli', 'Tankyx'] ->
         ((LOWER(col) LIKE '%tanguy%' AND LOWER(col) LIKE '%pedrazzoli%')
          OR (LOWER(col) LIKE '%tankyx%'))
    """
    if not names:
        return "1=0", []
    groups = []
    all_params = []
    for n in names:
        tokens = _name_tokens(n)
        if not tokens:
            continue
        clause, params = _name_like_clause(alias_col, tokens)
        groups.append(f"({clause})")
        all_params.extend(params)
    if not groups:
        return "1=0", []
    return "(" + " OR ".join(groups) + ")", all_params


def _name_matches_any(team_name, alias_names):
    """Python-side check: does team_name match any alias (token-AND)?"""
    tl = (team_name or '').lower()
    for n in alias_names:
        toks = _name_tokens(n)
        if toks and all(t in tl for t in toks):
            return True
    return False


def _find_matching_team_names(cur, alias_names):
    """Fast name resolution: use the (team_name, session_id) covering index to
    scan DISTINCT team_name values — small result, typically <2000 rows per
    track — then filter in Python. Avoids full-table scans that substring
    LIKE on lap_times would trigger.

    Returns (names_from_lap_history, names_from_lap_times).
    """
    history_names = []
    cur.execute('SELECT DISTINCT team_name FROM lap_history')
    for (name,) in cur.fetchall():
        if name and _name_matches_any(name, alias_names):
            history_names.append(name)

    times_names = []
    cur.execute('SELECT DISTINCT team_name FROM lap_times')
    for (name,) in cur.fetchall():
        if name and _name_matches_any(name, alias_names):
            times_names.append(name)

    return history_names, times_names


def _fetch_driver_session_ids(cur, history_names, times_names):
    """Return every session (session_id, name, start_time) where any of the given
    exact team_name values appears in EITHER lap_history or lap_times. Ordered
    newest first. Using both tables catches sessions where the parser wrote to
    lap_times but not lap_history.
    """
    if not history_names and not times_names:
        return []
    placeholders_h = ','.join('?' * len(history_names)) if history_names else ''
    placeholders_t = ','.join('?' * len(times_names)) if times_names else ''

    conditions = []
    params = []
    if history_names:
        conditions.append(
            f'rs.session_id IN (SELECT DISTINCT session_id FROM lap_history WHERE team_name IN ({placeholders_h}))'
        )
        params.extend(history_names)
    if times_names:
        conditions.append(
            f'rs.session_id IN (SELECT DISTINCT session_id FROM lap_times WHERE team_name IN ({placeholders_t}))'
        )
        params.extend(times_names)

    cur.execute(
        f"""
        SELECT rs.session_id, rs.name, rs.start_time FROM race_sessions rs
         WHERE {' OR '.join(conditions)}
         ORDER BY rs.start_time DESC
        """,
        params,
    )
    return cur.fetchall()


LAP_MIN_SECONDS = 20.0  # shorter than any real karting lap; anything below is a sector/artefact
LAP_MAX_SECONDS = 600.0  # pit-in laps top out well below this; mostly catches garbage
MAD_Z_THRESHOLD = 3.5    # modified-Z cutoff for outlier detection (Iglewicz & Hoaglin 1993)
MAD_MIN_SAMPLES = 5      # skip MAD filter for very small session samples


def _filter_outliers_mad(laps_with_flag, z_threshold=MAD_Z_THRESHOLD):
    """Statistical outlier filter using the modified Z-score (median + MAD).

    Lap times are right-skewed (most laps near race pace, a few slow pit or
    flag laps), so median/MAD is more robust than mean/σ — outliers don't
    inflate the reference values. Only applied to on-track laps; pit-in laps
    are preserved as-is (they're identified separately by the pit counter).

    For a reasonable symmetric approximation to the normal distribution the
    scaling constant is 0.6745; |modified_z| > 3.5 is a common outlier cutoff.
    """
    if len(laps_with_flag) < MAD_MIN_SAMPLES:
        return laps_with_flag

    on_track_secs = [s for s, pit in laps_with_flag if not pit]
    if len(on_track_secs) < MAD_MIN_SAMPLES:
        return laps_with_flag

    sorted_secs = sorted(on_track_secs)
    median = sorted_secs[len(sorted_secs) // 2]
    deviations = sorted(abs(s - median) for s in on_track_secs)
    mad = deviations[len(deviations) // 2]
    if mad == 0:
        return laps_with_flag  # all samples identical — nothing meaningful to filter

    out = []
    for s, is_pit in laps_with_flag:
        if is_pit:
            out.append((s, is_pit))
            continue
        z = 0.6745 * abs(s - median) / mad
        if z <= z_threshold:
            out.append((s, is_pit))
    return out


def _dedupe_laps(rows):
    """From ordered (raw_lap_time, cumulative_pit_count) tuples, dedupe stale
    repeated lap-time strings and convert to (seconds, is_pit_lap) list.

    A pit-in lap is detected by an increase in the cumulative pit counter from
    one kept row to the next. Values outside [LAP_MIN_SECONDS, LAP_MAX_SECONDS]
    are dropped — this catches sector-time artefacts that occasionally appear
    in the live-timing last_lap field (e.g. 4.32s "laps").
    """
    out = []
    prev_raw = None
    prev_pit = 0
    for raw, pit in rows:
        if raw == prev_raw:
            continue
        prev_raw = raw
        secs = _safe_parse_time(raw)
        if secs == float('inf') or secs < LAP_MIN_SECONDS or secs > LAP_MAX_SECONDS:
            continue
        pit_count = int(pit) if pit is not None else prev_pit
        is_pit = pit_count > prev_pit
        prev_pit = pit_count
        out.append((secs, is_pit))
    return out


def _fetch_laps_from_history(cur, session_id, team_names):
    """team_names: exact team_name values (use _find_matching_team_names)."""
    if not team_names:
        return []
    placeholders = ','.join('?' * len(team_names))
    cur.execute(
        f"""
        SELECT lap_time, pit_this_lap FROM lap_history
         WHERE session_id = ? AND team_name IN ({placeholders})
           AND lap_time IS NOT NULL AND lap_time != ''
         ORDER BY timestamp ASC
        """,
        [session_id] + team_names,
    )
    return _dedupe_laps(cur.fetchall())


def _fetch_laps_from_lap_times(cur, session_id, team_names):
    """Reconstruct the driver's completed laps from lap_times snapshots.

    lap_times is written on every polling tick (~1Hz), so `last_lap` repeats
    many times until a new lap is completed. A SQL window function dedupes at
    the DB layer to avoid pulling tens of thousands of rows into Python.
    """
    if not team_names:
        return []
    placeholders = ','.join('?' * len(team_names))
    cur.execute(
        f"""
        WITH ordered AS (
            SELECT timestamp, last_lap, pit_stops,
                   LAG(last_lap) OVER (ORDER BY timestamp) AS prev_lap
              FROM lap_times
             WHERE session_id = ? AND team_name IN ({placeholders})
               AND last_lap IS NOT NULL AND last_lap != ''
        )
        SELECT last_lap, pit_stops FROM ordered
         WHERE prev_lap IS NULL OR last_lap != prev_lap
         ORDER BY timestamp ASC
        """,
        [session_id] + team_names,
    )
    return _dedupe_laps(cur.fetchall())


def _fetch_laps_for_session(cur, session_id, history_names, times_names):
    """Prefer lap_history; fall back to lap_times if the former is empty.
    Applies MAD-based outlier filter per session so garbage values outside
    the sanity window but still within a plausible seconds range are dropped.
    """
    laps = _fetch_laps_from_history(cur, session_id, history_names)
    if not laps:
        laps = _fetch_laps_from_lap_times(cur, session_id, times_names)
    return _filter_outliers_mad(laps)


def _format_seconds(sec):
    """Format seconds as M:SS.mmm (or None)."""
    if sec is None or sec == float('inf'):
        return None
    mins = int(sec // 60)
    rem = sec - mins * 60
    return f"{mins}:{rem:06.3f}"


def _classify_session_mode(cur, session_id, history_names, times_names):
    """Determine if the driver ran sprint or endurance in a given session.

    Tries `lap_history` first (richer per-lap data). Falls back to `lap_times`
    snapshots for sessions where the parser never wrote lap_history rows (which
    happens on some tracks — see _fetch_driver_session_ids).

    Returns one of: 'sprint', 'endurance', 'unknown'. Heuristic: >1 kart = sprint;
    single kart with ≥2 cumulative pits and ≥10 lap samples = endurance;
    single kart, zero pits, <30 samples = single short heat (treated as sprint).
    """
    def _classify(karts, max_pits, laps):
        if laps == 0:
            return None
        if karts > 1:
            return 'sprint'
        if karts == 1 and max_pits >= 2 and laps >= 10:
            return 'endurance'
        if karts == 1 and max_pits == 0 and laps < 30:
            return 'sprint'
        return 'unknown'

    if history_names:
        placeholders = ','.join('?' * len(history_names))
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT kart_number), MAX(pit_this_lap), COUNT(*)
              FROM lap_history
             WHERE session_id=? AND team_name IN ({placeholders})
            """,
            [session_id] + history_names,
        )
        row = cur.fetchone() or (0, 0, 0)
        mode = _classify(row[0] or 0, row[1] or 0, row[2] or 0)
        if mode is not None:
            return mode

    if times_names:
        placeholders = ','.join('?' * len(times_names))
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT kart_number), MAX(pit_stops), COUNT(DISTINCT last_lap)
              FROM lap_times
             WHERE session_id=? AND team_name IN ({placeholders})
               AND last_lap IS NOT NULL AND last_lap != ''
            """,
            [session_id] + times_names,
        )
        row = cur.fetchone() or (0, 0, 0)
        mode = _classify(row[0] or 0, row[1] or 0, row[2] or 0)
        if mode is not None:
            return mode

    return 'unknown'


def _stddev(values):
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return var ** 0.5


def _percentile_rank(value, population):
    """Return percentile rank (0-100) of value within population (lower value -> lower rank)."""
    if not population:
        return None
    below = sum(1 for v in population if v < value)
    return round(100.0 * below / len(population), 1)




# ---------------------------------------------------------------------------
# Statistical helpers (no scipy available — pure-Python implementations)
# ---------------------------------------------------------------------------

def _normal_cdf(z):
    """Standard-normal CDF Φ(z) via math.erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _gammainc_upper_reg(a, x):
    """Regularised upper incomplete gamma Q(a, x) = Γ(a, x) / Γ(a).

    Series below the crossover, Lentz's continued fraction above. Standard
    Numerical Recipes technique; good to ~12 significant digits for the
    regimes we use (a in {1, 1.5, 2, ...}, x >= 0).
    """
    if x < 0 or a <= 0:
        return float('nan')
    if x == 0:
        return 1.0
    log_pref = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1.0:
        term = 1.0 / a
        total = term
        for n in range(1, 500):
            term *= x / (a + n)
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        p_lower = total * math.exp(log_pref)
        return max(0.0, min(1.0, 1.0 - p_lower))
    # Continued fraction for Q(a, x) when x >= a+1
    b = x + 1.0 - a
    c = 1e300
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return max(0.0, min(1.0, h * math.exp(log_pref)))


def _chi2_sf(chi2, df):
    """P(X > chi2) for chi-squared with df degrees of freedom."""
    if chi2 <= 0 or df <= 0:
        return 1.0
    return _gammainc_upper_reg(df / 2.0, chi2 / 2.0)


def _quantile(sorted_values, q):
    """Linear-interpolated quantile (type-7, same as numpy.quantile default).

    `sorted_values` must already be sorted ascending; returns None for empty.
    """
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return sorted_values[0]
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


# ---------------------------------------------------------------------------
# Layout + window filter helpers
# ---------------------------------------------------------------------------

# Sessions with this many session-best samples are surfaced as aggregates,
# but a higher bar is required before we'll quote a randomness verdict —
# a binomial test on 5 samples has almost no power against plausible
# alternatives.
MIN_SESSIONS_AGG = 5
MIN_SESSIONS_VERDICT = 20


def _window_cutoff(window_months):
    """Return an ISO-8601 string cutoff, or None to disable filtering.

    `window_months <= 0` (or None) disables; otherwise cutoff = now - N * 30d.
    """
    if not window_months or window_months <= 0:
        return None
    cutoff = datetime.now() - timedelta(days=int(window_months) * 30)
    return cutoff.isoformat()


def _load_track_layouts(track_id):
    """Wrapper that returns [] on error — callers treat 'no layouts' as a
    no-op rather than failing the whole query."""
    try:
        return track_db.get_layouts_for_track(track_id)
    except Exception as e:
        app.logger.warning(f"layout load failed for track {track_id}: {e}")
        return []


def _match_layout_for_field_best(field_best_seconds, layouts, default_layout):
    """Pick the layout whose [min, max) band contains field_best. Falls back
    to the default layout (if any), else None."""
    for lay in layouts:
        lo = lay.get('min_field_best')
        hi = lay.get('max_field_best')
        if lo is not None and field_best_seconds < lo:
            continue
        if hi is not None and field_best_seconds >= hi:
            continue
        return lay
    return default_layout


def _ensure_session_layouts(conn, track_id, session_field_best):
    """Backfill layout_id for any session currently NULL, using the session's
    field-best vs the track's configured layout bands.

    `session_field_best` is a {session_id: field_best_seconds} dict that the
    caller has already computed from lap_times (avoids a second scan).
    Safe no-op if no layouts are configured for the track.
    """
    layouts = _load_track_layouts(track_id)
    if not layouts:
        return
    default_layout = next((l for l in layouts if l.get('is_default')), None)
    cur = conn.cursor()
    cur.execute('SELECT session_id FROM race_sessions WHERE layout_id IS NULL')
    null_sids = [r[0] for r in cur.fetchall()]
    if not null_sids:
        return
    updates = []
    for sid in null_sids:
        fb = session_field_best.get(sid)
        if fb is None:
            continue
        chosen = _match_layout_for_field_best(fb, layouts, default_layout)
        if chosen:
            updates.append((chosen['id'], sid))
    if updates:
        cur.executemany(
            'UPDATE race_sessions SET layout_id = ? WHERE session_id = ?',
            updates,
        )
        conn.commit()


def _filter_sessions_by_layout_and_window(conn, layout_id, window_cutoff_iso):
    """Return the set of session_ids that pass the layout + window filters
    AND are not flagged is_excluded=1. Excluded sessions are always dropped
    from analytics — admins use the exclusion flag exactly because they
    shouldn't influence aggregates.

    Returns a set (possibly empty) when any filter applies; returns None
    only when no filters AND no exclusions exist, so callers can skip work.
    """
    cur = conn.cursor()
    # Cheap probe for any excluded sessions; if there are none and no other
    # filters, the caller can fast-path with `None` and skip the scan.
    cur.execute("SELECT COUNT(*) FROM race_sessions WHERE is_excluded = 1")
    has_exclusions = (cur.fetchone()[0] or 0) > 0

    if layout_id is None and window_cutoff_iso is None and not has_exclusions:
        return None

    clauses = ['(is_excluded IS NULL OR is_excluded = 0)']
    params: list = []
    if layout_id is not None:
        clauses.append('layout_id = ?')
        params.append(layout_id)
    if window_cutoff_iso is not None:
        clauses.append('start_time >= ?')
        params.append(window_cutoff_iso)
    cur.execute(
        f"SELECT session_id FROM race_sessions WHERE {' AND '.join(clauses)}",
        params,
    )
    return {r[0] for r in cur.fetchall()}


def _kart_bests_from_lap_history(cur, session_id):
    cur.execute(
        """
        SELECT kart_number, lap_time FROM lap_history
         WHERE session_id=? AND lap_time IS NOT NULL AND lap_time != ''
           AND kart_number IS NOT NULL
        """,
        (session_id,),
    )
    out = {}
    for kart, lt in cur.fetchall():
        secs = _safe_parse_time(lt)
        if secs == float('inf') or secs < LAP_MIN_SECONDS or secs > LAP_MAX_SECONDS:
            continue
        if kart not in out or secs < out[kart]:
            out[kart] = secs
    return out


def _kart_bests_from_lap_times(cur, session_id):
    """For sessions that only exist in lap_times, read the per-kart `best_lap`
    column. best_lap is a running-best snapshot per row; we take the min over
    all snapshots for each kart, then drop karts whose 'best' is so far below
    the session median that it must be a display/sector-time artefact (no real
    kart runs more than ~20% faster than the median of the field on the same
    track).
    """
    cur.execute(
        """
        SELECT DISTINCT kart_number, best_lap FROM lap_times
         WHERE session_id=? AND best_lap IS NOT NULL AND best_lap != ''
           AND kart_number IS NOT NULL
        """,
        (session_id,),
    )
    out = {}
    for kart, bl in cur.fetchall():
        secs = _safe_parse_time(bl)
        if secs == float('inf') or secs < LAP_MIN_SECONDS or secs > LAP_MAX_SECONDS:
            continue
        if kart not in out or secs < out[kart]:
            out[kart] = secs

    if len(out) < 5:
        return out

    values = sorted(out.values())
    median = values[len(values) // 2]
    # Fastest realistic kart on a given track isn't more than ~25% faster than the
    # median pace of the field — anything below that floor is parser noise.
    floor = median * 0.75
    return {k: v for k, v in out.items() if v >= floor}


def _driver_karts_in_session(cur, session_id, history_names, times_names):
    """Exact team_name IN (...) against both tables; union of returned karts."""
    karts = set()
    if history_names:
        placeholders = ','.join('?' * len(history_names))
        cur.execute(
            f"""
            SELECT DISTINCT kart_number FROM lap_history
             WHERE session_id=? AND team_name IN ({placeholders})
               AND kart_number IS NOT NULL
            """,
            [session_id] + history_names,
        )
        karts.update(r[0] for r in cur.fetchall())
    if times_names:
        placeholders = ','.join('?' * len(times_names))
        cur.execute(
            f"""
            SELECT DISTINCT kart_number FROM lap_times
             WHERE session_id=? AND team_name IN ({placeholders})
               AND kart_number IS NOT NULL
            """,
            [session_id] + times_names,
        )
        karts.update(r[0] for r in cur.fetchall())
    return karts


def _analyze_sprint_session(cur, session_id, session_date, history_names, times_names):
    """Return list of kart-factor samples for this driver in this session.

    Each sample = one (driver, kart_number) pair within the session. Uses
    lap_history for per-kart bests when available; falls back to lap_times
    best_lap snapshots otherwise.

    The session median used as the kart-factor denominator is computed
    leave-one-out — it excludes the karts the target driver sat in — so a
    driver's own pace cannot move the baseline they're measured against. If
    leaving the driver's karts out drops the remaining field below 3 karts
    we fall back to the full-field median (the self-reference bias is small
    at that point anyway because each driver accounts for only ~1/3 of the
    field).
    """
    kart_best = _kart_bests_from_lap_history(cur, session_id)
    if len(kart_best) < 3:
        kart_best = _kart_bests_from_lap_times(cur, session_id)
    if len(kart_best) < 3:
        return []

    driver_karts = [k for k in _driver_karts_in_session(cur, session_id, history_names, times_names) if k in kart_best]
    if not driver_karts:
        return []

    driver_kart_set = set(driver_karts)
    field_values = sorted(kart_best.values())
    field_median = field_values[len(field_values) // 2]
    if field_median <= 0:
        return []

    loo_values = sorted(v for k, v in kart_best.items() if k not in driver_kart_set)
    if len(loo_values) >= 3:
        loo_median = loo_values[len(loo_values) // 2]
        median_source = 'leave_one_out'
    else:
        loo_median = field_median
        median_source = 'full_field'
    if loo_median <= 0:
        return []

    ranked = sorted(kart_best.items(), key=lambda kv: kv[1])
    rank_of = {k: i + 1 for i, (k, _) in enumerate(ranked)}
    n_karts = len(kart_best)

    samples = []
    for kart in driver_karts:
        kb = kart_best[kart]
        rank = rank_of[kart]
        # Continuous percentile rank in (0, 1). Under random kart assignment
        # this is Uniform(0, 1) — the basis for the chi-sq + binomial tests
        # in the caller. (rank - 0.5)/K avoids boundary effects from integer
        # thresholds like floor(K/4).
        percentile = (rank - 0.5) / n_karts
        samples.append({
            'session_id': session_id,
            'session_date': session_date,
            'kart_number': kart,
            'kart_best_seconds': round(kb, 3),
            'session_median_seconds': round(loo_median, 3),
            'session_median_source': median_source,
            'kart_factor': round(kb / loo_median, 5),
            'kart_rank': rank,
            'karts_in_session': n_karts,
            'rank_percentile': round(percentile, 6),
        })
    return samples


def _segment_stints(laps):
    """Group chronologically-sorted lap rows into stints.

    Input: list of tuples (timestamp, lap_time_seconds, cumulative_pit_count).
    A new stint begins when the cumulative pit count increases. For each stint,
    the first lap (the pit-in lap itself) is excluded from pace stats since it's
    much slower than regular laps.
    Returns: list of dicts with best/mean/start/end/lap_count over *clean* laps.
    """
    if not laps:
        return []
    stints = []
    current = []
    prev_pit = laps[0][2] if laps[0][2] is not None else 0
    for ts, secs, pit in laps:
        pit_count = pit if pit is not None else prev_pit
        if pit_count > prev_pit and current:
            stints.append(current)
            current = []
        current.append((ts, secs))
        prev_pit = pit_count
    if current:
        stints.append(current)

    out = []
    for st in stints:
        # Drop the first lap of the stint (the pit-in lap for all stints after
        # the opening one) when we have enough samples to spare.
        clean = st[1:] if len(st) > 2 else st
        # Hard ceiling to eliminate remaining pit laps that slipped through
        values = [s for _, s in clean]
        if len(values) >= 3:
            sorted_v = sorted(values)
            median_v = sorted_v[len(sorted_v) // 2]
            ceiling = max(180.0, median_v * 2.0)
            values = [v for v in values if v <= ceiling] or values
        if not values:
            continue
        out.append({
            'start_ts': st[0][0],
            'end_ts': st[-1][0],
            'lap_count': len(values),
            'best': min(values),
            'mean': sum(values) / len(values),
        })
    return out


def _analyze_endurance_session(cur, session_id, session_date, driver_names):
    """Compute stint-pace stability for the driver's team in an endurance session.

    Returns a dict with the team's stats plus percentile vs. field (other teams
    in the same session), or None if not enough data. `driver_names` is the
    alias group.
    """
    # Fetch ALL lap_history for the session (used for field analysis)
    cur.execute(
        """
        SELECT team_name, timestamp, lap_time, pit_this_lap
          FROM lap_history
         WHERE session_id = ? AND lap_time IS NOT NULL AND lap_time != ''
         ORDER BY team_name, timestamp ASC
        """,
        (session_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return None

    per_team = {}
    prev_raw = {}  # team -> last-seen lap_time string, to dedupe stale snapshots
    for team, ts, lt, pit in rows:
        if lt == prev_raw.get(team):
            continue
        prev_raw[team] = lt
        secs = _safe_parse_time(lt)
        if secs == float('inf') or secs <= 0 or secs > 600:
            continue
        # pit is the cumulative pit count at this row; pass it through as-is
        # so _segment_stints can detect increases.
        per_team.setdefault(team, []).append((ts, secs, int(pit) if pit is not None else 0))

    # Match driver's team name among teams in this session. A team_name matches
    # if any alias name's tokens are all present in it (case-insensitive).
    def _matches_any(team_name):
        tl = (team_name or '').lower()
        for n in driver_names:
            toks = _name_tokens(n)
            if toks and all(t in tl for t in toks):
                return True
        return False

    driver_teams = [t for t in per_team.keys() if _matches_any(t)]
    if not driver_teams:
        return None

    # Build stints per team
    team_stints = {t: _segment_stints(per_team[t]) for t in per_team}

    # Session reference per stint: for each stint of driver's team, compute
    # min best-lap across all OTHER teams whose laps overlap the stint time window.
    results_for_field = {}  # team -> list of stint gaps
    for team, stints in team_stints.items():
        gaps = []
        for st in stints:
            s0, s1 = st['start_ts'], st['end_ts']
            # Fastest lap among all OTHER teams during [s0, s1]
            fastest_other = float('inf')
            for other, other_laps in per_team.items():
                if other == team:
                    continue
                for ts, secs, _pit in other_laps:
                    if ts >= s0 and ts <= s1 and secs < fastest_other:
                        fastest_other = secs
            if fastest_other == float('inf'):
                continue
            gaps.append(st['best'] - fastest_other)
        if gaps:
            results_for_field[team] = gaps

    if not results_for_field:
        return None

    # Per-team aggregates
    field_mean = {}
    field_sd = {}
    for team, gaps in results_for_field.items():
        field_mean[team] = sum(gaps) / len(gaps)
        field_sd[team] = _stddev(gaps)

    # Driver stats (pick first matching team; usually just one)
    driver_team = next((t for t in driver_teams if t in results_for_field), None)
    if not driver_team:
        return None

    mean_pop = list(field_mean.values())
    sd_pop = list(field_sd.values())
    mean_pct = _percentile_rank(field_mean[driver_team], mean_pop)
    sd_pct = _percentile_rank(field_sd[driver_team], sd_pop)
    flagged = (
        mean_pct is not None and sd_pct is not None
        and mean_pct <= 20 and sd_pct <= 20
        and len(results_for_field) >= 5
    )

    return {
        'session_id': session_id,
        'session_date': session_date,
        'driver_team_name': driver_team,
        'field_team_count': len(results_for_field),
        'stint_count': len(results_for_field[driver_team]),
        'stint_gaps': [round(g, 3) for g in results_for_field[driver_team]],
        'mean_gap': round(field_mean[driver_team], 3),
        'stddev_gap': round(field_sd[driver_team], 3),
        'mean_percentile': mean_pct,
        'stddev_percentile': sd_pct,
        'flagged': flagged,
    }


# ---------------------------------------------------------------------------
# Fleet Tracker — live physical-machine tracking for endurance races
# ---------------------------------------------------------------------------
# The Apex Timing feed exposes only team identity (the number plate follows the
# team). Which *physical* kart a team runs each stint is supplied manually by
# the operator via fleet_assignments. This block segments each team's race into
# stints, residualizes each stint's pace against a rolling field reference (to
# cancel track conditions), and attributes the residual to the physical kart
# currently mapped to that team — producing a live fleet quality ranking plus
# "fast/slow machine in the pits" signals. See _segment_stints / the kart-
# fairness residualization for the methodology this reuses.

FLEET_MIN_SAMPLE_LAPS = 5          # below this, a kart's pace reads 'insufficient'
FLEET_FIELD_WINDOW_SECONDS = 600   # rolling field-reference window (~10 min)
FLEET_MIN_BAND_SECONDS = 0.15      # floor for the fast/slow classification band

# Fleet data is per user, so the cache is keyed by (track_id, user_id).
# {(track_id, user_id): {session_id, computed_at, payload}}
_fleet_cache = {}


def _live_session_id(track_id):
    """Current session id from the live parser, or None when not running."""
    if multi_track_manager and track_id in multi_track_manager.parsers:
        return getattr(multi_track_manager.parsers[track_id], 'current_session_id', None)
    return None


def _live_standings_df(track_id):
    """Current standings DataFrame from the live parser (for location/holder),
    or None when the parser isn't running or has no data."""
    try:
        if multi_track_manager and track_id in multi_track_manager.parsers:
            df = multi_track_manager.parsers[track_id].get_current_standings()
            if df is not None and not df.empty:
                return df
    except Exception:
        pass
    return None


def _fleet_assignment_map(cur, session_id, user_id):
    """team_name -> {stint_index: fleet_kart_id} for this user, using the newest
    non-superseded row per (team, stint_index)."""
    cur.execute(
        """SELECT team_name, stint_index, fleet_kart_id
             FROM fleet_assignments
            WHERE session_id = ? AND user_id = ? AND superseded = 0
            ORDER BY team_name, stint_index, created_at ASC, id ASC""",
        (session_id, user_id),
    )
    amap = {}
    for team, stint_idx, kid in cur.fetchall():
        amap.setdefault(team, {})[stint_idx] = kid  # last (newest) wins
    return amap


def _infer_stint_index(cur, session_id, team_name):
    """Best-effort current stint index = cumulative pit count for the team."""
    cur.execute(
        "SELECT MAX(pit_this_lap) FROM lap_history WHERE session_id = ? AND team_name = ?",
        (session_id, team_name),
    )
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _compute_live_fleet_pace(conn, session_id, user_id, standings_df=None):
    """Core fleet pace fingerprint for one user. Reads lap_history (shared) +
    the user's fleet tables for the session and returns the board body.

    Pure with respect to its inputs (conn + standings_df) so it is unit-testable
    without a live websocket. standings_df (optional) supplies live location and
    holder kart-number/position from the current feed.
    """
    cur = conn.cursor()

    # 1. This user's active registry: id -> (label, lane)
    cur.execute(
        "SELECT id, label, lane FROM fleet_karts WHERE is_active = 1 AND user_id = ? ORDER BY label",
        (user_id,))
    registry = {}
    kart_lane = {}
    for kid, label, lane in cur.fetchall():
        registry[kid] = label
        kart_lane[kid] = lane

    # 2. Per-team clean lap series (reuse the dedup/parse/clamp of the endurance
    #    analyzer) and a flat field list for the rolling reference.
    cur.execute(
        """SELECT team_name, timestamp, lap_time, pit_this_lap
             FROM lap_history
            WHERE session_id = ? AND lap_time IS NOT NULL AND lap_time != ''
            ORDER BY team_name, timestamp ASC""",
        (session_id,),
    )
    per_team = {}
    prev_raw = {}
    all_clean = []  # (ts, secs) across the whole field
    for team, ts, lt, pit in cur.fetchall():
        if lt == prev_raw.get(team):
            continue
        prev_raw[team] = lt
        secs = _safe_parse_time(lt)
        if secs == float('inf') or secs <= 0 or secs > LAP_MAX_SECONDS:
            continue
        per_team.setdefault(team, []).append((ts, secs, int(pit) if pit is not None else 0))
        all_clean.append((ts, secs))

    # 3. Rolling field reference (cancels track conditions). Median of clean laps
    #    in the last FLEET_FIELD_WINDOW_SECONDS; fall back to session-wide median.
    def _parse_iso(ts):
        try:
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None

    field_ref = None
    if all_clean:
        valid = [(p, s) for p, s in ((_parse_iso(ts), secs) for ts, secs in all_clean) if p is not None]
        if valid:
            latest = max(p for p, _ in valid)
            cutoff = latest - timedelta(seconds=FLEET_FIELD_WINDOW_SECONDS)
            window_vals = sorted(s for p, s in valid if p >= cutoff)
            if len(window_vals) >= 3:
                field_ref = _quantile(window_vals, 0.5)
        if field_ref is None:
            field_ref = _quantile(sorted(s for _, s in all_clean), 0.5)

    # 4. Segment stints per team and attribute each stint's residual to the
    #    physical kart that was assigned for that stint index.
    amap = _fleet_assignment_map(cur, session_id, user_id)
    kart_samples = {}  # fleet_kart_id -> {residuals, weights, laps}
    for team, laps in per_team.items():
        stints = _segment_stints(laps)
        team_amap = amap.get(team, {})
        for idx, st in enumerate(stints):
            kid = team_amap.get(idx)
            if kid is None or kid not in registry or field_ref is None:
                continue
            residual = st['mean'] - field_ref
            entry = kart_samples.setdefault(kid, {'residuals': [], 'weights': [], 'laps': 0})
            entry['residuals'].append(residual)
            entry['weights'].append(st['lap_count'])
            entry['laps'] += st['lap_count']

    # 5. Per-kart aggregates: lap-weighted mean residual + simple SE.
    kart_stats = {}
    for kid, e in kart_samples.items():
        total_w = sum(e['weights'])
        if total_w <= 0:
            continue
        mean_residual = sum(r * w for r, w in zip(e['residuals'], e['weights'])) / total_w
        sd = _stddev(e['residuals'])
        n_stints = len(e['residuals'])
        uncertainty = (sd / math.sqrt(n_stints)) if n_stints >= 1 and sd > 0 else None
        kart_stats[kid] = {
            'mean_residual': mean_residual,
            'laps': e['laps'],
            'n_stints': n_stints,
            'uncertainty': uncertainty,
        }

    # 6. Fleet-median residual + robust MAD band for fast/slow classification.
    qualified = [s['mean_residual'] for s in kart_stats.values() if s['laps'] >= FLEET_MIN_SAMPLE_LAPS]
    fleet_median_residual = _quantile(sorted(qualified), 0.5) if qualified else None
    band = FLEET_MIN_BAND_SECONDS
    if qualified and fleet_median_residual is not None:
        mad = _quantile(sorted(abs(r - fleet_median_residual) for r in qualified), 0.5)
        band = max(FLEET_MIN_BAND_SECONDS, mad or 0.0)

    def _classify(stat):
        if stat['laps'] < FLEET_MIN_SAMPLE_LAPS or fleet_median_residual is None:
            return 'insufficient', None
        delta = stat['mean_residual'] - fleet_median_residual
        if delta < -band:
            return 'fast', delta
        if delta > band:
            return 'slow', delta
        return 'neutral', delta

    # 7. Current holder of each kart = assignment at the team's highest stint idx.
    current_holder = {}  # team -> fleet_kart_id
    for team, sm in amap.items():
        if sm:
            current_holder[team] = sm[max(sm.keys())]
    kart_holder = {kid: team for team, kid in current_holder.items()}

    # 8. Live location/holder layer from the current standings feed.
    live = {}
    if standings_df is not None and not standings_df.empty:
        for rec in standings_df.to_dict('records'):
            tname = rec.get('Team', '')
            if not tname:
                continue

            def _as_int(v):
                try:
                    return int(v) if str(v).strip() else None
                except (ValueError, TypeError):
                    return None
            live[tname] = {
                'status': (rec.get('Status') or '').strip(),
                'kart_number': _as_int(rec.get('Kart')),
                'position': _as_int(rec.get('Position')),
            }

    # 9. Build one row per active registry kart.
    karts = []
    for kid, label in registry.items():
        holder_team = kart_holder.get(kid)
        live_info = live.get(holder_team) if holder_team else None
        if holder_team and live_info:
            location = 'in-pits' if live_info['status'] == 'Pit-in' else (
                'on-track' if live_info['status'] else 'unknown')
        elif holder_team:
            location = 'unknown'
        else:
            location = 'available'

        stat = kart_stats.get(kid)
        if stat:
            cls, delta = _classify(stat)
            mean_residual = round(stat['mean_residual'], 3)
            uncertainty = round(stat['uncertainty'], 3) if stat['uncertainty'] is not None else None
            sample_laps, n_stints = stat['laps'], stat['n_stints']
        else:
            cls, delta = 'insufficient', None
            mean_residual = uncertainty = None
            sample_laps = n_stints = 0

        alerts = []
        if location == 'in-pits' and cls == 'fast':
            alerts.append('fast_kart_in_pits')
        elif location == 'in-pits' and cls == 'slow':
            alerts.append('slow_kart_in_pits')

        # Kanban column derived from location (on track / in pit are timing-
        # driven for held karts; unheld karts sit Available in a lane).
        if location == 'available':
            column = 'available'
        elif location == 'in-pits':
            column = 'in_pit'
        else:  # on-track or unknown
            column = 'on_track'

        karts.append({
            'fleet_kart_id': kid,
            'label': label,
            'holder_team': holder_team,
            'holder_kart_number': live_info['kart_number'] if live_info else None,
            'holder_position': live_info['position'] if live_info else None,
            'location': location,
            'column': column,
            'lane': kart_lane.get(kid) if column == 'available' else None,
            'stint_index': max(amap[holder_team].keys()) if holder_team and amap.get(holder_team) else None,
            'mean_residual': mean_residual,
            'pace_delta_vs_fleet': round(delta, 3) if delta is not None else None,
            'uncertainty': uncertainty,
            'sample_laps': sample_laps,
            'n_stints': n_stints,
            'classification': cls,
            'rank': None,
            'alerts': alerts,
        })

    # 10. Rank karts with a pace estimate (fastest = lowest residual first).
    for i, k in enumerate(sorted((k for k in karts if k['mean_residual'] is not None),
                                 key=lambda k: k['mean_residual'])):
        k['rank'] = i + 1

    return {
        'field_ref_seconds': round(field_ref, 3) if field_ref is not None else None,
        'fleet_median_residual': round(fleet_median_residual, 3) if fleet_median_residual is not None else None,
        'karts': karts,
        'unassigned_teams': sorted(t for t in per_team if t not in current_holder),
    }


def compute_fleet_payload(track_id, session_id, user_id, standings_df=None, timestamp=None):
    """Build a user's fleet board payload for a track/session and cache it.

    Returns None for an unknown track or a falsy session_id. Cached per
    (track_id, user_id) so rapid refetches during a race are cheap.
    """
    if not session_id:
        return None
    try:
        conn = get_track_db_connection(track_id)
    except UnknownTrackError:
        return None
    try:
        body = _compute_live_fleet_pace(conn, session_id, user_id, standings_df=standings_df)
    finally:
        conn.close()
    payload = {
        'track_id': track_id,
        'session_id': session_id,
        'timestamp': timestamp or datetime.now().isoformat(),
        **body,
    }
    _fleet_cache[(track_id, user_id)] = {
        'session_id': session_id,
        'computed_at': time.time(),
        'payload': payload,
    }
    return payload


# ---- Fleet Tracker REST endpoints (all per-user, login required) ----------






def start_multi_track_monitoring():
    """Start monitoring all configured tracks automatically"""
    global multi_track_manager, multi_track_loop, multi_track_thread

    def run_multi_track_loop():
        """Run the async event loop for multi-track monitoring"""
        global multi_track_loop, multi_track_manager

        multi_track_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(multi_track_loop)

        multi_track_manager = MultiTrackManager(socketio=socketio)

        try:
            print("Starting multi-track monitoring...")
            multi_track_loop.run_until_complete(multi_track_manager.start_all_parsers())
        except Exception as e:
            print(f"Error in multi-track monitoring: {e}")
            traceback.print_exc()
        finally:
            multi_track_loop.close()

    # Start in a separate thread
    multi_track_thread = threading.Thread(target=run_multi_track_loop, daemon=True)
    multi_track_thread.start()
    print("Multi-track monitoring thread started")

def get_database_path(track_id: int) -> str:
    """Get the database file path for a specific track"""
    return f'race_data_track_{track_id}.db'

class UnknownTrackError(Exception):
    """Raised when an API caller supplies a track_id that is not in tracks.db."""


def get_track_db_connection(track_id, timeout: float = 5.0):
    """
    Get database connection for a specific track with timeout.

    Validates that track_id is a positive int AND that it corresponds to a real
    row in tracks.db. This prevents sqlite3.connect() from creating stray
    race_data_track_N.db files on disk for attacker-supplied ids.
    """
    try:
        track_id = int(track_id)
    except (TypeError, ValueError):
        raise UnknownTrackError(f'Invalid track_id: {track_id!r}')
    if track_id <= 0 or not track_db.get_track_by_id(track_id):
        raise UnknownTrackError(f'Unknown track_id: {track_id}')

    db_path = get_database_path(track_id)
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@app.errorhandler(UnknownTrackError)
def _handle_unknown_track(exc):
    return jsonify({'error': str(exc)}), 404


# --- Blueprint registration -------------------------------------------------
# Imports live at the bottom so the blueprints can `from race_ui import ...`
# the helpers/state defined above without circular-import grief.
#
# When start-selenium.sh launches us via `python race_ui.py`, this module is
# loaded as `__main__`, not `race_ui`. Blueprints `import race_ui` to reach
# helpers via dotted access (test-monkeypatch friendly); without this alias
# that import re-executes race_ui.py from disk → circular import. Aliasing
# `race_ui` to the running module makes the import a no-op lookup.
import sys as _sys  # noqa: E402
_sys.modules.setdefault('race_ui', _sys.modules[__name__])

from race_app.blueprints.admin_users_routes import admin_users_bp  # noqa: E402
from race_app.blueprints.aliases_routes import aliases_bp  # noqa: E402
from race_app.blueprints.auth_routes import auth_bp  # noqa: E402
from race_app.blueprints.driver_consistency_routes import driver_consistency_bp  # noqa: E402
from race_app.blueprints.driver_fairness_routes import driver_fairness_bp  # noqa: E402
from race_app.blueprints.fleet_routes import fleet_bp  # noqa: E402
from race_app.blueprints.kart_fairness_routes import kart_fairness_bp  # noqa: E402
from race_app.blueprints.me_routes import me_bp  # noqa: E402
from race_app.blueprints.pit_alert_routes import pit_alert_bp  # noqa: E402
from race_app.blueprints.session_configs_routes import session_configs_bp  # noqa: E402
from race_app.blueprints.socket_admin_routes import socket_admin_bp  # noqa: E402
from race_app.blueprints.team_data_routes import team_data_bp  # noqa: E402

app.register_blueprint(admin_users_bp)
app.register_blueprint(aliases_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(driver_consistency_bp)
app.register_blueprint(driver_fairness_bp)
app.register_blueprint(fleet_bp)
app.register_blueprint(kart_fairness_bp)
app.register_blueprint(me_bp)
app.register_blueprint(pit_alert_bp)
app.register_blueprint(session_configs_bp)
app.register_blueprint(socket_admin_bp)
app.register_blueprint(team_data_bp)


if __name__ == '__main__':
    try:
        # Auto-start multi-track monitoring
        print("Starting Flask-SocketIO server on port 5000...")
        print("Auto-starting data collection for all configured tracks...")
        start_multi_track_monitoring()

        # For development/pm2, allow unsafe werkzeug (in production, use gunicorn with eventlet)
        socketio.run(app, host='127.0.0.1', port=5000, debug=False, allow_unsafe_werkzeug=True)
    except Exception as e:
        print(f"Error starting server: {e}")
        print(traceback.format_exc())
    finally:
        # Ensure the update thread is stopped when the application exits
        if update_thread and update_thread.is_alive():
            stop_event.set()
            update_thread.join(timeout=5)

        # Clean up the parser
        if parser:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(parser.cleanup())
            loop.close()

        # Clean up multi-track manager
        if multi_track_manager and multi_track_loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    multi_track_manager.stop_all_parsers(),
                    multi_track_loop
                )
                if multi_track_thread and multi_track_thread.is_alive():
                    multi_track_thread.join(timeout=5)
            except Exception as e:
                print(f"Error stopping multi-track manager: {e}")



