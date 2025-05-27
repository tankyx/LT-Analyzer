import asyncio
import json
import threading
import time
import traceback
from datetime import datetime
from collections import deque
import random
import math

from flask import Flask, jsonify, request
from flask_cors import CORS

from apex_timing_parser import ApexTimingParserPlaywright

# Initialize Flask app
app = Flask(__name__)
CORS(app)

REQUIRED_PIT_STOPS = 7
PIT_STOP_TIME = 158

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
        'pit_time': PIT_STOP_TIME
    },
    'race_time': 0,
    'is_running': False,
    'simulation_mode': SIMULATION_MODE
}

# Create our parser
parser = None
update_thread = None
stop_event = threading.Event()
simulation_teams = []

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
        
        # Check if my team is in position 1
        if my_team.get('Position') == '1':
            my_base_gap = 0.0
        else:
            my_base_gap = float(my_team.get('Gap', '0').replace(',', '.') or '0')
        
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
                    
                    # If position is 1, gap is 0
                    if monitored_team.get('Position') == '1':
                        mon_base_gap = 0.0
                    else:
                        mon_base_gap = float(monitored_team.get('Gap', '0').replace(',', '.') or '0')
                    
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
        
        # Calculate delta times if my_team is set
        if race_data['my_team'] and race_data['monitored_teams']:
            calculate_delta_times(team_dicts, race_data['my_team'], race_data['monitored_teams'])
            
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
        'simulation_mode': race_data.get('simulation_mode', False)
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
    
    # Initialize the parser for real data
    parser = ApexTimingParserPlaywright()
    if not await parser.initialize():
        print("Failed to initialize parser. Exiting update thread.")
        return
    
    try:
        print("Background update thread started")
        url = "https://www.apex-timing.com/live-timing/karting-mariembourg/index.html"
        
        while not stop_event.is_set():
            try:
                print("Fetching new data...")
                grid_html, dyna_html = await parser.get_page_content(url)
                
                if grid_html and dyna_html:
                    # Parse dynamic info
                    session_info = parser.parse_dyna_info(dyna_html)
                    race_data['session_info'] = session_info
                    
                    # Parse grid data
                    df = parser.parse_grid_data(grid_html)
                    if not df.empty:
                        # Convert DataFrame to list of dictionaries
                        teams_data = df.to_dict('records')
                        race_data['teams'] = teams_data
                        race_data['last_update'] = datetime.now().strftime('%H:%M:%S')
                        
                        # Update delta times for monitored teams
                        if race_data['my_team'] and race_data['monitored_teams']:
                            delta_times = calculate_delta_times(
                                teams_data,
                                race_data['my_team'],
                                race_data['monitored_teams']
                            )
                            race_data['delta_times'] = delta_times
                        
                        print(f"Updated data at {race_data['last_update']} - {len(teams_data)} teams")
            except Exception as e:
                print(f"Error updating race data: {e}")
                print(traceback.format_exc())
                
                # Try to reinitialize the browser if there was an error
                await parser.cleanup()
                if not await parser.initialize():
                    print("Failed to reinitialize parser. Exiting update thread.")
                    return
            
            # Wait before next update
            await asyncio.sleep(5)
    except Exception as e:
        print(f"Error in update thread: {e}")
        print(traceback.format_exc())
    finally:
        if parser:
            await parser.cleanup()
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
    
    return jsonify({'status': 'success'})

@app.route('/api/start-simulation', methods=['POST'])
def start_simulation():
    """Start the data collection thread"""
    global update_thread, stop_event, race_data
    
    try:
        # Get mode from request (default to real data)
        data = request.json or {}
        simulation_mode = data.get('simulation', False)
        print(f"Starting with simulation mode: {simulation_mode}")
        
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
        
        # Start a new thread
        start_update_thread()
        
        mode_text = 'simulation' if simulation_mode else 'real data collection'
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
    global update_thread
    
    is_running = update_thread is not None and update_thread.is_alive()
    return jsonify({
        'status': 'running' if is_running else 'stopped',
        'last_update': race_data['last_update']
    })

@app.route('/api/update-pit-config', methods=['POST'])
def update_pit_config():
    """Update pit stop configuration"""
    global race_data, PIT_STOP_TIME, REQUIRED_PIT_STOPS
    
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
            
        print(f"Updated pit config: time={PIT_STOP_TIME}s, required stops={REQUIRED_PIT_STOPS}")
        return jsonify({'status': 'success', 'message': 'Pit stop configuration updated'})
    
    return jsonify({'status': 'error', 'message': 'Invalid configuration data'})

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

if __name__ == '__main__':
    # Don't automatically start the update thread - wait for user to choose mode
    # start_update_thread()
    
    try:
        # Run the Flask app
        print("Starting Flask server on port 5000...")
        print("Ready to start data collection - use the web interface to choose mode")
        app.run(host='0.0.0.0', port=5000, debug=False)
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
