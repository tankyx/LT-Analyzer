# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LT-Analyzer is a real-time race timing analysis system for karting/racing events that receives live timing data from Apex Timing WebSocket connections and provides real-time analytics through a web dashboard.

## Architecture

The system consists of three main components:

1. **Data Collection Layer** (`apex_timing_websocket.py`): WebSocket-based parser that receives live race data
2. **API Layer** (`race_ui.py`): Flask-SocketIO server that processes data and serves it to the frontend via WebSocket
3. **Frontend** (`racing-analyzer/`): Next.js React dashboard for visualizing race progress with real-time WebSocket updates

Data flows: Apex Timing WebSocket → Parser → SQLite DB → Flask-SocketIO → WebSocket → Next.js Frontend

## Common Commands

### Development
```bash
# Frontend development
cd racing-analyzer
npm install              # Install dependencies
npm run dev              # Start development server with Turbopack (http://localhost:3000)
npm run build            # Build for production
npm run lint             # Run ESLint checks

# Backend development (without pm2)
python race_ui.py        # Start Flask API server (port 5000)
python apex_timing_websocket.py  # Start WebSocket data collection
python race_simulator.py # Run with simulated test data
```

### Production Deployment (with pm2)
```bash
# Start backend
pm2 start start-selenium.sh --name "lt-analyzer-backend"

# Start frontend  
pm2 start start-frontend.sh --name "lt-analyzer-frontend"

# Management
pm2 status               # Check process status
pm2 logs                 # View logs
pm2 restart all          # Restart both services
```

Note: `start-selenium.sh` activates the Python virtual environment (`racing-venv`) and runs `race_ui.py` with WebSocket backend support.

## Key API Endpoints

- `GET /api/race-data` - Get current race standings and timing data (still available for compatibility)
- `POST /api/update-monitoring` - Set teams to monitor
- `POST /api/start-simulation` - Start data collection
- `POST /api/stop-simulation` - Stop data collection
- `POST /api/update-pit-config` - Configure pit stop detection settings
- `GET /api/parser-status` - Check parser status

## WebSocket Events

### Client → Server:
- `connect` - Initial connection, server sends full race data

### Server → Client:
- `race_data_update` - Full race data update (on connect)
- `teams_update` - Team positions and status updates
- `gap_update` - Delta time updates for monitored teams
- `session_update` - Session info changes (flags, status)
- `monitoring_update` - When monitored teams change
- `pit_config_update` - Pit stop configuration changes

## Important Implementation Details

1. **Real-time Updates**: The frontend receives real-time updates via WebSocket connection. No more polling!

2. **Pit Stop Detection**: The system detects pit stops by monitoring lap time thresholds and position changes. Configuration is done through `PitStopConfig` component.

3. **Gap Calculations**: Two types of gaps are calculated:
   - Raw gap: Actual time difference between teams
   - Adjusted gap: Accounts for remaining pit stops (configurable per team)

4. **Class Filtering**: Supports filtering by racing class (Class 1/2) in the dashboard

5. **Database**: Uses SQLite (`race_data.db`) to store historical race data and lap times

6. **WebSocket**: The WebSocket parser runs asynchronously and handles real-time data updates from the Apex Timing servers

7. **Virtual Environment**: Backend runs in a Python virtual environment (`racing-venv`) which must be activated before running Python scripts

## Technology Stack

- **Backend**: Python, Flask-SocketIO, WebSockets, BeautifulSoup4, SQLite, Pandas, eventlet
- **Frontend**: Next.js 15, TypeScript, React 19, Tailwind CSS, Recharts, Socket.IO-client
- **Production**: pm2 process manager for both frontend and backend services