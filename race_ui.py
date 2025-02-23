from flask import Flask, jsonify
from flask_cors import CORS
from apex_timing_parser import ApexTimingParser
import threading
import time

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variable to store race data
race_data = {
    'teams': [],
    'session_info': {},
    'last_update': None
}

# Global parser instance
parser = ApexTimingParser()

def update_race_data():
    """Background thread to update race data"""
    while True:
        try:
            grid_html, dyna_html = parser.get_page_content("https://www.apex-timing.com/live-timing/karting-mariembourg/index.html")
            if grid_html and dyna_html:
                df = parser.parse_grid_data(grid_html)
                if not df.empty:
                    race_data['teams'] = df.to_dict('records')
                    race_data['session_info'] = parser.parse_dyna_info(dyna_html)
                    race_data['last_update'] = time.strftime('%H:%M:%S')
                    print(f"Data updated at {race_data['last_update']}")
        except Exception as e:
            print(f"Error updating race data: {e}")
        time.sleep(5)  # Update every 5 seconds

@app.route('/api/race-data')
def get_race_data():
    return jsonify(race_data)

if __name__ == '__main__':
    # Start the background update thread
    update_thread = threading.Thread(target=update_race_data, daemon=True)
    update_thread.start()
    
    print("Starting Flask server on port 5000...")
    # Run the Flask app on port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)