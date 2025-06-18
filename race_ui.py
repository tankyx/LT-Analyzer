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

# Initialize Flask app
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # For session management
CORS(app, 
     origins=["http://localhost:3000", "https://krranalyser.fr", "http://krranalyser.fr"],
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

def emit_race_update(update_type='full', data=None):
    """Emit race data updates to all connected clients"""
    if len(connected_clients) == 0:
        return
    
    # Only emit if we have actual data to send
    if not race_data.get('teams') and update_type != 'custom':
        return
        
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

# Function to calculate delta times between teams
def calculate_delta_times(teams, my_team_kart, monitored_karts):
    """Calculate delta times between my team and monitored teams"""
    global race_data, PIT_STOP_TIME, REQUIRED_PIT_STOPS
    
    if not my_team_kart or not teams:
        return {}

    my_team = next((team for team in teams if team.get('Kart') == my_team_kart), None)
    if not my_team:
        return {}

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
                            team_pos = int(t.get('Position', '0'))
                            if start_pos < team_pos < end_pos:
                                team_gap = t.get('Gap', '0')
                                if 'Tour' in team_gap:
                                    # This team is lapped
                                    lap_diff += int(team_gap.split()[0])
                        
                        return lap_diff
                    
                    my_position = int(my_team.get('Position', '0'))
                    mon_position = int(monitored_team.get('Position', '0'))
                    
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
                                    team_karts = [int(my_team.get('Kart', 0)), int(monitored_team.get('Kart', 0))]
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
                                    team_karts = [int(my_team.get('Kart', 0)), int(monitored_team.get('Kart', 0))]
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
                        'position': int(monitored_team.get('Position', '0')),
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
        INSERT INTO sessions (id, user_id, expires_at)
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
        WHERE s.id = ? AND s.expires_at > ?
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
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    # Hash the password
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
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
        
        # Validate URL if provided and not in simulation mode
        if not simulation_mode and not timing_url:
            return jsonify({'status': 'error', 'message': 'Timing URL or track ID is required for real data mode'}), 400
        
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
            'location': '',  # Not in tracks.db
            'length_meters': None,  # Not in tracks.db
            'description': '',  # Not in tracks.db
            'timing_url': track['timing_url'],
            'websocket_url': track['websocket_url'],
            'column_mappings': track['column_mappings'],
            'is_active': True,  # Default to active
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
        column_mappings=data.get('column_mappings')
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
        column_mappings=data.get('column_mappings')
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

if __name__ == '__main__':
    # Don't automatically start the update thread - wait for user to choose mode
    # start_update_thread()
    
    try:
        # Run the Flask app with SocketIO
        print("Starting Flask-SocketIO server on port 5000...")
        print("Ready to start data collection - use the web interface to choose mode")
        
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
