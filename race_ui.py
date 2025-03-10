from flask import Flask, jsonify, request
from flask_cors import CORS
from apex_timing_parser import ApexTimingParser
import threading
import time
from collections import deque
from statistics import mean

app = Flask(__name__)
CORS(app)

race_data = {
    'teams': [],
    'session_info': {},
    'last_update': None,
    'my_team': None,
    'monitored_teams': [],
    'delta_times': {},
    'gap_history': {}
}

# Global parser instance
parser = ApexTimingParser()

def calculate_trend(current_gap, previous_gaps):
    """Calculate trend and determine arrow type based on gap change
    Returns: (trend_value, arrow_type)
    trend_value: negative means we're catching up
    arrow_type: 1, 2, or 3 for single, double, triple arrow"""
    # Need at least 2 laps to show a trend
    if len(previous_gaps) < 2:
        return 0, 0
    
    avg_previous = mean(previous_gaps)
    trend = current_gap - avg_previous
    
    if abs(trend) < 0.5:
        arrow = 1
    elif abs(trend) < 1.0:
        arrow = 2
    else:
        arrow = 3
        
    return trend, arrow

def calculate_delta_times(teams, my_team_kart, monitored_karts):
    """Calculate delta times between my team and monitored teams"""
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
        
        # Remove history for karts no longer monitored
        for kart in list(race_data['gap_history'].keys()):
            if kart not in monitored_karts:
                del race_data['gap_history'][kart]
        
        for kart in monitored_karts:
            monitored_team = next((team for team in teams if team['Kart'] == kart), None)
            if monitored_team:
                try:
                    # Calculate gap between monitored team and my team
                    mon_pit_stops = int(monitored_team.get('Pit Stops', '0') or '0')
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
                    
                    # Calculate trends only if we have enough data
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

def update_race_data():
    """Background thread to update race data"""
    while True:
        try:
            grid_html, dyna_html = parser.get_page_content("https://www.apex-timing.com/live-timing/karting-mariembourg/index.html")
            if grid_html and dyna_html:
                df = parser.parse_grid_data(grid_html)
                if not df.empty:
                    teams_data = df.to_dict('records')
                    race_data['teams'] = teams_data
                    race_data['session_info'] = parser.parse_dyna_info(dyna_html)
                    race_data['last_update'] = time.strftime('%H:%M:%S')
                    
                    # Update delta times for monitored teams
                    race_data['delta_times'] = calculate_delta_times(
                        teams_data,
                        race_data['my_team'],
                        race_data['monitored_teams']
                    )
                    
                    print(f"Data updated at {race_data['last_update']}")
        except Exception as e:
            print(f"Error updating race data: {e}")
        time.sleep(1)

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
            'gaps': list(history['gaps']),
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

if __name__ == '__main__':
    try:
        # Start the background update thread
        update_thread = threading.Thread(target=update_race_data, daemon=True)
        update_thread.start()
        
        print("Starting Flask server on port 5000...")
        # Run the Flask app on port 5000
        app.run(host='0.0.0.0', port=5000, debug=True)
    finally:
        # Ensure browser is closed when app exits
        parser.cleanup()
