import asyncio
import json
import threading
import time
import traceback
from datetime import datetime, timedelta
from collections import deque
import random
import math
import hashlib
import secrets
import sqlite3
from functools import wraps

from flask import Flask, jsonify, request, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room

from apex_timing_websocket import ApexTimingWebSocketParser
from database_manager import TrackDatabase
from multi_track_manager import MultiTrackManager

# Initialize Flask app
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # For session management
CORS(app, 
     origins=["http://localhost:3000", "https://krranalyser.fr", "http://krranalyser.fr", "https://tpresearch.fr", "http://tpresearch.fr", "https://www.tpresearch.fr", "http://www.tpresearch.fr"],
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# Initialize SocketIO with CORS support and proxy handling
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',
    logger=False,
    engineio_logger=False,
    ping_interval=25,  # Send ping every 25 seconds
    ping_timeout=60    # Wait 60 seconds for pong response
)

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
last_race_data_hash = None

# WebSocket connection handlers
@socketio.on('connect')
def handle_connect(auth=None):
    """Handle client connection"""
    print(f"Client connected: {request.sid}")
    connected_clients.add(request.sid)
    join_room('race_updates')
    
    # Convert gap_history deques to lists for JSON serialization
    serializable_gap_history = {}
    for kart, history in race_data['gap_history'].items():
        serializable_gap_history[kart] = {
            'gaps': list(history['gaps']) if isinstance(history['gaps'], deque) else history['gaps'],
            'last_update': history.get('last_update')
        }
        if 'adjusted_gaps' in history:
            serializable_gap_history[kart]['adjusted_gaps'] = list(history['adjusted_gaps']) if isinstance(history['adjusted_gaps'], deque) else history['adjusted_gaps']
    
    # Send current race data on connect
    emit('race_data_update', {
        'teams': race_data['teams'],
        'session_info': race_data['session_info'],
        'last_update': race_data['last_update'],
        'delta_times': race_data['delta_times'],
        'gap_history': serializable_gap_history,
        'simulation_mode': race_data['simulation_mode'],
        'timing_url': race_data['timing_url'],
        'is_running': race_data['is_running'],
        'my_team': race_data['my_team'],
        'monitored_teams': race_data['monitored_teams'],
        'pit_config': race_data['pit_config']
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f"Client disconnected: {request.sid}")
    connected_clients.discard(request.sid)
    leave_room('race_updates')
    leave_room('standings_stream')

@socketio.on('join_track')
def handle_join_track(data):
    """Handle client joining a track-specific room"""
    track_id = data.get('track_id')
    if track_id:
        room = f'track_{track_id}'
        join_room(room)
        print(f"Client {request.sid} joined {room}")
        emit('track_joined', {'track_id': track_id})

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
        track_info = track_db.get_track(track_id)
        if not track_info:
            emit('team_room_error', {
                'error': f'Track {track_id} not found',
                'timestamp': datetime.now().isoformat()
            })
            return

        # Validate team exists on this track by checking current standings
        db_path = f'race_data_track_{track_id}.db'
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            # Check if team exists in lap_times table (most recent data)
            cursor.execute('''
                SELECT DISTINCT team_name
                FROM lap_times
                WHERE team_name = ?
                ORDER BY timestamp DESC
                LIMIT 1
            ''', (team_name,))
            result = cursor.fetchone()

            if not result:
                emit('team_room_error', {
                    'error': f'Team "{team_name}" not found on track {track_id}',
                    'track_id': track_id,
                    'track_name': track_info['track_name'],
                    'timestamp': datetime.now().isoformat()
                })
                return

        # Join the team-specific room
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
        print(f"Error handling join_team_room: {e}")
        emit('team_room_error', {
            'error': f'Failed to join team room: {str(e)}',
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
    if len(connected_clients) == 0:
        return
    
    # Only emit if we have actual data to send
    if not race_data.get('teams') and update_type != 'custom':
        return
    
    # Emit standings update to subscribers
    if update_type in ['full', 'teams'] and race_data.get('teams'):
        emit_standings_update()
        
    if update_type == 'full':
        # Convert gap_history deques to lists for JSON serialization
        serializable_gap_history = {}
        for kart, history in race_data['gap_history'].items():
            serializable_gap_history[kart] = {
                'gaps': list(history['gaps']) if isinstance(history['gaps'], deque) else history['gaps'],
                'last_update': history.get('last_update')
            }
            if 'adjusted_gaps' in history:
                serializable_gap_history[kart]['adjusted_gaps'] = list(history['adjusted_gaps']) if isinstance(history['adjusted_gaps'], deque) else history['adjusted_gaps']
        
        socketio.emit('race_data_update', {
            'teams': race_data['teams'],
            'session_info': race_data['session_info'],
            'last_update': race_data['last_update'],
            'delta_times': race_data['delta_times'],
            'gap_history': serializable_gap_history,
            'simulation_mode': race_data['simulation_mode'],
            'timing_url': race_data['timing_url'],
            'is_running': race_data['is_running'],
            'my_team': race_data['my_team'],
            'monitored_teams': race_data['monitored_teams'],
            'pit_config': race_data['pit_config']
        }, room='race_updates')
    elif update_type == 'teams' and race_data.get('teams'):
        socketio.emit('teams_update', {
            'teams': race_data['teams'],
            'last_update': race_data['last_update']
        }, room='race_updates')
    elif update_type == 'gaps' and race_data.get('delta_times'):
        # Convert gap_history deques to lists for JSON serialization
        serializable_gap_history = {}
        for kart, history in race_data['gap_history'].items():
            serializable_gap_history[kart] = {
                'gaps': list(history['gaps']) if isinstance(history['gaps'], deque) else history['gaps'],
                'last_update': history.get('last_update')
            }
            if 'adjusted_gaps' in history:
                serializable_gap_history[kart]['adjusted_gaps'] = list(history['adjusted_gaps']) if isinstance(history['adjusted_gaps'], deque) else history['adjusted_gaps']
        
        socketio.emit('gap_update', {
            'delta_times': race_data['delta_times'],
            'gap_history': serializable_gap_history
        }, room='race_updates')
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
        """Format seconds to MM:SS.sss"""
        minutes = int(seconds // 60)
        seconds_remainder = seconds % 60
        return f"{minutes}:{seconds_remainder:06.3f}".replace(".", ":")
        
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
        conn = sqlite3.connect('race_data.db')
        cursor = conn.cursor()
        
        # Build query based on parameters
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
        
        # Get last 50 valid lap times
        query += " ORDER BY id DESC LIMIT 50"
        
        cursor.execute(query, params)
        lap_times = cursor.fetchall()
        
        if not lap_times:
            conn.close()
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
            except:
                continue
        
        conn.close()
        
        if valid_count > 0:
            avg_lap_time = total_seconds / valid_count
            return round(avg_lap_time, 1)
        else:
            return default
            
    except Exception as e:
        print(f"Error calculating average lap time: {e}")
        return default

# Store previous delta values for change detection
previous_deltas = {}

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

    standings = []
    for i, team in enumerate(sorted_teams):
        position = int(team.get('Position', '0') or '0')
        kart_num = team.get('Kart', '')
        
        # Get current team's gap/best lap
        if is_qualification:
            # In qualification, use best lap times
            best_lap = team.get('Best Lap', '')
            if best_lap:
                try:
                    # Parse time to seconds
                    if ':' in best_lap:
                        parts = best_lap.split(':')
                        minutes = int(parts[0])
                        seconds = float(parts[1].replace(',', '.'))
                        current_gap = minutes * 60 + seconds
                    else:
                        current_gap = float(best_lap.replace(',', '.'))
                except:
                    current_gap = float('inf')  # No valid lap
            else:
                current_gap = float('inf')  # No lap set
        else:
            # Normal race mode - use gap
            if position == 1:
                current_gap = 0.0
            else:
                gap_str = team.get('Gap', '0')
                if 'Tour' in gap_str:
                    # Lapped - use average lap time
                    laps_behind = int(gap_str.split()[0])
                    current_gap = laps_behind * get_average_lap_time()
                else:
                    try:
                        # Parse time to seconds
                        if ':' in gap_str:
                            parts = gap_str.split(':')
                            minutes = int(parts[0])
                            seconds = float(parts[1].replace(',', '.'))
                            current_gap = minutes * 60 + seconds
                        else:
                            current_gap = float(gap_str.replace(',', '.'))
                    except:
                        current_gap = 0.0
        
        # Calculate delta to P-1 (team ahead)
        delta_p_minus_1 = None
        if i > 0:  # Not the leader
            prev_team = sorted_teams[i-1]
            if is_qualification:
                # In qualification, use best lap times
                prev_best_lap = prev_team.get('Best Lap', '')
                if prev_best_lap:
                    try:
                        if ':' in prev_best_lap:
                            parts = prev_best_lap.split(':')
                            minutes = int(parts[0])
                            seconds = float(parts[1].replace(',', '.'))
                            prev_gap = minutes * 60 + seconds
                        else:
                            prev_gap = float(prev_best_lap.replace(',', '.'))
                    except:
                        prev_gap = float('inf')
                else:
                    prev_gap = float('inf')
            else:
                # Normal race mode - use gap
                prev_gap = 0.0
                prev_position = prev_team.get('Position', '0') or '0'
                if int(prev_position) > 1:
                    prev_gap_str = prev_team.get('Gap', '0')
                    if 'Tour' in prev_gap_str:
                        prev_laps = int(prev_gap_str.split()[0])
                        prev_gap = prev_laps * get_average_lap_time()
                    else:
                        try:
                            if ':' in prev_gap_str:
                                parts = prev_gap_str.split(':')
                                minutes = int(parts[0])
                                seconds = float(parts[1].replace(',', '.'))
                                prev_gap = minutes * 60 + seconds
                            else:
                                prev_gap = float(prev_gap_str.replace(',', '.'))
                        except:
                            prev_gap = 0.0
            
            if current_gap != float('inf') and prev_gap != float('inf'):
                delta_p_minus_1 = round(current_gap - prev_gap, 3)
            else:
                delta_p_minus_1 = None
        
        # Calculate delta to P+1 (team behind)
        delta_p_plus_1 = None
        if i < len(sorted_teams) - 1:  # Not the last place
            next_team = sorted_teams[i+1]
            if is_qualification:
                # In qualification, use best lap times
                next_best_lap = next_team.get('Best Lap', '')
                if next_best_lap:
                    try:
                        if ':' in next_best_lap:
                            parts = next_best_lap.split(':')
                            minutes = int(parts[0])
                            seconds = float(parts[1].replace(',', '.'))
                            next_gap = minutes * 60 + seconds
                        else:
                            next_gap = float(next_best_lap.replace(',', '.'))
                    except:
                        next_gap = float('inf')
                else:
                    next_gap = float('inf')
            else:
                # Normal race mode - use gap
                next_gap_str = next_team.get('Gap', '0')
                next_gap = 0.0
                if 'Tour' in next_gap_str:
                    next_laps = int(next_gap_str.split()[0])
                    next_gap = next_laps * get_average_lap_time()
                else:
                    try:
                        if ':' in next_gap_str:
                            parts = next_gap_str.split(':')
                            minutes = int(parts[0])
                            seconds = float(parts[1].replace(',', '.'))
                            next_gap = minutes * 60 + seconds
                        else:
                            next_gap = float(next_gap_str.replace(',', '.'))
                    except:
                        next_gap = 0.0
            
            if current_gap != float('inf') and next_gap != float('inf'):
                delta_p_plus_1 = round(next_gap - current_gap, 3)
            else:
                delta_p_plus_1 = None
        
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
        
        # Helper function to parse time string to seconds
        def parse_time_to_seconds(time_str):
            """Convert time string (MM:SS.sss or SS.sss) to seconds"""
            if ':' in time_str:
                parts = time_str.split(':')
                if len(parts) == 2:
                    # MM:SS.sss format
                    minutes = int(parts[0])
                    seconds = float(parts[1].replace(',', '.'))
                    return minutes * 60 + seconds
            # Just seconds
            return float(time_str.replace(',', '.'))
        
        # In qualification/practice, use best lap times instead of gaps
        if is_qualification:
            # Get my team's best lap time
            my_best_lap = my_team.get('Best Lap', '')
            if my_best_lap:
                try:
                    my_base_gap = parse_time_to_seconds(my_best_lap)
                except:
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
                    except:
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
                    
                    # Helper function to parse time string to seconds
                    def parse_time_to_seconds(time_str):
                        """Convert time string (MM:SS.sss or SS.sss) to seconds"""
                        if ':' in time_str:
                            parts = time_str.split(':')
                            if len(parts) == 2:
                                # MM:SS.sss format
                                minutes = int(parts[0])
                                seconds = float(parts[1].replace(',', '.'))
                                return minutes * 60 + seconds
                        # Just seconds
                        return float(time_str.replace(',', '.'))
                    
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
                            except:
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
                                        # Calculate gap based on lap difference
                                        # Get average lap time from recent data for better accuracy
                                        avg_lap_time = get_average_lap_time()
                                        
                                        # Also consider the specific teams' recent lap times if available
                                        team_karts = [int(my_team.get('Kart', '0') or '0'), int(monitored_team.get('Kart', '0') or '0')]
                                        team_avg = get_average_lap_time(kart_numbers=team_karts)
                                        if team_avg != 90.0:  # If we got valid team-specific data
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
                                        # Get average lap time from recent data
                                        avg_lap_time = get_average_lap_time()
                                        
                                        # Also consider the specific teams' recent lap times if available
                                        team_karts = [int(my_team.get('Kart', '0') or '0'), int(monitored_team.get('Kart', '0') or '0')]
                                        team_avg = get_average_lap_time(kart_numbers=team_karts)
                                        if team_avg != 90.0:  # If we got valid team-specific data
                                            avg_lap_time = team_avg
                                        
                                        if my_position < mon_position:
                                            # Monitored team is behind us with lapped teams in between
                                            mon_base_gap += laps_between * avg_lap_time
                                        else:
                                            # Monitored team is ahead of us with lapped teams in between
                                            mon_base_gap -= laps_between * avg_lap_time
                                    # If no lapped teams between us, we're on same lap - use gap as is
                                except:
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
    conn = sqlite3.connect('race_data.db')
    conn.row_factory = sqlite3.Row
    return conn

def create_session(user_id):
    """Create a new session for user"""
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=24)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sessions (session_token, user_id, expires_at)
        VALUES (?, ?, ?)
    ''', (session_id, user_id, expires_at.isoformat()))
    conn.commit()
    conn.close()

    return session_id

def verify_session(session_id):
    """Verify if session is valid and return user info"""
    if not session_id:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.id, u.username, u.role, u.email
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.session_token = ? AND s.expires_at > ?
    ''', (session_id, datetime.now().isoformat()))

    user = cursor.fetchone()
    conn.close()

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
@app.route('/api/auth/login', methods=['POST'])
def login():
    """User login endpoint"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        # Hash the password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Log login attempt
            cursor.execute('''
                INSERT INTO login_attempts (username, ip_address, success)
                VALUES (?, ?, ?)
            ''', (username, request.remote_addr, False))
            
            # Check credentials
            cursor.execute('''
                SELECT id, username, role, email, is_active
                FROM users
                WHERE username = ? AND password_hash = ?
            ''', (username, password_hash))
            
            user = cursor.fetchone()
            
            if user and user['is_active']:
                # Update last login
                cursor.execute('''
                    UPDATE users SET last_login = ? WHERE id = ?
                ''', (datetime.now().isoformat(), user['id']))
                
                # Update login attempt as successful
                cursor.execute('''
                    UPDATE login_attempts 
                    SET success = 1 
                    WHERE id = (SELECT MAX(id) FROM login_attempts WHERE username = ?)
                ''', (username,))
                
                conn.commit()
                
                # Create session
                session_id = create_session(user['id'])
                session['session_id'] = session_id
                
                conn.close()
                
                return jsonify({
                    'success': True,
                    'user': {
                        'id': user['id'],
                        'username': user['username'],
                        'role': user['role'],
                        'email': user['email']
                    }
                })
            
            conn.commit()
            conn.close()
            
            return jsonify({'error': 'Invalid credentials'}), 401
            
        except sqlite3.Error as e:
            conn.rollback()
            conn.close()
            print(f"Database error in login: {e}")
            return jsonify({'error': 'Database error occurred'}), 500
            
    except Exception as e:
        print(f"Login error: {e}")
        print(traceback.format_exc())
        return jsonify({'error': 'An error occurred during login'}), 500

@app.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """User logout endpoint"""
    session_id = session.get('session_id')
    if session_id:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
        conn.commit()
        conn.close()
        session.clear()
    
    return jsonify({'success': True})

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    """Check if user is authenticated"""
    session_id = session.get('session_id')
    user = verify_session(session_id)
    
    if user:
        return jsonify({
            'authenticated': True,
            'user': user
        })
    
    return jsonify({'authenticated': False})

# User management routes (admin only)
@app.route('/api/admin/users', methods=['GET'])
@admin_required
def get_users():
    """Get all users (admin only)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, username, email, role, created_at, last_login, is_active
        FROM users
        ORDER BY created_at DESC
    ''')
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify(users)

@app.route('/api/admin/users', methods=['POST'])
@admin_required
def create_user():
    """Create new user (admin only)"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    role = data.get('role', 'user')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO users (username, password_hash, email, role)
            VALUES (?, ?, ?, ?)
        ''', (username, password_hash, email, role))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        
        return jsonify({
            'success': True,
            'user': {
                'id': user_id,
                'username': username,
                'email': email,
                'role': role
            }
        })
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Username already exists'}), 400

@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """Update user (admin only)"""
    data = request.get_json()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build update query dynamically
    updates = []
    params = []
    
    if 'email' in data:
        updates.append('email = ?')
        params.append(data['email'])
    
    if 'role' in data:
        updates.append('role = ?')
        params.append(data['role'])
    
    if 'is_active' in data:
        updates.append('is_active = ?')
        params.append(data['is_active'])
    
    if 'password' in data:
        updates.append('password_hash = ?')
        params.append(hashlib.sha256(data['password'].encode()).hexdigest())
    
    if not updates:
        return jsonify({'error': 'No fields to update'}), 400
    
    params.append(user_id)
    query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    
    cursor.execute(query, params)
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete user (admin only)"""
    # Prevent deleting admin user
    if user_id == 1:
        return jsonify({'error': 'Cannot delete admin user'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

# REST API routes
@app.route('/api/race-data')
def get_race_data():
    """Return the current race data as JSON"""
    return jsonify(get_serializable_race_data())

@app.route('/api/update-monitoring', methods=['POST'])
def update_monitoring():
    """Update the monitored teams"""
    global race_data
    
    data = request.json
    print("Received monitoring update:", data)
    
    race_data['my_team'] = data.get('myTeam')
    race_data['monitored_teams'] = data.get('monitoredTeams', [])
    
    print(f"Updated monitoring: my_team={race_data['my_team']}, monitored_teams={race_data['monitored_teams']}")
    
    # Emit monitoring update via WebSocket
    emit_race_update('custom', {
        'event': 'monitoring_update',
        'payload': {
            'my_team': race_data['my_team'],
            'monitored_teams': race_data['monitored_teams']
        }
    })
    
    # If we have teams data, recalculate and emit delta times
    if race_data.get('teams') and race_data['my_team'] and race_data['monitored_teams']:
        calculate_delta_times(race_data['teams'], race_data['my_team'], race_data['monitored_teams'])
        # Emit gap updates
        emit_race_update('gaps')
    
    return jsonify({'status': 'success'})

@app.route('/api/start-simulation', methods=['POST'])
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
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/stop-simulation', methods=['POST'])
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

@app.route('/api/update-pit-config', methods=['POST'])
def update_pit_config():
    """Update pit stop configuration"""
    global race_data, PIT_STOP_TIME, REQUIRED_PIT_STOPS, DEFAULT_LAP_TIME
    
    data = request.json
    print("Received pit config update:", data)
    
    if data:
        # Update global variables
        if 'pitStopTime' in data:
            PIT_STOP_TIME = data['pitStopTime']
            race_data['pit_config']['pit_time'] = PIT_STOP_TIME
            
        if 'requiredPitStops' in data:
            REQUIRED_PIT_STOPS = data['requiredPitStops']
            race_data['pit_config']['required_stops'] = REQUIRED_PIT_STOPS
            
        if 'defaultLapTime' in data:
            DEFAULT_LAP_TIME = data['defaultLapTime']
            race_data['pit_config']['default_lap_time'] = DEFAULT_LAP_TIME
            
        print(f"Updated pit config: time={PIT_STOP_TIME}s, required stops={REQUIRED_PIT_STOPS}, default lap={DEFAULT_LAP_TIME}s")
        
        # Emit pit config update via WebSocket
        emit_race_update('custom', {
            'event': 'pit_config_update',
            'payload': race_data['pit_config']
        })
        
        return jsonify({'status': 'success', 'message': 'Pit stop configuration updated'})
    
    return jsonify({'status': 'error', 'message': 'Invalid configuration data'})

@app.route('/api/set-parser-mode', methods=['POST'])
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
        is_active=data.get('is_active', True)
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
        is_active=data.get('is_active')
    )

    if 'error' in result:
        return jsonify({'error': result['error']}), 400

    return jsonify({'success': True})

@app.route('/api/admin/tracks/<int:track_id>', methods=['DELETE'])
@admin_required
def admin_delete_track(track_id):
    """Delete a track (admin only)"""
    result = track_db.delete_track(track_id)

    if 'error' in result:
        return jsonify({'error': result['error']}), 404

    return jsonify({'success': True})

# Test endpoints for simulating track sessions
@app.route('/api/test/simulate-session/<int:track_id>', methods=['POST'])
def simulate_track_session(track_id):
    """Simulate an active session on a track for testing purposes"""
    global multi_track_manager

    if not multi_track_manager:
        return jsonify({'error': 'Multi-track manager not initialized'}), 500

    # Check if track exists
    if track_id not in multi_track_manager.parsers:
        return jsonify({'error': f'Track {track_id} not found'}), 404

    parser = multi_track_manager.parsers[track_id]

    # Simulate active session by updating last_data_time
    from datetime import datetime
    parser.last_data_time = datetime.now()
    parser.session_active_status = True

    # Broadcast session status update for this specific track
    room = f'track_{track_id}'
    socketio.emit('session_status', {
        'track_id': track_id,
        'track_name': parser.track_name,
        'active': True,
        'message': 'Simulated session active',
        'timestamp': datetime.now().isoformat()
    }, room=room)

    # Broadcast all tracks status update
    multi_track_manager.broadcast_all_tracks_status()

    return jsonify({
        'success': True,
        'message': f'Simulated active session for track {track_id} ({parser.track_name})',
        'track_id': track_id,
        'track_name': parser.track_name
    })

@app.route('/api/test/stop-session/<int:track_id>', methods=['POST'])
def stop_simulated_session(track_id):
    """Stop simulated session on a track"""
    global multi_track_manager

    if not multi_track_manager:
        return jsonify({'error': 'Multi-track manager not initialized'}), 500

    # Check if track exists
    if track_id not in multi_track_manager.parsers:
        return jsonify({'error': f'Track {track_id} not found'}), 404

    parser = multi_track_manager.parsers[track_id]

    # Mark session as inactive
    parser.last_data_time = None
    parser.session_active_status = False

    # Broadcast session status update for this specific track
    from datetime import datetime
    room = f'track_{track_id}'
    socketio.emit('session_status', {
        'track_id': track_id,
        'track_name': parser.track_name,
        'active': False,
        'message': 'Simulated session stopped',
        'timestamp': datetime.now().isoformat()
    }, room=room)

    # Broadcast all tracks status update
    multi_track_manager.broadcast_all_tracks_status()

    return jsonify({
        'success': True,
        'message': f'Stopped simulated session for track {track_id} ({parser.track_name})',
        'track_id': track_id,
        'track_name': parser.track_name
    })

# Keep original track routes for backwards compatibility
@app.route('/api/tracks', methods=['POST'])
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
def delete_track(track_id):
    """Delete a track from the database"""
    result = track_db.delete_track(track_id)
    
    if 'error' in result:
        return jsonify(result), 404
    return jsonify(result)

@app.route('/api/reset-race-data', methods=['POST'])
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
@app.route('/api/team-data/common-sessions', methods=['POST'])
def get_common_sessions():
    """Get sessions where all specified teams participated"""
    try:
        data = request.json
        team_names = data.get('teams', [])
        track_id = data.get('track_id', 1)  # Default to track 1

        if not team_names or len(team_names) < 1:
            return jsonify({'sessions': []})

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Get sessions where all teams participated
        placeholders = ','.join(['?' for _ in team_names])
        team_names_lower = [name.strip().lower() for name in team_names]

        query = f"""
            WITH team_sessions AS (
                SELECT DISTINCT
                    lt.session_id,
                    CASE
                        WHEN lt.team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                        ELSE LOWER(TRIM(lt.team_name))
                    END as team_name
                FROM lap_times lt
                WHERE (
                    CASE
                        WHEN lt.team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                        ELSE LOWER(TRIM(lt.team_name))
                    END
                ) IN ({placeholders})
            )
            SELECT
                rs.session_id,
                rs.start_time,
                rs.name,
                rs.track,
                COUNT(DISTINCT ts.team_name) as teams_present
            FROM race_sessions rs
            JOIN team_sessions ts ON rs.session_id = ts.session_id
            GROUP BY rs.session_id
            HAVING COUNT(DISTINCT ts.team_name) = ?
            ORDER BY rs.start_time DESC
        """

        cursor.execute(query, team_names_lower + [len(team_names)])
        sessions = [{
            'session_id': row[0],
            'start_time': row[1],
            'name': row[2],
            'track': row[3],
            'teams_present': row[4]
        } for row in cursor.fetchall()]

        conn.close()

        return jsonify({'sessions': sessions})
    except Exception as e:
        print(f"Error getting common sessions: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/sessions', methods=['GET'])
def get_all_sessions():
    """Get all sessions for a track"""
    try:
        track_id = request.args.get('track_id', 1, type=int)  # Default to track 1

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Get all sessions for the track, ordered by most recent first
        query = """
            SELECT
                rs.session_id,
                rs.start_time,
                rs.name,
                rs.track,
                COUNT(DISTINCT lt.team_name) as teams_count
            FROM race_sessions rs
            LEFT JOIN lap_times lt ON rs.session_id = lt.session_id
            GROUP BY rs.session_id
            ORDER BY rs.start_time DESC
        """

        cursor.execute(query)
        sessions = [{
            'session_id': row[0],
            'start_time': row[1],
            'name': row[2],
            'track': row[3],
            'teams_count': row[4]
        } for row in cursor.fetchall()]

        conn.close()

        return jsonify({'sessions': sessions})
    except Exception as e:
        print(f"Error getting sessions: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/search', methods=['GET'])
def search_teams():
    """Search for teams by name (case-insensitive, removes class prefix)"""
    try:
        search_query = request.args.get('q', '').strip()
        session_id = request.args.get('session_id', None)
        track_id = request.args.get('track_id', 1, type=int)  # Default to track 1

        if not search_query:
            return jsonify({'teams': []})

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Build query to search teams, handling both with and without class prefix
        query = """
            SELECT DISTINCT
                CASE
                    WHEN team_name LIKE '% - %' THEN TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3))
                    ELSE TRIM(team_name)
                END as team_name_clean,
                CASE
                    WHEN team_name LIKE '% - %' THEN GROUP_CONCAT(DISTINCT SUBSTR(team_name, 1, 1))
                    ELSE NULL
                END as classes
            FROM lap_times
            WHERE (
                CASE
                    WHEN team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                    ELSE LOWER(TRIM(team_name))
                END
            ) LIKE ?
            GROUP BY team_name_clean
            ORDER BY team_name_clean
            LIMIT 20
        """

        cursor.execute(query, (f'%{search_query.lower()}%',))
        teams = [{'name': row[0], 'classes': row[1] if row[1] else ''} for row in cursor.fetchall()]

        conn.close()

        return jsonify({'teams': teams})
    except Exception as e:
        print(f"Error searching teams: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/top-teams', methods=['GET'])
def get_top_teams():
    """Get top N teams ranked by best lap time"""
    try:
        limit = request.args.get('limit', 10, type=int)
        track_id = request.args.get('track_id', 1, type=int)  # Default to track 1
        session_id = request.args.get('session_id', None)

        # Validate limit
        if limit not in [10, 20, 30]:
            limit = 10

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Build session filter
        session_filter = ""
        query_params = []
        if session_id:
            session_filter = "AND session_id = ?"
            query_params.append(int(session_id))

        # Query to get top teams with their stats
        # Handles both formats: with class prefix "1 - TEAMNAME" and without "TEAMNAME"
        # Handles mixed best_lap formats: "MM:SS.mmm" and raw seconds
        query = f"""
            WITH team_stats AS (
                SELECT
                    CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END as team_name_clean,
                    MAX(CASE
                        WHEN team_name LIKE '% - %' THEN
                            TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3))
                        ELSE
                            TRIM(team_name)
                    END) as team_name_display,
                    MIN(
                        CASE
                            WHEN best_lap LIKE '%:%' THEN
                                CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                            WHEN best_lap IS NOT NULL AND best_lap != '' AND LENGTH(TRIM(best_lap)) > 0 THEN
                                CAST(best_lap AS REAL)
                            ELSE
                                NULL
                        END
                    ) as best_lap_seconds,
                    COUNT(DISTINCT session_id) as sessions_count,
                    GROUP_CONCAT(DISTINCT SUBSTR(team_name, 1, 1)) as classes
                FROM lap_times
                WHERE best_lap IS NOT NULL
                AND best_lap != ''
                AND team_name IS NOT NULL
                AND team_name != ''
                {session_filter}
                GROUP BY team_name_clean
            ),
            team_laps AS (
                SELECT
                    CASE
                        WHEN lt.team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(lt.team_name))
                    END as team_name_clean,
                    SUM(CASE
                        WHEN lt.position = 1 AND lt.gap LIKE 'Tour %'
                        THEN CAST(SUBSTR(lt.gap, 6) AS INTEGER)
                        WHEN lt.gap LIKE '+% Tour%'
                        THEN CAST(SUBSTR(lt.gap, 6) AS INTEGER) - CAST(SUBSTR(lt.gap, INSTR(lt.gap, '+') + 1, INSTR(lt.gap, ' ') - 2) AS INTEGER)
                        ELSE 0
                    END) as total_laps
                FROM lap_times lt
                WHERE lt.team_name IS NOT NULL
                AND lt.team_name != ''
                {session_filter}
                GROUP BY team_name_clean
            ),
            avg_laps AS (
                SELECT
                    CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END as team_name_clean,
                    AVG(
                        CASE
                            WHEN last_lap LIKE '%:%' THEN
                                CAST(SUBSTR(last_lap, 1, INSTR(last_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(last_lap, INSTR(last_lap, ':') + 1) AS REAL)
                            ELSE NULL
                        END
                    ) as avg_lap_seconds
                FROM lap_times
                WHERE last_lap IS NOT NULL
                AND last_lap != ''
                AND last_lap LIKE '%:%'
                AND team_name IS NOT NULL
                AND team_name != ''
                {session_filter}
                GROUP BY team_name_clean
            ),
            best_lap_timestamps AS (
                SELECT
                    subq.team_name_clean,
                    MIN(subq.timestamp) as best_lap_timestamp
                FROM (
                    SELECT
                        CASE
                            WHEN team_name LIKE '% - %' THEN
                                LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE
                                LOWER(TRIM(team_name))
                        END as team_name_clean,
                        timestamp,
                        CASE
                            WHEN best_lap LIKE '%:%' THEN
                                CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                            WHEN best_lap IS NOT NULL AND best_lap != '' AND LENGTH(TRIM(best_lap)) > 0 THEN
                                CAST(best_lap AS REAL)
                            ELSE
                                NULL
                        END as best_lap_seconds
                    FROM lap_times
                    WHERE best_lap IS NOT NULL
                    AND best_lap != ''
                    AND team_name IS NOT NULL
                    AND team_name != ''
                    {session_filter}
                ) subq
                INNER JOIN team_stats ts ON subq.team_name_clean = ts.team_name_clean
                    AND subq.best_lap_seconds IS NOT NULL
                    AND ts.best_lap_seconds IS NOT NULL
                    AND ABS(subq.best_lap_seconds - ts.best_lap_seconds) < 0.01
                GROUP BY subq.team_name_clean
            )
            SELECT
                ts.team_name_display,
                ts.best_lap_seconds,
                COALESCE(al.avg_lap_seconds, 0) as avg_lap_seconds,
                COALESCE(tl.total_laps, 0) as total_laps,
                ts.sessions_count,
                ts.classes,
                blt.best_lap_timestamp
            FROM team_stats ts
            LEFT JOIN team_laps tl ON ts.team_name_clean = tl.team_name_clean
            LEFT JOIN avg_laps al ON ts.team_name_clean = al.team_name_clean
            LEFT JOIN best_lap_timestamps blt ON ts.team_name_clean = blt.team_name_clean
            WHERE ts.best_lap_seconds IS NOT NULL
            ORDER BY ts.best_lap_seconds ASC
            LIMIT ?
        """

        # Add limit parameter to query_params
        query_params_with_limit = query_params * 4 + [limit]  # session_id repeated for each CTE (now 4), then limit
        cursor.execute(query, query_params_with_limit)
        teams = []
        for row in cursor.fetchall():
            best_lap_seconds = row[1]
            # Format best_lap_seconds to MM:SS.mmm
            if best_lap_seconds:
                mins = int(best_lap_seconds // 60)
                secs = best_lap_seconds % 60
                best_lap_formatted = f"{mins}:{secs:06.3f}"
            else:
                best_lap_formatted = None

            teams.append({
                'name': row[0],
                'best_lap_time': best_lap_formatted,
                'avg_lap_seconds': row[2],
                'total_laps': row[3],
                'sessions_count': row[4],
                'classes': row[5],
                'best_lap_timestamp': row[6] if len(row) > 6 else None
            })

        conn.close()

        return jsonify({'teams': teams, 'limit': limit})
    except Exception as e:
        print(f"Error getting top teams: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/stats', methods=['GET'])
def get_team_stats():
    """Get statistics for a specific team"""
    try:
        team_name = request.args.get('team', '').strip().lower()
        session_id = request.args.get('session_id', None)
        track_id = request.args.get('track_id', 1, type=int)  # Default to track 1

        if not team_name:
            return jsonify({'error': 'Team name required'}), 400

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Get overall statistics
        # Handles both formats: with class prefix "1 - TEAMNAME" and without "TEAMNAME"
        stats_query = """
            SELECT
                COUNT(*) as total_records,
                MIN(
                    CASE
                        WHEN best_lap LIKE '%:%' THEN
                            CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                            CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                        WHEN best_lap IS NOT NULL AND best_lap != '' THEN
                            CAST(best_lap AS REAL)
                        ELSE NULL
                    END
                ) as best_lap_seconds,
                COUNT(DISTINCT session_id) as sessions_participated,
                GROUP_CONCAT(DISTINCT SUBSTR(team_name, 1, 1)) as classes_raced,
                MAX(pit_stops) as max_pit_stops
            FROM lap_times
            WHERE CASE
                    WHEN team_name LIKE '% - %' THEN
                        LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                    ELSE
                        LOWER(TRIM(team_name))
                END = ?
        """

        cursor.execute(stats_query, (team_name,))
        stats = cursor.fetchone()

        # Calculate total laps using the race leader's lap count from gap field
        # For each session, find winner's lap count and calculate this team's laps
        session_filter = ""
        query_params = [team_name]
        if session_id:
            session_filter = "AND tfg.session_id = ?"
            query_params.append(int(session_id))

        lap_count_query = f"""
            WITH leader_laps AS (
                SELECT
                    session_id,
                    MAX(CASE
                        WHEN position = 1 AND gap LIKE 'Tour %'
                        THEN CAST(SUBSTR(gap, 6) AS INTEGER)
                        WHEN position = 1 AND gap LIKE 'Lap %'
                        THEN CAST(SUBSTR(gap, 5) AS INTEGER)
                        ELSE 0
                    END) as total_laps
                FROM lap_times
                WHERE gap LIKE 'Tour %' OR gap LIKE 'Lap %'
                GROUP BY session_id
            ),
            team_final_gap AS (
                SELECT DISTINCT
                    lt.session_id,
                    FIRST_VALUE(lt.gap) OVER (PARTITION BY lt.session_id ORDER BY lt.timestamp DESC) as final_gap
                FROM lap_times lt
                WHERE CASE
                        WHEN lt.team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(lt.team_name))
                    END = ?
            )
            SELECT
                SUM(CASE
                    WHEN tfg.final_gap LIKE '% Tour%' THEN
                        ll.total_laps - CAST(SUBSTR(tfg.final_gap, 1, INSTR(tfg.final_gap, ' ') - 1) AS INTEGER)
                    WHEN tfg.final_gap LIKE '% Lap%' THEN
                        ll.total_laps - CAST(SUBSTR(tfg.final_gap, 1, INSTR(tfg.final_gap, ' ') - 1) AS INTEGER)
                    ELSE
                        ll.total_laps
                END) as total_laps_all_sessions
            FROM team_final_gap tfg
            JOIN leader_laps ll ON tfg.session_id = ll.session_id
            WHERE ll.total_laps > 0 {session_filter}
        """

        cursor.execute(lap_count_query, query_params)
        lap_count_result = cursor.fetchone()
        total_laps = lap_count_result[0] if lap_count_result and lap_count_result[0] else 0

        # Get lap history statistics for average lap time
        lap_history_session_filter = ""
        lap_history_params = [team_name]
        if session_id:
            lap_history_session_filter = "AND session_id = ?"
            lap_history_params.append(int(session_id))

        lap_history_query = f"""
            SELECT
                AVG(lap_seconds) as avg_lap_seconds
            FROM (
                SELECT DISTINCT
                    session_id,
                    lap_number,
                    CAST(SUBSTR(lap_time, 1, 1) AS REAL) * 60 + CAST(SUBSTR(lap_time, 3) AS REAL) as lap_seconds
                FROM lap_history
                WHERE CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END = ?
                AND lap_time IS NOT NULL
                AND lap_time != ''
                AND lap_time NOT LIKE '%Tour%'
                AND lap_time NOT LIKE '%Lap%'
                {lap_history_session_filter}
            )
        """

        cursor.execute(lap_history_query, lap_history_params)
        lap_stats = cursor.fetchone()

        # Get session breakdown
        session_query = """
            SELECT
                rs.session_id,
                rs.start_time,
                rs.name as session_name,
                COUNT(lt.id) as lap_records,
                MIN(
                    CASE
                        WHEN lt.best_lap LIKE '%:%' THEN
                            CAST(SUBSTR(lt.best_lap, 1, INSTR(lt.best_lap, ':') - 1) AS REAL) * 60 +
                            CAST(SUBSTR(lt.best_lap, INSTR(lt.best_lap, ':') + 1) AS REAL)
                        WHEN lt.best_lap IS NOT NULL AND lt.best_lap != '' THEN
                            CAST(lt.best_lap AS REAL)
                        ELSE NULL
                    END
                ) as best_lap_seconds
            FROM race_sessions rs
            LEFT JOIN lap_times lt ON rs.session_id = lt.session_id
            WHERE CASE
                    WHEN lt.team_name LIKE '% - %' THEN
                        LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                    ELSE
                        LOWER(TRIM(lt.team_name))
                END = ?
            GROUP BY rs.session_id
            ORDER BY rs.start_time DESC
        """

        cursor.execute(session_query, (team_name,))
        sessions = []
        for row in cursor.fetchall():
            best_lap_secs = row[4]
            if best_lap_secs:
                mins = int(best_lap_secs // 60)
                secs = best_lap_secs % 60
                best_lap_formatted = f"{mins}:{secs:06.3f}"
            else:
                best_lap_formatted = None

            sessions.append({
                'session_id': row[0],
                'start_time': row[1],
                'name': row[2],
                'lap_records': row[3],
                'best_lap': best_lap_formatted
            })

        conn.close()

        # Format best_lap_seconds to MM:SS.mmm
        best_lap_seconds = stats[1] if stats else None
        if best_lap_seconds:
            mins = int(best_lap_seconds // 60)
            secs = best_lap_seconds % 60
            best_lap_time = f"{mins}:{secs:06.3f}"
        else:
            best_lap_time = None

        return jsonify({
            'team_name': team_name,
            'total_records': stats[0] if stats else 0,
            'best_lap_time': best_lap_time,
            'sessions_participated': stats[2] if stats else 0,
            'classes_raced': stats[3].split(',') if stats and stats[3] else [],
            'max_pit_stops': stats[4] if stats else 0,
            'total_laps_completed': total_laps,  # Use calculated total from leader's lap count
            'avg_lap_seconds': round(lap_stats[0], 3) if lap_stats and lap_stats[0] else None,
            'total_pit_stops': stats[4] if stats else 0,  # Use max_pit_stops from lap_times table
            'sessions': sessions
        })
    except Exception as e:
        print(f"Error getting team stats: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/lap-details', methods=['POST'])
def get_lap_details():
    """Get detailed lap-by-lap data for teams in a session"""
    try:
        data = request.json
        team_names = data.get('teams', [])
        session_id = data.get('session_id', None)
        track_id = data.get('track_id', 1)  # Default to track 1

        if not team_names or not session_id:
            return jsonify({'error': 'Teams and session_id required'}), 400

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        lap_details = {}

        for team_name in team_names:
            team_name_lower = team_name.strip().lower()

            # Debug: Count total records for this team in session
            debug_count_query = """
                SELECT COUNT(*) FROM lap_times
                WHERE (
                    CASE
                        WHEN team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE LOWER(TRIM(team_name))
                    END
                ) = ?
                AND session_id = ?
            """
            cursor.execute(debug_count_query, (team_name_lower, int(session_id)))
            total_records = cursor.fetchone()[0]
            print(f"DEBUG: Team {team_name} has {total_records} total records in session {session_id}")

            # Get all laps from lap_times by detecting when last_lap changes
            lap_query = """
                WITH lap_changes AS (
                    SELECT
                        timestamp,
                        last_lap,
                        LAG(last_lap) OVER (ORDER BY timestamp) as prev_last_lap,
                        pit_stops,
                        LAG(pit_stops, 1, 0) OVER (ORDER BY timestamp) as prev_pit_stops
                    FROM lap_times
                    WHERE (
                        CASE
                            WHEN team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE LOWER(TRIM(team_name))
                        END
                    ) = ?
                    AND session_id = ?
                    AND last_lap IS NOT NULL
                    AND last_lap <> ''
                    ORDER BY timestamp
                ),
                lap_completions AS (
                    SELECT
                        ROW_NUMBER() OVER (ORDER BY timestamp) as lap_number,
                        last_lap,
                        CASE
                            WHEN last_lap LIKE '%:%' THEN
                                CAST(SUBSTR(last_lap, 1, INSTR(last_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(last_lap, INSTR(last_lap, ':') + 1) AS REAL)
                            ELSE 0
                        END as lap_seconds,
                        CASE WHEN pit_stops > prev_pit_stops THEN 1 ELSE 0 END as had_pit
                    FROM lap_changes
                    WHERE last_lap <> prev_last_lap OR prev_last_lap IS NULL
                )
                SELECT
                    lap_number,
                    lap_seconds,
                    had_pit
                FROM lap_completions
                WHERE lap_seconds > 50 AND lap_seconds < 600
                ORDER BY lap_number ASC
            """

            cursor.execute(lap_query, (team_name_lower, int(session_id)))
            laps_raw = cursor.fetchall()
            print(f"DEBUG: Team {team_name} - Query returned {len(laps_raw)} laps")

            laps = []
            for (lap_number, lap_seconds, pit_this_lap) in laps_raw:
                laps.append({
                    'lap_number': lap_number,
                    'lap_time': lap_seconds,
                    'pit_stop': pit_this_lap > 0
                })

            lap_details[team_name] = laps

        # Detect stints for all teams based on pit stop laps (3:40 - 3:50 = 220-230 seconds)
        stints = []
        for team_name, laps in lap_details.items():
            team_stints = []
            stint_start = 1
            stint_number = 1

            for i, lap in enumerate(laps):
                # Detect pit stop lap (lap time >= 225 seconds or 3:45)
                if lap['lap_time'] >= 225:
                    # End current stint before the pit lap
                    if lap['lap_number'] > stint_start:
                        team_stints.append({
                            'stint_number': stint_number,
                            'start_lap': stint_start,
                            'end_lap': lap['lap_number'] - 1,
                            'lap_count': lap['lap_number'] - stint_start
                        })
                        stint_number += 1
                    # Next stint starts after the pit lap
                    stint_start = lap['lap_number'] + 1

            # Add final stint (from last pit to end of race)
            if laps and stint_start <= laps[-1]['lap_number']:
                team_stints.append({
                    'stint_number': stint_number,
                    'start_lap': stint_start,
                    'end_lap': laps[-1]['lap_number'],
                    'lap_count': laps[-1]['lap_number'] - stint_start + 1
                })

            stints.append({
                'team_name': team_name,
                'stints': team_stints
            })

        conn.close()

        return jsonify({
            'lap_details': lap_details,
            'stints': stints
        })
    except Exception as e:
        print(f"Error getting lap details: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/compare', methods=['POST'])
def compare_teams():
    """Compare statistics for multiple teams"""
    try:
        data = request.json
        team_names = data.get('teams', [])
        session_id = data.get('session_id', None)
        track_id = data.get('track_id', 1)  # Default to track 1

        if not team_names or len(team_names) < 2:
            return jsonify({'error': 'At least 2 teams required for comparison'}), 400

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        comparison = []

        for team_name in team_names:
            team_name_lower = team_name.strip().lower()

            # Build session filter
            session_filter_stats = ""
            stats_params = [team_name_lower]
            if session_id:
                session_filter_stats = "AND session_id = ?"
                stats_params.append(int(session_id))

            # Get overall statistics
            stats_query = f"""
                SELECT
                    COUNT(*) as total_records,
                    MIN(
                        CASE
                            WHEN best_lap LIKE '%:%' THEN
                                CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                            WHEN best_lap IS NOT NULL AND best_lap != '' THEN
                                CAST(best_lap AS REAL)
                            ELSE NULL
                        END
                    ) as best_lap_seconds,
                    COUNT(DISTINCT session_id) as sessions_participated,
                    GROUP_CONCAT(DISTINCT SUBSTR(team_name, 1, 1)) as classes_raced
                FROM lap_times
                WHERE CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END = ?
                {session_filter_stats}
            """

            cursor.execute(stats_query, stats_params)
            stats = cursor.fetchone()

            # Calculate total laps using the race leader's lap count from gap field
            session_filter_laps = ""
            lap_count_params = [team_name_lower]
            if session_id:
                session_filter_laps = "AND tfg.session_id = ?"
                lap_count_params.append(int(session_id))

            lap_count_query = f"""
                WITH leader_laps AS (
                    SELECT
                        session_id,
                        MAX(CASE
                            WHEN position = 1 AND gap LIKE 'Tour %'
                            THEN CAST(SUBSTR(gap, 6) AS INTEGER)
                            WHEN position = 1 AND gap LIKE 'Lap %'
                            THEN CAST(SUBSTR(gap, 5) AS INTEGER)
                            ELSE 0
                        END) as total_laps
                    FROM lap_times
                    WHERE gap LIKE 'Tour %' OR gap LIKE 'Lap %'
                    GROUP BY session_id
                ),
                team_final_gap AS (
                    SELECT DISTINCT
                        lt.session_id,
                        FIRST_VALUE(lt.gap) OVER (PARTITION BY lt.session_id ORDER BY lt.timestamp DESC) as final_gap
                    FROM lap_times lt
                    WHERE CASE
                            WHEN lt.team_name LIKE '% - %' THEN
                                LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                            ELSE
                                LOWER(TRIM(lt.team_name))
                        END = ?
                )
                SELECT
                    SUM(CASE
                        WHEN tfg.final_gap LIKE '% Tour%' THEN
                            ll.total_laps - CAST(SUBSTR(tfg.final_gap, 1, INSTR(tfg.final_gap, ' ') - 1) AS INTEGER)
                        WHEN tfg.final_gap LIKE '% Lap%' THEN
                            ll.total_laps - CAST(SUBSTR(tfg.final_gap, 1, INSTR(tfg.final_gap, ' ') - 1) AS INTEGER)
                        ELSE
                            ll.total_laps
                    END) as total_laps_all_sessions
                FROM team_final_gap tfg
                JOIN leader_laps ll ON tfg.session_id = ll.session_id
                WHERE ll.total_laps > 0 {session_filter_laps}
            """

            cursor.execute(lap_count_query, lap_count_params)
            lap_count_result = cursor.fetchone()
            total_laps = lap_count_result[0] if lap_count_result and lap_count_result[0] else 0

            # Get lap history statistics for average lap time
            session_filter_history = ""
            lap_history_params = [team_name_lower]
            if session_id:
                session_filter_history = "AND session_id = ?"
                lap_history_params.append(int(session_id))

            lap_history_query = f"""
                SELECT
                    AVG(lap_seconds) as avg_lap_seconds
                FROM (
                    SELECT DISTINCT
                        session_id,
                        lap_number,
                        CAST(SUBSTR(lap_time, 1, 1) AS REAL) * 60 + CAST(SUBSTR(lap_time, 3) AS REAL) as lap_seconds
                    FROM lap_history
                    WHERE CASE
                            WHEN team_name LIKE '% - %' THEN
                                LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE
                                LOWER(TRIM(team_name))
                        END = ?
                    AND lap_time IS NOT NULL
                    AND lap_time != ''
                    AND lap_time NOT LIKE '%Tour%'
                    AND lap_time NOT LIKE '%Lap%'
                    {session_filter_history}
                )
            """

            cursor.execute(lap_history_query, lap_history_params)
            lap_stats = cursor.fetchone()

            # Get lap time distribution (last 50 unique laps) - use DISTINCT to avoid duplicates
            session_filter_dist = ""
            lap_dist_params = [team_name_lower]
            if session_id:
                session_filter_dist = "AND session_id = ?"
                lap_dist_params.append(int(session_id))

            lap_dist_query = f"""
                SELECT DISTINCT
                    session_id,
                    lap_number,
                    lap_time
                FROM lap_history
                WHERE CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END = ?
                AND lap_time IS NOT NULL
                AND lap_time != ''
                AND lap_time NOT LIKE '%Tour%'
                AND lap_time NOT LIKE '%Lap%'
                {session_filter_dist}
                ORDER BY session_id DESC, lap_number DESC
                LIMIT 50
            """

            cursor.execute(lap_dist_query, lap_dist_params)
            lap_times_raw = cursor.fetchall()

            # Parse lap times to seconds
            lap_times = []
            for (session_id, lap_number, lap_time) in lap_times_raw:
                try:
                    if ':' in lap_time:
                        parts = lap_time.split(':')
                        if len(parts) == 2:
                            minutes = int(parts[0])
                            seconds = float(parts[1].replace(',', '.'))
                            lap_seconds = minutes * 60 + seconds
                            if 50 < lap_seconds < 150:  # Filter unrealistic times
                                lap_times.append(lap_seconds)
                except:
                    continue

            # Format best_lap_seconds to MM:SS.mmm
            best_lap_seconds = stats[1] if stats else None
            if best_lap_seconds:
                mins = int(best_lap_seconds // 60)
                secs = best_lap_seconds % 60
                best_lap_formatted = f"{mins}:{secs:06.3f}"
            else:
                best_lap_formatted = None

            comparison.append({
                'team_name': team_name,
                'total_records': stats[0] if stats else 0,
                'best_lap_time': best_lap_formatted,
                'sessions_participated': stats[2] if stats else 0,
                'classes_raced': stats[3].split(',') if stats and stats[3] else [],
                'total_laps_completed': total_laps,  # Use calculated total from leader's lap count
                'avg_lap_seconds': round(lap_stats[0], 3) if lap_stats and lap_stats[0] else None,
                'lap_times': lap_times[:20]  # Return last 20 laps for charting
            })

        conn.close()

        return jsonify({'comparison': comparison})
    except Exception as e:
        print(f"Error comparing teams: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/delete-best-lap', methods=['POST'])
@admin_required
def delete_best_lap():
    """Delete (nullify) a team's best lap time record (admin only)"""
    try:
        data = request.json
        team_name = data.get('team_name', '').strip().lower()
        track_id = data.get('track_id', 1)
        best_lap_time = data.get('best_lap_time', '').strip()

        if not team_name or not best_lap_time:
            return jsonify({'error': 'team_name and best_lap_time are required'}), 400

        # Parse best_lap_time to seconds for comparison
        # Format is "M:SS.mmm" or "MM:SS.mmm"
        try:
            if ':' in best_lap_time:
                parts = best_lap_time.split(':')
                minutes = int(parts[0])
                seconds = float(parts[1])
                best_lap_seconds = minutes * 60 + seconds
            else:
                best_lap_seconds = float(best_lap_time)
        except ValueError:
            return jsonify({'error': 'Invalid best_lap_time format'}), 400

        # Retry logic to handle database locks
        max_retries = 3
        retry_delay = 0.5  # seconds
        last_error = None

        for attempt in range(max_retries):
            try:
                conn = get_track_db_connection(track_id, timeout=5.0)
                cursor = conn.cursor()

                # Find and nullify the best_lap field for records matching this team and lap time
                # Handle both formats: with class prefix "1 - TEAMNAME" and without "TEAMNAME"
                # Also handle mixed best_lap formats: "MM:SS.mmm" and raw seconds
                update_query = """
                    UPDATE lap_times
                    SET best_lap = NULL
                    WHERE CASE
                            WHEN team_name LIKE '% - %' THEN
                                LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE
                                LOWER(TRIM(team_name))
                        END = ?
                    AND ABS(
                        CASE
                            WHEN best_lap LIKE '%:%' THEN
                                CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                            WHEN best_lap IS NOT NULL AND best_lap != '' THEN
                                CAST(best_lap AS REAL)
                            ELSE 999999
                        END - ?
                    ) < 0.01
                """

                cursor.execute(update_query, (team_name, best_lap_seconds))
                rows_updated = cursor.rowcount
                conn.commit()
                conn.close()

                if rows_updated == 0:
                    return jsonify({'error': 'No matching lap time found for this team'}), 404

                return jsonify({
                    'success': True,
                    'message': f'Deleted best lap time for {team_name}',
                    'rows_updated': rows_updated
                })

            except sqlite3.OperationalError as e:
                last_error = e
                if 'locked' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Database locked on attempt {attempt + 1}/{max_retries}, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    raise
            finally:
                try:
                    if 'conn' in locals():
                        conn.close()
                except:
                    pass

        # If we get here, all retries failed
        raise last_error if last_error else Exception("Unknown error during database operation")

    except Exception as e:
        print(f"Error deleting best lap: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/mass-delete-laps', methods=['POST'])
@admin_required
def mass_delete_laps():
    """
    Delete all lap times under a specified threshold (track-wide, admin only)

    Supports two deletion modes:
    1. lap_history: Delete individual lap records from lap_history table
    2. best_laps: Nullify best_lap field in lap_times if below threshold
    """
    try:
        data = request.json
        track_id = data.get('track_id', 1)
        threshold_seconds = data.get('threshold_seconds')
        delete_type = data.get('delete_type', 'lap_history')

        if threshold_seconds is None:
            return jsonify({'error': 'threshold_seconds is required'}), 400

        # Validate delete_type
        if delete_type not in ['lap_history', 'best_laps']:
            return jsonify({'error': 'delete_type must be "lap_history" or "best_laps"'}), 400

        # Retry logic to handle database locks
        max_retries = 3
        retry_delay = 0.5
        last_error = None

        for attempt in range(max_retries):
            try:
                conn = get_track_db_connection(track_id, timeout=10.0)
                cursor = conn.cursor()

                rows_affected = 0

                if delete_type == 'lap_history':
                    # Delete individual lap records from lap_history
                    delete_query = """
                        DELETE FROM lap_history
                        WHERE CASE
                                WHEN lap_time LIKE '%:%' THEN
                                    CAST(SUBSTR(lap_time, 1, INSTR(lap_time, ':') - 1) AS REAL) * 60 +
                                    CAST(SUBSTR(lap_time, INSTR(lap_time, ':') + 1) AS REAL)
                                WHEN lap_time IS NOT NULL AND lap_time != '' THEN
                                    CAST(lap_time AS REAL)
                                ELSE 999999
                            END < ?
                    """
                    cursor.execute(delete_query, (threshold_seconds,))
                    rows_affected = cursor.rowcount

                elif delete_type == 'best_laps':
                    # Nullify best_lap field in lap_times if below threshold
                    update_query = """
                        UPDATE lap_times
                        SET best_lap = NULL
                        WHERE CASE
                                WHEN best_lap LIKE '%:%' THEN
                                    CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                    CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                                WHEN best_lap IS NOT NULL AND best_lap != '' THEN
                                    CAST(best_lap AS REAL)
                                ELSE 999999
                            END < ?
                    """
                    cursor.execute(update_query, (threshold_seconds,))
                    rows_affected = cursor.rowcount

                conn.commit()
                conn.close()

                return jsonify({
                    'success': True,
                    'message': f'Mass deletion completed',
                    'rows_affected': rows_affected,
                    'delete_type': delete_type,
                    'threshold_seconds': threshold_seconds
                })

            except sqlite3.OperationalError as e:
                last_error = e
                if 'locked' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Database locked on attempt {attempt + 1}/{max_retries}, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    raise
            finally:
                try:
                    if 'conn' in locals():
                        conn.close()
                except:
                    pass

        # If we get here, all retries failed
        raise last_error if last_error else Exception("Unknown error during mass delete operation")

    except Exception as e:
        print(f"Error in mass delete: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/all-laps', methods=['GET'])
def get_all_laps():
    """
    Get all laps for a specific team on a track

    Parameters:
    - team (required): team name
    - track_id (required): track ID
    - session_id (optional): filter by session
    - limit (optional): max number of laps to return (default: 50)
    - offset (optional): pagination offset (default: 0)
    """
    try:
        team_name = request.args.get('team', '').strip().lower()
        track_id = request.args.get('track_id', 1, type=int)
        session_id = request.args.get('session_id', None, type=int)
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        if not team_name:
            return jsonify({'error': 'team parameter is required'}), 400

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Build session filter
        session_filter = ""
        query_params = [team_name]
        if session_id:
            session_filter = "AND lh.session_id = ?"
            query_params.append(session_id)

        # Query to get all laps with session information
        query = f"""
            SELECT
                lh.lap_number,
                lh.lap_time,
                lh.session_id,
                rs.name as session_name,
                rs.start_time as session_date,
                lh.timestamp,
                lh.pit_this_lap,
                lh.position_after_lap
            FROM lap_history lh
            JOIN race_sessions rs ON lh.session_id = rs.session_id
            WHERE CASE
                    WHEN lh.team_name LIKE '% - %' THEN
                        LOWER(TRIM(SUBSTR(lh.team_name, INSTR(lh.team_name, ' - ') + 3)))
                    ELSE
                        LOWER(TRIM(lh.team_name))
                END = ?
            {session_filter}
            ORDER BY rs.start_time DESC, lh.lap_number ASC
            LIMIT ? OFFSET ?
        """

        query_params.extend([limit, offset])
        cursor.execute(query, query_params)

        laps = []
        for row in cursor.fetchall():
            laps.append({
                'lap_number': row[0],
                'lap_time': row[1],
                'session_id': row[2],
                'session_name': row[3] if row[3] else 'Unknown Session',
                'session_date': row[4],
                'timestamp': row[5],
                'pit_this_lap': bool(row[6]),
                'position_after_lap': row[7]
            })

        # Get total count for pagination
        count_query = f"""
            SELECT COUNT(*)
            FROM lap_history lh
            WHERE CASE
                    WHEN lh.team_name LIKE '% - %' THEN
                        LOWER(TRIM(SUBSTR(lh.team_name, INSTR(lh.team_name, ' - ') + 3)))
                    ELSE
                        LOWER(TRIM(lh.team_name))
                END = ?
            {session_filter}
        """
        cursor.execute(count_query, [team_name] + (query_params[1:2] if session_id else []))
        total_laps = cursor.fetchone()[0]

        conn.close()

        return jsonify({
            'team_name': team_name,
            'track_id': track_id,
            'total_laps': total_laps,
            'laps': laps,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        print(f"Error getting all laps: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/cross-track-sessions', methods=['GET'])
def get_cross_track_sessions():
    """
    Get all sessions for a team across all tracks

    Parameters:
    - team (required): team name (supports flexible matching - finds all name variations)
    """
    try:
        team_name = request.args.get('team', '').strip().lower()

        if not team_name:
            return jsonify({'error': 'team parameter is required'}), 400

        # Tokenize the team name for flexible matching (handles "DELVENNE Simon" vs "SIMON DELVENNE")
        name_tokens = [token.strip() for token in team_name.split() if token.strip()]

        # Get all tracks from tracks.db
        tracks_conn = sqlite3.connect('tracks.db')
        tracks_cursor = tracks_conn.cursor()
        tracks_cursor.execute('SELECT id, track_name FROM tracks WHERE is_active = 1')
        tracks = tracks_cursor.fetchall()
        tracks_conn.close()

        sessions = []
        total_laps = 0
        tracks_raced = 0
        best_lap_overall = None
        best_lap_overall_seconds = float('inf')

        # Query each track's database
        for track_id, track_name in tracks:
            try:
                conn = get_track_db_connection(track_id)
                cursor = conn.cursor()

                # Build flexible matching conditions for lap_history
                lh_conditions = []
                lh_params = []
                for token in name_tokens:
                    lh_conditions.append("LOWER(lh.team_name) LIKE ?")
                    lh_params.append(f'%{token}%')

                lh_where_clause = " AND ".join(lh_conditions) if lh_conditions else "1=1"

                # Build flexible matching conditions for lap_times
                lt_conditions = []
                lt_params = []
                for token in name_tokens:
                    lt_conditions.append("LOWER(lt.team_name) LIKE ?")
                    lt_params.append(f'%{token}%')

                lt_where_clause = " AND ".join(lt_conditions) if lt_conditions else "1=1"

                # Get sessions for this team on this track (using flexible name matching)
                # Note: We only use lap_history to avoid cartesian product with lap_times
                query = f"""
                    SELECT
                        rs.session_id,
                        rs.name as session_name,
                        rs.start_time as session_date,
                        COUNT(lh.lap_number) as total_laps,
                        MIN(
                            CASE
                                WHEN lh.lap_time LIKE '%:%' THEN
                                    CAST(SUBSTR(lh.lap_time, 1, INSTR(lh.lap_time, ':') - 1) AS REAL) * 60 +
                                    CAST(SUBSTR(lh.lap_time, INSTR(lh.lap_time, ':') + 1) AS REAL)
                                WHEN lh.lap_time IS NOT NULL AND lh.lap_time != '' THEN
                                    CAST(lh.lap_time AS REAL)
                                ELSE NULL
                            END
                        ) as best_lap_seconds,
                        AVG(
                            CASE
                                WHEN lh.lap_time LIKE '%:%' THEN
                                    CAST(SUBSTR(lh.lap_time, 1, INSTR(lh.lap_time, ':') - 1) AS REAL) * 60 +
                                    CAST(SUBSTR(lh.lap_time, INSTR(lh.lap_time, ':') + 1) AS REAL)
                                WHEN lh.lap_time IS NOT NULL AND lh.lap_time != '' THEN
                                    CAST(lh.lap_time AS REAL)
                                ELSE NULL
                            END
                        ) as avg_lap_seconds
                    FROM race_sessions rs
                    INNER JOIN lap_history lh ON rs.session_id = lh.session_id
                        AND ({lh_where_clause})
                    GROUP BY rs.session_id, rs.name, rs.start_time
                    ORDER BY rs.start_time DESC
                """

                cursor.execute(query, lh_params)
                track_sessions = cursor.fetchall()
                conn.close()

                if track_sessions:
                    tracks_raced += 1

                for row in track_sessions:
                    session_id, session_name, session_date, laps_count, best_lap_secs, avg_lap_secs = row

                    # Format best lap
                    if best_lap_secs:
                        mins = int(best_lap_secs // 60)
                        secs = best_lap_secs % 60
                        best_lap_formatted = f"{mins}:{secs:06.3f}"

                        # Track overall best lap
                        if best_lap_secs < best_lap_overall_seconds:
                            best_lap_overall_seconds = best_lap_secs
                            best_lap_overall = best_lap_formatted
                    else:
                        best_lap_formatted = None

                    # Format avg lap
                    if avg_lap_secs:
                        mins = int(avg_lap_secs // 60)
                        secs = avg_lap_secs % 60
                        avg_lap_formatted = f"{mins}:{secs:06.3f}"
                    else:
                        avg_lap_formatted = None

                    sessions.append({
                        'session_id': session_id,
                        'track_id': track_id,
                        'track_name': track_name,
                        'session_name': session_name if session_name else 'Unknown Session',
                        'session_date': session_date,
                        'total_laps': laps_count if laps_count else 0,
                        'best_lap': best_lap_formatted,
                        'avg_lap': avg_lap_formatted
                    })

                    total_laps += laps_count if laps_count else 0

            except Exception as track_error:
                print(f"Error querying track {track_id}: {track_error}")
                continue

        return jsonify({
            'team_name': team_name,
            'sessions': sessions,
            'overall_stats': {
                'total_sessions': len(sessions),
                'total_laps': total_laps,
                'tracks_raced': tracks_raced,
                'best_lap_overall': best_lap_overall
            }
        })

    except Exception as e:
        print(f"Error getting cross-track sessions: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-data/session-laps', methods=['GET'])
def get_session_laps():
    """
    Get all lap details for a specific team in a specific session

    Parameters:
    - team (required): team name (flexible matching)
    - track_id (required): track ID
    - session_id (required): session ID
    """
    try:
        team_name = request.args.get('team', '').strip().lower()
        track_id = request.args.get('track_id', type=int)
        session_id = request.args.get('session_id', type=int)

        if not team_name:
            return jsonify({'error': 'team parameter is required'}), 400
        if not track_id:
            return jsonify({'error': 'track_id parameter is required'}), 400
        if not session_id:
            return jsonify({'error': 'session_id parameter is required'}), 400

        # Tokenize the team name for flexible matching
        name_tokens = [token.strip() for token in team_name.split() if token.strip()]

        # Build flexible matching conditions
        conditions = []
        params = [session_id]
        for token in name_tokens:
            conditions.append("LOWER(lh.team_name) LIKE ?")
            params.append(f'%{token}%')

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        conn = get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Calculate lap numbers based on chronological order since lap_number field is unreliable
        query = f"""
            SELECT
                ROW_NUMBER() OVER (ORDER BY lh.timestamp ASC) as lap_number,
                lh.lap_time,
                lh.timestamp,
                lh.pit_this_lap,
                lh.position_after_lap
            FROM lap_history lh
            WHERE lh.session_id = ?
                AND ({where_clause})
            ORDER BY lh.timestamp ASC
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        laps = []
        for row in rows:
            lap_number, lap_time, timestamp, pit_this_lap, position_after_lap = row
            laps.append({
                'lap_number': lap_number,
                'lap_time': lap_time,
                'timestamp': timestamp,
                'pit_this_lap': bool(pit_this_lap),
                'position_after_lap': position_after_lap
            })

        return jsonify({
            'laps': laps,
            'total_count': len(laps)
        })

    except Exception as e:
        print(f"Error getting session laps: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

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

def get_track_db_connection(track_id: int, timeout: float = 5.0):
    """
    Get database connection for a specific track with timeout

    Args:
        track_id: The track ID
        timeout: Timeout in seconds for database operations (default: 5.0)

    Returns:
        sqlite3.Connection object
    """
    db_path = get_database_path(track_id)
    conn = sqlite3.connect(db_path, timeout=timeout)
    # Enable WAL mode for better concurrent access (if not already enabled)
    conn.execute("PRAGMA journal_mode=WAL")
    # Set busy timeout to 5 seconds (5000ms)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Pit Alert System - Send alerts from web client to Android overlay
@app.route('/api/trigger-pit-alert', methods=['POST'])
def trigger_pit_alert():
    """Trigger a pit alert for a specific team on a track"""
    data = request.json
    
    track_id = data.get('track_id')
    team_name = data.get('team_name')
    alert_message = data.get('alert_message', 'PIT NOW')
    
    if not track_id or not team_name:
        return jsonify({
            'status': 'error', 
            'message': 'track_id and team_name are required'
        }), 400
    
    try:
        # Emit to the team's specific room
        room = f'team_track_{track_id}_{team_name}'
        
        alert_data = {
            'track_id': track_id,
            'team_name': team_name,
            'alert_type': 'pit_required',
            'alert_message': alert_message,
            'timestamp': datetime.now().isoformat(),
            'flash_color': '#FF0000',  # Red flash
            'duration_ms': 80000,      # Flash for 80 seconds
            'priority': 'high'
        }
        
        # Emit to team-specific room (Android clients in that room will receive it)
        socketio.emit('pit_alert', alert_data, room=room)
        
        # Also emit to track room for web clients to show the alert
        track_room = f'track_{track_id}'
        socketio.emit('pit_alert_broadcast', {
            'track_id': track_id,
            'team_name': team_name,
            'alert_message': alert_message,
            'timestamp': datetime.now().isoformat()
        }, room=track_room)
        
        print(f"[PIT ALERT] 🚨 PIT ALERT triggered for team '{team_name}' on track {track_id} - Message: '{alert_message}'")
        print(f"[PIT ALERT] ✅ Successfully emitted 'pit_alert' to room: {room}")
        print(f"[PIT ALERT] ✅ Successfully emitted 'pit_alert_broadcast' to room: {track_room}")
        
        return jsonify({
            'status': 'success',
            'message': f'Pit alert sent to {team_name}',
            'room': room,
            'alert': alert_data
        })
        
    except Exception as e:
        print(f"Error triggering pit alert: {e}")
        return jsonify({
            'status': 'error', 
            'message': f'Failed to trigger pit alert: {str(e)}'
        }), 500

# Socket.IO Admin Endpoints - for monitoring room joins
@socketio.on('join_team_room')
def handle_join_team_room_monitor(data):
    """Enhanced version that logs all room joins for monitoring"""
    """Handle client joining a team-specific room for a track"""
    track_id = data.get('track_id')
    team_name = data.get('team_name')
    
    if not track_id or not team_name:
        emit('team_room_error', {
            'error': 'track_id and team_name are required',
            'timestamp': datetime.now().isoformat()
        })
        return
    
    try:
        # Join the team-specific room
        room = f'team_track_{track_id}_{team_name}'
        join_room(room)
        
        # Log for monitoring
        print(f"[ROOM MONITOR] Client {request.sid} JOINED team room: {room}")
        print(f"[ROOM MONITOR] Active clients in {room}: {len(socketio.server.rooms.get(room, set()))}")
        
        # Send confirmation with team and track info
        emit('team_room_joined', {
            'track_id': track_id,
            'team_name': team_name,
            'room': room,
            'sid': request.sid
        })
        
    except Exception as e:
        print(f"Error handling join_team_room: {e}")
        emit('team_room_error', {
            'error': f'Failed to join team room: {str(e)}',
            'timestamp': datetime.now().isoformat()
        })

@socketio.on('leave_team_room')
def handle_leave_team_room_monitor(data):
    """Enhanced version that logs all room leaves for monitoring"""
    """Handle client leaving a team-specific room"""
    track_id = data.get('track_id')
    team_name = data.get('team_name')
    
    if not track_id or not team_name:
        return
    
    try:
        room = f'team_track_{track_id}_{team_name}'
        leave_room(room)
        
        # Log for monitoring
        print(f"[ROOM MONITOR] Client {request.sid} LEFT team room: {room}")
        print(f"[ROOM MONITOR] Remaining clients in {room}: {len(socketio.server.rooms.get(room, set()))}")
        
    except Exception as e:
        print(f"Error handling leave_team_room: {e}")

@app.route('/api/admin/socketio/rooms', methods=['POST'])
@admin_required
def admin_get_socketio_rooms():
    """Get all active Socket.IO rooms (admin only)"""
    try:
        if not hasattr(socketio, 'server') or not hasattr(socketio.server, 'rooms'):
            return jsonify({'error': 'Socket.IO server not available'}), 503
        
        # Get all rooms (this includes Socket.IO internal rooms)
        rooms = list(socketio.server.rooms.keys())
        
        # Filter out internal rooms (those that start with the client SID)
        non_internal_rooms = [room for room in rooms if not any(sid in room for sid in socketio.server.rooms.keys() if len(room) > 20)]
        
        # Return unique rooms
        unique_rooms = list(set(non_internal_rooms))
        unique_rooms.sort()
        
        return jsonify(unique_rooms)
    except Exception as e:
        return jsonify({'error': f'Failed to get rooms: {str(e)}'}), 500

@app.route('/api/admin/socketio/room-info', methods=['POST'])
@admin_required
def admin_get_room_info():
    """Get information about a specific Socket.IO room (admin only)"""
    try:
        data = request.json
        room_name = data.get('room')
        
        if not room_name:
            return jsonify({'error': 'room parameter is required'}), 400
        
        if not hasattr(socketio, 'server') or not hasattr(socketio.server, 'rooms'):
            return jsonify({'error': 'Socket.IO server not available'}), 503
        
        # Get clients in the room
        clients = socketio.server.rooms.get(room_name, set())
        
        return jsonify({
            'room': room_name,
            'client_count': len(clients),
            'clients': list(clients),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': f'Failed to get room info: {str(e)}'}), 500

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



