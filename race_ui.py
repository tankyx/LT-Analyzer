from flask import Flask, render_template, jsonify
from apex_timing_parser import ApexTimingParser
import threading
import time
import json

app = Flask(__name__)

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
        except Exception as e:
            print(f"Error updating race data: {e}")
        time.sleep(5)  # Update every 5 seconds

# Create templates/index.html with this content
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Race Analysis</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/vue@2.6.14"></script>
    <style>
        .alert { background-color: #f8d7da; color: #721c24; padding: 1rem; margin: 1rem 0; border-radius: 0.25rem; }
        .gaining { color: green; }
        .losing { color: red; }
    </style>
</head>
<body class="bg-gray-100">
    <div id="app" class="container mx-auto px-4 py-8">
        <div class="bg-white shadow-lg rounded-lg p-6 mb-6">
            <h1 class="text-2xl font-bold mb-4">Race Analysis</h1>
            
            <!-- Team Selection -->
            <div class="grid grid-cols-2 gap-4 mb-6">
                <div>
                    <label class="block text-sm font-medium text-gray-700">My Team</label>
                    <select v-model="myTeam" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm">
                        <option value="">Select Team</option>
                        <option v-for="team in teams" :value="team.Kart">
                            {{ team.Team }} (Kart #{{ team.Kart }})
                        </option>
                    </select>
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">Teams to Monitor</label>
                    <select v-model="monitoredTeams" multiple class="mt-1 block w-full rounded-md border-gray-300 shadow-sm">
                        <option v-for="team in teams" :value="team.Kart">
                            {{ team.Team }} (Kart #{{ team.Kart }})
                        </option>
                    </select>
                </div>
            </div>

            <!-- Session Info -->
            <div class="bg-blue-50 p-4 rounded-lg mb-6">
                <h2 class="font-semibold">Session Information</h2>
                <p>{{ sessionInfo.dyn1 }}</p>
                <p class="text-sm text-gray-600">Last Update: {{ lastUpdate }}</p>
            </div>

            <!-- Alerts -->
            <div v-if="alerts.length > 0" class="mb-6">
                <div v-for="alert in alerts" :key="alert.id" class="alert">
                    {{ alert.message }}
                </div>
            </div>

            <!-- Main Data Display -->
            <div class="grid grid-cols-2 gap-4">
                <!-- Direct Competitors -->
                <div class="bg-white p-4 rounded-lg shadow">
                    <h2 class="font-bold mb-2">Direct Competitors</h2>
                    <div v-for="competitor in directCompetitors" :key="competitor.Kart" 
                         class="border-b py-2">
                        <div class="flex justify-between">
                            <span>{{ competitor.Team }}</span>
                            <span>Gap: {{ calculateRealGap(competitor) }}s</span>
                        </div>
                        <div class="text-sm text-gray-600">
                            Last Lap: {{ competitor['Last Lap'] }} | 
                            Pits: {{ competitor['Pit Stops'] }}
                        </div>
                    </div>
                </div>

                <!-- Class Pace Analysis -->
                <div class="bg-white p-4 rounded-lg shadow">
                    <h2 class="font-bold mb-2">Class Pace Analysis</h2>
                    <table class="w-full">
                        <thead>
                            <tr class="text-left">
                                <th>Team</th>
                                <th>Last 5 Avg</th>
                                <th>Trend</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="team in classCompetitors" :key="team.Kart">
                                <td>{{ team.Team }}</td>
                                <td>{{ team.LastLapAvg }}</td>
                                <td :class="team.trend > 0 ? 'gaining' : 'losing'">
                                    {{ team.trend > 0 ? '↑' : '↓' }}
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        new Vue({
            el: '#app',
            data: {
                teams: [],
                sessionInfo: {},
                lastUpdate: '',
                myTeam: '',
                monitoredTeams: [],
                alerts: []
            },
            computed: {
                directCompetitors() {
                    if (!this.myTeam) return [];
                    const myTeamData = this.teams.find(t => t.Kart === this.myTeam);
                    if (!myTeamData) return [];
                    
                    const myClass = myTeamData.Team.charAt(0);
                    const myPos = parseInt(myTeamData.Position);
                    
                    return this.teams.filter(team => 
                        team.Team.charAt(0) === myClass &&
                        Math.abs(parseInt(team.Position) - myPos) <= 1 &&
                        team.Kart !== this.myTeam
                    );
                },
                classCompetitors() {
                    if (!this.myTeam) return [];
                    const myTeamData = this.teams.find(t => t.Kart === this.myTeam);
                    if (!myTeamData) return [];
                    
                    const myClass = myTeamData.Team.charAt(0);
                    return this.teams
                        .filter(team => team.Team.charAt(0) === myClass)
                        .map(team => ({
                            ...team,
                            LastLapAvg: team['Last Lap'],
                            trend: Math.random() > 0.5 ? 1 : -1  // This should be calculated from actual data
                        }))
                        .sort((a, b) => a.LastLapAvg - b.LastLapAvg);
                }
            },
            methods: {
                calculateRealGap(competitor) {
                    const PIT_TIME = 150; // 2min30sec in seconds
                    const myTeamData = this.teams.find(t => t.Kart === this.myTeam);
                    if (!myTeamData) return 0;
                    
                    const pitDiff = parseInt(competitor['Pit Stops']) - parseInt(myTeamData['Pit Stops']);
                    const baseGap = parseFloat(competitor.Gap || 0);
                    return (baseGap + (pitDiff * PIT_TIME)).toFixed(1);
                },
                updateData() {
                    fetch('/api/race-data')
                        .then(response => response.json())
                        .then(data => {
                            this.teams = data.teams;
                            this.sessionInfo = data.session_info;
                            this.lastUpdate = data.last_update;
                            
                            // Check for pit stops
                            this.checkPitStops();
                        });
                },
                checkPitStops() {
                    // Monitor pit stops for selected teams
                    this.monitoredTeams.forEach(kartNum => {
                        const team = this.teams.find(t => t.Kart === kartNum);
                        if (team && team['Pit Stops'] > (team.lastPitCount || 0)) {
                            this.alerts.push({
                                id: Date.now(),
                                message: `${team.Team} is pitting!`
                            });
                            team.lastPitCount = team['Pit Stops'];
                        }
                    });
                }
            },
            mounted() {
                this.updateData();
                setInterval(this.updateData, 5000);
            }
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return INDEX_HTML

@app.route('/api/race-data')
def get_race_data():
    return jsonify(race_data)

if __name__ == '__main__':
    # Start the background update thread
    update_thread = threading.Thread(target=update_race_data, daemon=True)
    update_thread.start()
    
    # Run the Flask app
    app.run(debug=True)