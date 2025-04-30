import asyncio
import json
import threading
import time
import traceback
from datetime import datetime
from collections import deque

from flask import Flask, jsonify, request
from flask_cors import CORS

from apex_timing import ApexTimingParserPlaywright

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize global variables
race_data = {
    'teams': [],
    'session_info': {},
    'last_update': None,
    'my_team': None,
    'monitored_teams': [],
    'delta_times': {},
    'gap_history': {}
}

# Create our parser
parser = None
update_thread = None
stop_event = threading.Event()

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
    global race_data
    
    if not my_team_kart or not teams:
        return {}

    my_team = next((team for team in teams if team.get('Kart') == my_team_kart), None)
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
                    
                    # If position is 1, gap is 0
                    if monitored_team.get('Position') == '1':
                        mon_base_gap = 0.0
                    else:
                        mon_base_gap = float(monitored_team.get('Gap', '0').replace(',', '.') or '0')
                    
                    # Calculate real gap including pit stop compensation
                    real_gap = (mon_base_gap - my_base_gap) + ((mon_pit_stops - my_pit_stops) * 150)
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
    
    return deltas

# Function to make gap_history serializable for JSON
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

# Function to update race data in the background
async def update_race_data():
    global race_data, parser
    
    # Initialize the parser
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
    stop_event.clear()
    
    # Define a wrapper function for asyncio
    def run_async_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(update_race_data())
        loop.close()
    
    # Start the thread
    update_thread = threading.Thread(target=run_async_loop, daemon=True)
    update_thread.start()

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
    global update_thread, stop_event
    
    # Stop any existing thread
    if update_thread and update_thread.is_alive():
        stop_event.set()
        update_thread.join(timeout=5)
    
    # Start a new thread
    start_update_thread()
    
    return jsonify({'status': 'success', 'message': 'Data collection started'})

@app.route('/api/stop-simulation', methods=['POST'])
def stop_simulation():
    """Stop the data collection thread"""
    global update_thread, stop_event
    
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
    # Start the update thread when the application starts
    start_update_thread()
    
    try:
        # Run the Flask app
        print("Starting Flask server on port 5000...")
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
