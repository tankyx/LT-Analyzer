from flask import Flask, jsonify, request
import random
import time
import threading
from datetime import datetime
from collections import deque
import math

app = Flask(__name__)

# Configuration
NUM_TEAMS = 40
TRACK_LENGTH_METERS = 1375  # Typical karting track length
BASE_LAP_TIME_SECONDS = 73  # Base lap time around 73 seconds
LAP_TIME_VARIANCE = 1.0     # Variance in seconds to add randomness
MAX_RACE_TIME_SECONDS = 60 * 60 * 3  # 3 hours race
PIT_STOP_INTERVAL_MIN = 9  # Min laps between pit stops
PIT_STOP_INTERVAL_MAX = 47  # Max laps between pit stops
PIT_STOP_DURATION = 150      # Pit stop duration in seconds
PIT_STOP_CHANCE = 0.001      # Random chance of an early pit stop per lap

# Global race state
race_data = {
    'teams': [],
    'session_info': {
        'dyn1': 'Race Simulation',
        'dyn2': 'Test Track',
        'light': 'green'
    },
    'last_update': None,
    'my_team': None,
    'monitored_teams': [],
    'delta_times': {},
    'gap_history': {},
    'race_time': 0,
    'is_running': False
}

# Team class to manage team state
class Team:
    def __init__(self, kart_num, team_name, skill_level):
        self.kart_num = kart_num
        self.team_name = team_name
        self.skill_level = skill_level  # 0.9 to 1.1 (1.0 is average)
        self.position = 0
        self.last_position = 0  # Track previous position to detect position changes
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
        self.status = "On Track"  # Default status
        self.status_duration = 0  # How long to maintain a temporary status
        self.last_lap_seconds = 0
        self.consistency = random.uniform(0.98, 0.99)  # How consistent lap times are
        self.tire_wear = 1.0  # 1.0 is new tires, decreases with laps
        self.fuel_level = 1.0  # 1.0 is full tank, decreases with laps
        self.race_finished = False  # Flag to track if the team has finished the race
        
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
        return f"{minutes}:{seconds_remainder:.3f}".replace(".", ":")
        
    def format_runtime(self, seconds):
        """Format seconds to MM:SS"""
        minutes = int(seconds // 60)
        seconds_remainder = int(seconds % 60)
        return f"{minutes}:{seconds_remainder:02d}"
        
    def calculate_lap_time(self):
        """Calculate a realistic lap time based on skill and conditions"""
        # Update status duration and reset temporary statuses
        if self.status_duration > 0:
            self.status_duration -= 1
            if self.status_duration == 0:
                # Reset temporary statuses
                if self.status in ["Up", "Down", "Pit-out"]:
                    self.status = "On Track"
        
        if self.race_finished:
            self.status = "Finished"
            return 999  # No more laps
            
        if self.in_pits:
            # Process pit stop
            self.pit_time_remaining -= 1
            
            # When pit stop is almost complete, change status to "Pit-out"
            if self.pit_time_remaining == 10:  # 10 seconds before exit
                self.status = "Pit-out"
                self.status_duration = 15  # Show Pit-out status for 15 seconds
            
            if self.pit_time_remaining <= 0:
                self.in_pits = False
                self.status = "Pit-out"  # Show Pit-out status temporarily
                self.status_duration = 15  # Show for 15 seconds
                self.tire_wear = 1.0  # Fresh tires
                self.fuel_level = 1.0  # Full tank
                self.next_pit_in = random.randint(PIT_STOP_INTERVAL_MIN, PIT_STOP_INTERVAL_MAX)
            return 999  # Still in pits
        
        # Base lap time modified by skill level
        base_time = BASE_LAP_TIME_SECONDS / self.skill_level
        
        # Add some random variation
        variation = random.uniform(-LAP_TIME_VARIANCE, LAP_TIME_VARIANCE)
        
        # Add effects of tire wear
        tire_effect = (1.0 - self.tire_wear) * 2
        
        # Add effects of fuel level (lighter is faster)
        fuel_effect = (1.0 - self.fuel_level) * -0.5
        
        # Calculate lap time
        lap_time = base_time + variation + tire_effect + fuel_effect
        
        # Ensure some consistency between laps (weighted average with last lap)
        if self.last_lap_seconds > 0:
            lap_time = (lap_time * (1.0 - self.consistency)) + (self.last_lap_seconds * self.consistency)
        
        # Check if pit stop is needed
        self.next_pit_in -= 1
        
        # Decrease tire performance and fuel level
        self.tire_wear -= random.uniform(0.01, 0.03)
        self.fuel_level -= random.uniform(0.02, 0.04)
        
        # Random chance of early pit stop (mechanical issue, strategy)
        if self.next_pit_in <= 0 or random.random() < PIT_STOP_CHANCE:
            self.in_pits = True
            self.pit_time_remaining = PIT_STOP_DURATION
            self.pit_stops += 1
            self.status = "Pit-in"
            return 999  # Entering pits
        
        return lap_time

    def update_position(self, new_position):
        """Update the team's position and set status accordingly if it changed"""
        if new_position != self.position:
            # Store old position
            old_position = self.position
            # Update to new position
            self.position = new_position
            
            # Set status based on position change
            if self.last_position != 0 and not self.in_pits:  # Skip on first assignment or during pit stops
                if new_position < self.last_position:
                    self.status = "Up"  # Moved up positions
                    self.status_duration = 5  # Show for 5 seconds
                elif new_position > self.last_position:
                    self.status = "Down"  # Lost positions
                    self.status_duration = 5  # Show for 5 seconds
            
            # Update last position for next comparison
            self.last_position = new_position

# Generate realistic team names
def generate_team_name():
    prefixes = ["Team", "Racing", "Kart", "Speed", "Apex", "Circuit", "Pro", "Elite", "Turbo", "Drift"]
    names = ["Alpha", "Beta", "Gamma", "Delta", "Omega", "Phoenix", "Falcon", "Tiger", "Eagle", "Dragon", 
             "Viper", "Cobra", "Lightning", "Thunder", "Storm", "Blaze", "Fire", "Ice", "Steel", "Carbon"]
    suffixes = ["Racing", "Karts", "Motorsport", "Team", "Racers", "Crew", "Squad", "Champions", "Masters", "Pros"]
    
    if random.random() < 0.3:  # 30% chance of having a sponsor
        sponsors = ["RedBull", "Monster", "Gulf", "Shell", "Mobil", "Castrol", "Pirelli", "Bridgestone", 
                    "DHL", "GoPro", "Sparco", "OMP", "Alpine", "Alpinestars", "Brembo"]
        return f"{random.choice(sponsors)} {random.choice(names)} {random.choice(suffixes)}"
    
    if random.random() < 0.5:  # 50% chance of prefix+name style
        return f"{random.choice(prefixes)} {random.choice(names)}"
    else:  # 50% chance of name+suffix style
        return f"{random.choice(names)} {random.choice(suffixes)}"

# Initialize teams
def initialize_teams():
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

# Update team positions and gaps
def update_positions_and_gaps(teams):
    # Sort teams by total distance covered (most to least)
    sorted_teams = sorted(teams, key=lambda t: t.total_distance, reverse=True)
    
    # Update positions
    for i, team in enumerate(sorted_teams):
        team.update_position(i + 1)
    
    # Calculate gaps (leader has 0 gap)
    leader = sorted_teams[0]
    leader.gap = "0.000"
    leader.gap_seconds = 0
    
    for team in sorted_teams[1:]:
        # Gap is distance difference converted to time
        distance_diff = leader.total_distance - team.total_distance
        if distance_diff <= 0:
            team.gap = "0.000"
            team.gap_seconds = 0
        else:
            # Convert distance to time using approximate speed
            approx_speed = TRACK_LENGTH_METERS / BASE_LAP_TIME_SECONDS  # meters per second
            time_diff = distance_diff / approx_speed
            team.gap = f"{time_diff:.3f}"
            team.gap_seconds = time_diff
    
    return sorted_teams

# Check if a team has finished the race
def check_race_completion(team, race_time, max_race_time):
    """Mark a team as finished if the race time is almost up"""
    if race_time >= max_race_time - 60 and not team.race_finished and not team.in_pits:
        # Randomly finish teams in the last minute based on position
        # Teams in higher positions finish earlier
        finish_chance = 0.05 * (1.0 / team.position) * ((race_time - (max_race_time - 60)) / 60)
        if random.random() < finish_chance:
            team.race_finished = True
            team.status = "Finished"
            return True
    return False

# Run race simulation
def simulate_race():
    global race_data
    
    # Initialize teams
    teams = initialize_teams()
    race_data['teams'] = [team.to_dict() for team in teams]
    race_data['race_time'] = 0
    race_data['is_running'] = True
    
    # Initialize gap history for all teams
    for team in teams:
        race_data['gap_history'][str(team.kart_num)] = {
            'gaps': [],
            'last_update': None
        }
    
    # Simulation time step (1 second)
    time_step = 1.0
    
    # Main simulation loop
    while race_data['race_time'] < MAX_RACE_TIME_SECONDS and race_data['is_running']:
        # Update race time
        race_data['race_time'] += time_step
        
        # Process each team
        for team in teams:
            # Update runtime
            team.run_time_seconds += time_step
            team.run_time = team.format_runtime(team.run_time_seconds)
            
            # Check if the team should finish the race
            check_race_completion(team, race_data['race_time'], MAX_RACE_TIME_SECONDS)
            
            # Randomly stop a kart (mechanical issue)
            if not team.in_pits and not team.race_finished and random.random() < 0.00005:  # Very rare chance
                team.status = "Stopped"
                team.status_duration = random.randint(30, 120)  # Stop for 30-120 seconds
            
            # Calculate distance covered in this time step
            if team.in_pits or team.status == "Stopped" or team.race_finished:
                # No distance covered in pits, when stopped, or after finishing
                pass
            else:
                # Approximate speed in meters per second
                if team.last_lap_seconds > 0:
                    speed = TRACK_LENGTH_METERS / team.last_lap_seconds
                else:
                    speed = TRACK_LENGTH_METERS / BASE_LAP_TIME_SECONDS
                
                distance_this_step = speed * time_step
                team.total_distance += distance_this_step
                
                # Check if completed a lap
                laps_completed = math.floor(team.total_distance / TRACK_LENGTH_METERS)
                if laps_completed > team.total_laps:
                    # New lap completed
                    team.total_laps = laps_completed
                    
                    # Calculate lap time
                    lap_time = team.calculate_lap_time()
                    
                    if lap_time < 900:  # Not in pits or stopped
                        # Update last lap time
                        team.last_lap_seconds = lap_time
                        team.last_lap = team.format_time(lap_time)
                        
                        # Update best lap time
                        if lap_time < team.best_lap_seconds:
                            team.best_lap_seconds = lap_time
                            team.best_lap = team.format_time(lap_time)
        
        # Update positions and gaps
        updated_teams = update_positions_and_gaps(teams)
        
        # Update team dictionaries
        team_dicts = [team.to_dict() for team in updated_teams]
        race_data['teams'] = team_dicts
        
        # Update last update timestamp
        race_data['last_update'] = datetime.now().strftime('%H:%M:%S')
        
        # Calculate delta times if my_team is set
        if race_data['my_team']:
            calculate_delta_times()
            
        # Sleep to control simulation speed (4x real time)
        time.sleep(time_step / 4)

def calculate_delta_times():
    """Calculate delta times between my team and monitored teams"""
    global race_data
    
    my_team_kart = race_data['my_team']
    monitored_karts = race_data['monitored_teams']
    teams = race_data['teams']
    
    if not my_team_kart or not teams:
        return {}

    my_team = next((team for team in teams if team['Kart'] == my_team_kart), None)
    if not my_team:
        return {}

    deltas = {}
    try:
        my_pit_stops = int(my_team.get('Pit Stops', '0') or '0')
        my_base_gap = float(my_team.get('Gap', '0').replace(',', '.') or '0')
        
        # Initialize gap history for new karts
        for kart in monitored_karts:
            if kart not in race_data['gap_history']:
                race_data['gap_history'][kart] = {
                    'gaps': deque(maxlen=10),  # Store last 10 gaps
                    'last_update': None
                }
        
        for kart in monitored_karts:
            monitored_team = next((team for team in teams if team['Kart'] == kart), None)
            if monitored_team:
                try:
                    # Calculate gap between monitored team and my team
                    mon_pit_stops = int(monitored_team.get('Pit Stops', '0') or '0')
                    mon_base_gap = float(monitored_team.get('Gap', '0').replace(',', '.') or '0')
                    
                    # Calculate real gap including pit stop compensation
                    real_gap = (mon_base_gap - my_base_gap) + ((mon_pit_stops - my_pit_stops) * 25)
                    real_gap = round(real_gap, 3)
                    
                    # Update gap history
                    gap_history = race_data['gap_history'][kart]
                    last_lap = monitored_team.get('Last Lap')
                    
                    # Only update history when we see a new lap
                    if last_lap and last_lap != gap_history['last_update']:
                        gap_history['gaps'].append(real_gap)
                        gap_history['last_update'] = last_lap
                    
                    # Get gaps as list for calculations
                    gaps = list(gap_history['gaps'])
                    
                    # Calculate trends
                    trend_1, arrow_1 = calculate_trend(real_gap, gaps[-2:] if len(gaps) >= 2 else [])
                    trend_5, arrow_5 = calculate_trend(real_gap, gaps[-5:] if len(gaps) >= 5 else [])
                    trend_10, arrow_10 = calculate_trend(real_gap, gaps[-10:] if len(gaps) >= 10 else [])
                    
                    deltas[kart] = {
                        'gap': real_gap,
                        'team_name': monitored_team.get('Team', ''),
                        'position': int(monitored_team.get('Position', '0')),
                        'last_lap': last_lap,
                        'best_lap': monitored_team.get('Best Lap', ''),
                        'pit_stops': str(mon_pit_stops),
                        'trends': {
                            'lap_1': {'value': trend_1, 'arrow': arrow_1},
                            'lap_5': {'value': trend_5, 'arrow': arrow_5},
                            'lap_10': {'value': trend_10, 'arrow': arrow_10}
                        }
                    }
                except (ValueError, TypeError, AttributeError) as e:
                    print(f"Error calculating delta for kart {kart}: {e}")
                    continue
    except Exception as e:
        print(f"Error calculating deltas: {e}")
        return {}
    
    race_data['delta_times'] = deltas
    return deltas

def calculate_trend(current_gap, previous_gaps):
    """Calculate trend and determine arrow type based on gap change
    Returns: (trend_value, arrow_type)
    trend_value: negative means we're catching up
    arrow_type: 1, 2, or 3 for single, double, triple arrow"""
    # Need at least 2 laps to show a trend
    if len(previous_gaps) < 2:
        return 0, 0
    
    avg_previous = sum(previous_gaps) / len(previous_gaps)
    trend = current_gap - avg_previous
    
    if abs(trend) < 0.5:
        arrow = 1
    elif abs(trend) < 1.0:
        arrow = 2
    else:
        arrow = 3
        
    return trend, arrow

def get_serializable_race_data():
    """Convert race_data to a JSON-serializable format"""
    serializable_data = {
        'teams': race_data['teams'],
        'session_info': race_data['session_info'],
        'last_update': race_data['last_update'],
        'my_team': race_data['my_team'],
        'monitored_teams': race_data['monitored_teams'],
        'delta_times': race_data['delta_times']
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

@app.route('/api/race-data')
def get_race_data():
    return jsonify(get_serializable_race_data())

@app.route('/api/update-monitoring', methods=['POST'])
def update_monitoring():
    data = request.json
    print("Received monitoring update:", data)  # Debug print
    race_data['my_team'] = data.get('myTeam')
    race_data['monitored_teams'] = data.get('monitoredTeams', [])
    print("Updated race_data:", race_data['my_team'], race_data['monitored_teams'])  # Debug print
    return jsonify({'status': 'success'})

@app.route('/api/start-simulation', methods=['POST'])
def start_simulation():
    global race_data
    
    # Reset any existing race
    race_data['teams'] = []
    race_data['last_update'] = None
    race_data['delta_times'] = {}
    race_data['gap_history'] = {}
    race_data['my_team'] = None
    race_data['monitored_teams'] = []
    
    # Start simulation in a background thread
    if not race_data['is_running']:
        simulation_thread = threading.Thread(target=simulate_race, daemon=True)
        simulation_thread.start()
        return jsonify({'status': 'success', 'message': 'Race simulation started'})
    else:
        return jsonify({'status': 'error', 'message': 'Simulation already running'})

@app.route('/api/stop-simulation', methods=['POST'])
def stop_simulation():
    global race_data
    race_data['is_running'] = False
    return jsonify({'status': 'success', 'message': 'Race simulation stopped'})

if __name__ == '__main__':
    try:
        # Enable CORS
        from flask_cors import CORS
        CORS(app)
        
        print("Starting Flask server on port 5000...")
        # Run the Flask app on port 5000
        app.run(host='0.0.0.0', port=5000, debug=True)
    except Exception as e:
        print(f"Error starting server: {e}")
