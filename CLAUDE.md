# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LT-Analyzer is a real-time race timing analysis system for karting/racing events that simultaneously monitors multiple tracks, receives live timing data from Apex Timing WebSocket connections, and provides real-time analytics through a web dashboard.

## Architecture

The system consists of four main components:

1. **Multi-Track Manager** (`multi_track_manager.py`): Manages concurrent monitoring of multiple tracks, each with its own parser and database
2. **Data Collection Layer** (`apex_timing_websocket.py`): WebSocket-based parser that receives live race data from Apex Timing servers
3. **API Layer** (`race_ui.py`): Flask-SocketIO server that broadcasts track-specific updates via Socket.IO rooms
4. **Frontend** (`racing-analyzer/`): Next.js React dashboard with track selector for visualizing race progress with real-time WebSocket updates

**Data Flow:**
```
Apex Timing WebSocket → TrackSpecificParser → Track Database (race_data_track_N.db)
                                                         ↓
                                    Socket.IO Room (track_N) → Frontend (track selector)
```

**Key Architectural Features:**
- **Automatic Collection**: System auto-starts monitoring all configured tracks on backend startup
- **Track Isolation**: Each track has its own database and Socket.IO room for independent data streams
- **Session Monitoring**: Detects and broadcasts when tracks have active/inactive racing sessions
- **Real-time Switching**: Frontend can switch between tracks and receive only that track's updates

## Project Structure

```
LT-Analyzer/
├── apex_timing_websocket.py    # Base WebSocket parser for live race data
├── multi_track_manager.py      # Multi-track concurrent monitoring manager
├── race_ui.py                  # Flask-SocketIO API server with room-based broadcasting
├── database_manager.py         # Database utilities and management
├── initialize_databases.py     # Database initialization script
├── race_data_track_1.db        # Track 1 database (Mariembourg)
├── race_data_track_2.db        # Track 2 database (Spa)
├── race_data_track_3.db        # Track 3 database (RKC)
├── race_data_track_N.db        # ... additional track databases
├── tracks.db                   # Track information and WebSocket URLs (16KB)
├── auth.db                     # User authentication database (24KB)
├── racing-analyzer/            # Next.js frontend application
│   ├── app/
│   │   ├── components/
│   │   │   └── RaceDashboard/ # Main dashboard with track selector
│   │   │       ├── index.tsx  # Main dashboard component with two-column layout
│   │   │       ├── MultiTrackStatus.tsx  # Real-time multi-track status monitor
│   │   │       └── ...        # Other dashboard components
│   │   ├── services/
│   │   │   ├── ApiService.ts      # REST API client
│   │   │   └── WebSocketService.ts # Socket.IO client with room management
│   │   ├── admin/             # Admin panel for tracks and users
│   │   ├── data/              # Data comparison page
│   │   └── dashboard/         # Main dashboard page
├── racing-venv/                # Python virtual environment
├── migrations/                 # Archived database migration scripts
├── scripts/                    # Utility scripts
├── tests/                      # Test suite
├── start-selenium.sh           # Backend startup script (used by pm2)
├── start-frontend.sh           # Frontend startup script (used by pm2)
└── apex_timing_websocket.log   # Current log file with rotation
```

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
```

### Production Deployment (with pm2)
```bash
# Start backend
pm2 start start-selenium.sh --name "lt-analyzer-backend"

# Start frontend
pm2 start start-frontend.sh --name "lt-analyzer-frontend"

# Management
pm2 status               # Check process status
pm2 logs                 # View logs (all services)
pm2 logs lt-analyzer-backend  # View backend logs only
pm2 restart all          # Restart both services
pm2 stop lt-analyzer-backend  # Stop backend
```

Note: `start-selenium.sh` activates the Python virtual environment (`racing-venv`) and runs `race_ui.py` with WebSocket backend support. Multi-track monitoring starts automatically.

### Database Management
```bash
# Wipe all race data and start fresh (while backend is stopped)
pm2 stop lt-analyzer-backend
rm -f race_data*.db
pm2 start lt-analyzer-backend  # Will auto-create fresh databases

# Check database sizes
ls -lh race_data*.db

# Query a specific track's data
sqlite3 race_data_track_1.db "SELECT COUNT(*) FROM lap_times"

# View all tracks
sqlite3 tracks.db "SELECT id, track_name, websocket_url FROM tracks"
```

## Key API Endpoints

### Race Data & Monitoring
- `GET /api/race-data` - Get current race standings and timing data (legacy endpoint, still available)
- `POST /api/update-monitoring` - Set teams to monitor for delta calculations
- `POST /api/update-pit-config` - Configure pit stop detection settings (pit time, required stops)
- `GET /api/parser-status` - Check multi-track parser status
- `GET /api/tracks/status` - Get session status for all tracks (active/inactive, teams count)

### Track Management (Admin)
- `GET /api/admin/tracks` - List all configured tracks with full details (location, length, etc.)
- `POST /api/admin/tracks` - Create new track with WebSocket URL
- `PUT /api/admin/tracks/<id>` - Update track configuration
- `DELETE /api/admin/tracks/<id>` - Delete track

### User Management (Admin)
- `GET /api/admin/users` - List all users
- `POST /api/admin/users` - Create new user
- `PUT /api/admin/users/<id>` - Update user
- `DELETE /api/admin/users/<id>` - Delete user

### Team Data Analysis (/data page)
- `GET /api/team-data/top-teams` - Get top N teams ranked by best lap time
  - Parameters: `track_id`, `limit` (10/20/30)
  - Returns: team name, best lap, avg lap, total laps, sessions count, classes
  - Handles mixed best_lap formats (MM:SS.mmm and raw seconds)
  - Works with/without class prefix ("1 - TEAMNAME" or "TEAMNAME")
- `GET /api/team-data/search` - Search for teams by name (case-insensitive)
  - Parameters: `q` (query string), `track_id`
- `GET /api/team-data/stats` - Get detailed statistics for a specific team
  - Parameters: `team`, `track_id`, optional `session_id`
  - Returns: best lap, avg lap, total laps, sessions, pit stops
- `POST /api/team-data/compare` - Compare statistics for multiple teams
  - Body: `teams[]`, `track_id`, optional `session_id`
  - Returns: comparison data with lap times for charting
- `POST /api/team-data/common-sessions` - Get sessions where all specified teams participated
  - Body: `teams[]`, `track_id`
- `POST /api/team-data/lap-details` - Get detailed lap-by-lap data for teams in a session
  - Body: `teams[]`, `session_id`, `track_id`
  - Returns: lap details and stint information
- `POST /api/team-data/delete-best-lap` - Delete (nullify) a team's best lap time (admin only)
  - Body: `team_name`, `track_id`, `best_lap_time`
  - Sets best_lap field to NULL (preserves record, second-best becomes new best)
  - Requires admin authentication

### Testing & Development
- `POST /api/test/simulate-session/<track_id>` - Simulate active session on a track (for testing)
- `POST /api/test/stop-session/<track_id>` - Stop simulated session on a track

**Note**: Data collection starts automatically on backend startup. No manual start/stop endpoints needed.

## WebSocket Events

### Client → Server:
- `connect` - Initial connection establishment
- `join_track` - Join a track-specific room to receive updates
  - Payload: `{ track_id: number }`
- `leave_track` - Leave a track-specific room
  - Payload: `{ track_id: number }`
- `join_all_tracks` - Join the all_tracks room for multi-track status updates
- `leave_all_tracks` - Leave the all_tracks room
- `join_team_room` - Join a team-specific room for a track to receive team updates
  - Payload: `{ track_id: number, team_name: string }`
  - Validates track and team exist before joining
- `leave_team_room` - Leave a team-specific room
  - Payload: `{ track_id: number, team_name: string }`

### Server → Client:
- `track_update` - Real-time updates for a specific track (sent to track room only)
  - Payload: `{ track_id, track_name, teams, session_id, timestamp }`
- `session_status` - Session active/inactive status for a track (sent to track room)
  - Payload: `{ track_id, track_name, active, message, timestamp }`
- `all_tracks_status` - Status update for all tracks (sent to all_tracks room)
  - Payload: `{ tracks: [{ track_id, track_name, active, last_update, teams_count, is_connected }], timestamp }`
- `team_specific_update` - Real-time updates for a specific team on a track (sent to team room only)
  - Payload: `{ track_id, track_name, team_name, position, kart, status, last_lap, best_lap, total_laps, runtime, gap_to_leader, gap_to_front, gap_to_behind, pit_stops, session_id, timestamp }`
  - Room: `team_track_{track_id}_{team_name}`
- `team_room_joined` - Confirmation of joining team room
  - Payload: `{ track_id, track_name, team_name, room, timestamp }`
- `team_room_left` - Confirmation of leaving team room
  - Payload: `{ track_id, team_name, room, timestamp }`
- `team_room_error` - Error when joining/leaving team room
  - Payload: `{ error, track_id?, track_name?, timestamp }`
- `teams_update` - Team positions and status updates (legacy)
- `gap_update` - Delta time updates for monitored teams
- `session_update` - Session info changes (flags, status)
- `monitoring_update` - When monitored teams change
- `pit_config_update` - Pit stop configuration changes
- `race_data_update` - Full race data update (legacy, on connect)

## Important Implementation Details

1. **Multi-Track Monitoring**:
   - The `MultiTrackManager` automatically monitors all tracks configured in `tracks.db` on backend startup
   - Each track runs its own `TrackSpecificParser` in a concurrent asyncio task
   - Tracks are completely isolated - separate databases, separate Socket.IO rooms, separate sessions

2. **Socket.IO Room Architecture**:
   - Each track has a dedicated room: `track_1`, `track_2`, etc.
   - Frontend joins/leaves rooms when user selects a track in the dropdown
   - Only subscribed clients receive updates for their selected track
   - Backend broadcasts `track_update` events to the appropriate room when new data arrives
   - The `all_tracks` room broadcasts status for all tracks simultaneously
   - Frontend joins `all_tracks` room to display multi-track status panel
   - When any track's session status changes, updates are broadcast to both the track room and all_tracks room

3. **Session Status Monitoring**:
   - Each track parser monitors for data reception in a background thread
   - If no data received for 2 minutes, broadcasts `session_status` with `active: false`
   - When data resumes, broadcasts `session_status` with `active: true`
   - Frontend displays session status indicator and shows alerts for inactive sessions

4. **Automatic Data Collection**:
   - System auto-starts on backend initialization (no manual start required)
   - Continuously monitors all tracks 24/7
   - Data written to disk immediately (minimal memory footprint: ~10KB per track parser)
   - Safe for long-running deployment

5. **Database Architecture**: Uses SQLite with per-track databases:
   - `race_data_track_N.db` - One database per track with race data and lap times
     - Tables: `race_sessions`, `lap_times`, `lap_history`
   - `tracks.db` - Track information and configuration
     - Fields: `id`, `track_name`, `timing_url`, `websocket_url`, `column_mappings` (legacy, optional), `location`, `length_meters`, `description`, `is_active`, `created_at`, `updated_at`
     - Note: `column_mappings` is optional; system primarily uses data-type based detection
   - `auth.db` - User authentication for admin panel
     - Tables: `users`, `sessions`, `login_attempts`

6. **Frontend Dashboard Layout**:
   - **Two-column responsive layout** (stacks on mobile, side-by-side on desktop):
     - **Left column**: Track selector dropdown and My Team selector
     - **Right column**: Multi-Track Status panel showing all tracks simultaneously
   - **Track selector** dropdown to choose which track's detailed data to view
   - **Multi-Track Status panel** (`MultiTrackStatus.tsx`):
     - Real-time status display for all configured tracks
     - Shows active/inactive sessions with visual indicators (green pulsing = active)
     - Displays team counts for active sessions
     - Scrollable list (max height: 400px) when many tracks are configured
     - Click any track to switch to it
   - Automatically joins the selected track's Socket.IO room for detailed data
   - Also joins `all_tracks` room for the multi-track status panel
   - Efficient bandwidth usage: only receives detailed updates for selected track

7. **Pit Stop Detection**: The system detects pit stops by monitoring lap time thresholds and position changes. Configuration is done through `PitStopConfig` component.

8. **Gap Calculations**: Two types of gaps are calculated:
   - Raw gap: Actual time difference between teams
   - Adjusted gap: Accounts for remaining pit stops (configurable per team)

9. **Class Filtering**: Supports filtering by racing class (Class 1/2) in the dashboard

10. **WebSocket Connections**:
    - Each track parser maintains its own WebSocket connection to Apex Timing servers
    - Connections run asynchronously and handle reconnections automatically
    - Multiple connection attempts with different SSL configurations for compatibility

11. **Virtual Environment**: Backend runs in a Python virtual environment (`racing-venv`) which must be activated before running Python scripts manually

12. **Logging**: The WebSocket parser logs to `apex_timing_websocket.log` with automatic log rotation (10MB max, 3 backups)

13. **User Preferences Persistence** (`utils/persistence.ts`):
    - All user preferences saved to browser localStorage (client-side only)
    - Persisted data includes:
      - Selected track ID
      - "My Team" selection
      - Stint planner configuration (per track)
      - Driver names
      - Current driver index
      - Track-specific stint presets
    - Data loads after Next.js SSR hydration to avoid conflicts
    - Survives page refreshes and browser sessions

14. **Stint Planner Presets** (`StintPlanner.tsx`, `persistence.ts`):
    - Create multiple race configurations per track (e.g., "6 Hour Race", "12 Hour Endurance", "24h Race")
    - Each preset stores:
      - Number of stints
      - Min/Max stint times
      - Pit duration
      - Number of drivers
      - Total race time
    - Auto-loads when switching tracks
    - Instantly recalculates stint table when selecting different presets
    - Saved per-browser in localStorage (track-specific)
    - UI in Stint Planner tab with dropdown selector, save/delete buttons

15. **Team-Specific Socket.IO Rooms** (`race_ui.py`, `multi_track_manager.py`):
    - External apps can subscribe to real-time updates for a specific team on a specific track
    - Room naming convention: `team_track_{track_id}_{team_name}`
    - Client emits `join_team_room` with `{ track_id, team_name }`
    - Backend validates track and team exist before allowing join
    - Server emits `team_specific_update` to team room with:
      - Position, kart number, status
      - Last lap, best lap, total laps completed
      - Runtime (total race time for team)
      - Gap to leader, gap to team in front, gap to team behind
      - Pit stops count
      - Session ID and timestamp
    - Updates broadcast automatically whenever race data updates (same frequency as track updates)
    - Test client available: `python test_team_socket.py`
    - Use case: Mobile apps monitoring specific team performance in real-time

16. **Data-Type Based Column Detection** (`apex_timing_websocket.py`):
    - **Layout-Agnostic Design**: System uses HTML `data-type` attributes instead of fixed column indices
    - **Universal Compatibility**: All Apex Timing tracks worldwide use standardized data-type codes
    - **Standard Data-Type Codes**:
      - `sta` = Status (On Track, Pit-in, Pit-out, Finished)
      - `rk` = Position/Rank
      - `no` = Kart Number
      - `dr` = Driver/Team Name
      - `llp` = Last Lap Time
      - `blp` = Best Lap Time
      - `gap` = Gap to Leader
      - `int` = Interval to Car Ahead
      - `otr` = On-Track Runtime
      - `pit` = Pit Stops (handles both count and time formats)
      - `tlp` = Total Laps
      - `s1/s2/s3` = Sector times (skipped)
    - **Priority-Based Detection** (`apex_timing_websocket.py:316-325`, `apex_timing_websocket.py:412-453`):
      1. **Data-type map** (highest priority) - Uses `data-type` HTML attributes
      2. **Custom map** (medium priority) - Legacy `column_mappings` from database
      3. **Text-based map** (fallback) - Auto-detection from column header text
    - **Adaptive to Layout Changes**: Handles different column orders between:
      - Qualifying vs Race sessions
      - Different track configurations
      - Hidden/visible columns (sectors, intervals)
    - **Cell Update Message Format**: Apex Timing sends `r{row}c{col}|type|value` (e.g., `r114c10|ti|17.821`)
      - Cell ID itself is the command (not prefixed with "update")
      - Parser detects and restructures for processing (`multi_track_manager.py:467-475`)
    - **Flexible Pit Stops Handling** (`multi_track_manager.py:559-566`):
      - Detects format: time (`"00:22"`) vs count (`"3"`)
      - Time format (MM:SS): Stored as 0 for count compatibility
      - Count format: Stored as integer
    - **Benefits**:
      - No manual column mapping configuration needed
      - Works with any Apex Timing track out-of-the-box
      - Survives layout changes without code updates
      - Single codebase supports all tracks worldwide

17. **Team Data Analysis (/data page)** (`racing-analyzer/app/data/page.tsx`, `race_ui.py`):
    - **Top Teams Table**: Shows top 10/20/30 teams ranked by best lap time
      - Configurable limit selector
      - Click team to add to comparison (max 2 teams)
      - Visual indicators for selected teams
      - Auto-loads when track or limit changes
    - **Mixed Data Format Support**:
      - Handles both `best_lap` formats: "MM:SS.mmm" (e.g., "1:02.499") and raw seconds (e.g., "58.800")
      - Converts to seconds for proper MIN() comparison in queries
      - Formats output consistently as "M:SS.mmm"
      - Works with/without class prefix: "1 - TEAMNAME" or "TEAMNAME"
    - **Team Comparison Features**:
      - Search teams by name (case-insensitive)
      - View detailed stats: best lap, avg lap, total laps, sessions, pit stops
      - Compare up to 2 teams side-by-side
      - Common sessions detection (sessions where both teams participated)
      - Lap-by-lap comparison charts and tables
      - Stint analysis with pit stop detection
      - 10-lap rolling average charts
    - **Delete Best Lap (Admin Only)** (`race_ui.py:3097-3167`):
      - Trash icon (🗑️) next to each team's best lap in top teams table
      - Only visible to users with `role === 'admin'`
      - Confirmation dialog before deletion
      - Nullifies `best_lap` field (sets to NULL) instead of deleting record
      - Preserves full data history for audit trail
      - Second-best lap automatically becomes new best lap on next query
      - Use case: Remove outlier lap times from track cuts or data errors
      - Endpoint: `POST /api/team-data/delete-best-lap` (requires admin auth)

## Multi-Track System Flow

### Backend Startup Sequence:
1. Flask-SocketIO server starts on port 5000
2. `MultiTrackManager` initializes
3. Loads all tracks from `tracks.db` with non-empty `websocket_url`
4. For each track:
   - Initializes track-specific database (`race_data_track_N.db`)
   - Creates `TrackSpecificParser` instance with track ID, name, and database path
   - Starts asyncio task to connect to track's WebSocket
   - Starts background thread for session monitoring (checks every 30 seconds)
5. All parsers run concurrently, independently monitoring their tracks

### Data Collection Flow:
1. Track parser receives WebSocket message from Apex Timing
2. Parses HTML table data into DataFrame
3. Stores data in track-specific database (`lap_times`, `lap_history` tables)
4. Updates `last_data_time` timestamp
5. Emits `track_update` event to Socket.IO room `track_N`
6. Only clients subscribed to `track_N` receive the update

### Session Monitoring Flow:
1. Background thread wakes up every 30 seconds
2. Checks time since `last_data_time`
3. If no data received for 2+ minutes:
   - Emits `session_status` with `active: false` to track's room
   - Logs "Session inactive" message
4. When data resumes:
   - Emits `session_status` with `active: true` to track's room
   - Logs "Session active" message
5. Only emits when status changes (prevents spam)

### Frontend Track Switching:
1. User selects track from dropdown (or clicks a track in Multi-Track Status panel)
2. Frontend calls `webSocketService.joinTrack(trackId)`
3. If already subscribed to another track, automatically leaves old room
4. Emits `join_track` event to server with `{ track_id: N }`
5. Server adds client to `track_N` room
6. Client starts receiving `track_update` and `session_status` events for that track only

### Multi-Track Status Updates:
1. Frontend joins `all_tracks` room on dashboard mount
2. Backend monitors all tracks and tracks session status changes
3. When any track's session status changes (active/inactive):
   - Backend broadcasts `all_tracks_status` to the `all_tracks` room
   - Frontend receives update and refreshes Multi-Track Status panel
4. Updates show in real-time without page refresh

## Testing Without Live Data

The system includes test endpoints to simulate active sessions without requiring real Apex Timing WebSocket data:

### Simulate Active Session:
```bash
# Activate a track session
curl -X POST http://localhost:5000/api/test/simulate-session/<track_id>

# Examples:
curl -X POST http://localhost:5000/api/test/simulate-session/1  # Mariembourg
curl -X POST http://localhost:5000/api/test/simulate-session/2  # Spa

# Activate multiple tracks
for i in {1..5}; do curl -X POST http://localhost:5000/api/test/simulate-session/$i; done
```

### Stop Simulated Session:
```bash
# Deactivate a track session
curl -X POST http://localhost:5000/api/test/stop-session/<track_id>

# Example:
curl -X POST http://localhost:5000/api/test/stop-session/1
```

**What happens:**
- The track's `last_data_time` is updated and `session_active_status` is set
- `session_status` event is broadcast to the track's room
- `all_tracks_status` event is broadcast to the `all_tracks` room
- Frontend Multi-Track Status panel updates in real-time (green indicator appears/disappears)
- Useful for testing the UI without waiting for actual race sessions

## Troubleshooting

### No data appearing for a track:
1. Check if track has active session: Look for green indicator in Multi-Track Status panel
2. Use test endpoints to simulate a session: `curl -X POST http://localhost:5000/api/test/simulate-session/1`
3. Verify WebSocket connection: `pm2 logs lt-analyzer-backend | grep "track N"`
4. Check if track is configured: `sqlite3 tracks.db "SELECT * FROM tracks WHERE id=N"`
5. Verify database is being written: `sqlite3 race_data_track_N.db "SELECT COUNT(*) FROM lap_times"`

### Session status stuck on "No active session":
- This is normal if there's no race happening at that track
- Apex Timing only sends data when a session is active
- Check the Multi-Track Status panel - gray indicators mean no active session
- Try selecting a different track that may have an active session (green indicator)
- Use test endpoints to simulate sessions for development/testing

### Frontend not receiving updates:
1. Check WebSocket connection status (should show "connected")
2. Verify you've selected a track in the dropdown or Multi-Track Status panel
3. Check Multi-Track Status panel shows the track with a green indicator (active session)
4. Check browser console for Socket.IO errors
5. Verify backend is running: `pm2 status`
6. Verify `all_tracks_status` events are being received (check browser console)

### Database growing too large:
- Each track database grows with race data over time
- To reset: Stop backend, delete `race_data_track_N.db`, restart backend
- To reset all: `pm2 stop lt-analyzer-backend && rm -f race_data*.db && pm2 start lt-analyzer-backend`

### Backend memory issues:
- Each parser uses ~10KB in-memory
- Data is written to disk immediately, not cached in memory
- If issues persist, check for database lock issues or disk space

## Technology Stack

- **Backend**: Python, Flask-SocketIO, WebSockets, BeautifulSoup4, SQLite, Pandas, eventlet
- **Frontend**: Next.js 15, TypeScript, React 19, Tailwind CSS, Recharts, Socket.IO-client
- **Production**: pm2 process manager for both frontend and backend services