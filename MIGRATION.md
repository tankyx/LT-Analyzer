# LT-Analyzer Migration Guide: pm2 to Docker with Multi-Team Support

## Overview
This guide documents the migration from the current pm2-based deployment to a containerized Docker setup with multi-team/multi-user support.

## Current Architecture (Updated)
- **Process Management**: pm2 managing 2 processes
  - `lt-analyzer-backend`: Flask-SocketIO API with WebSocket parser (port 5000)
  - `lt-analyzer-frontend`: Next.js application (port 3000)
- **Data Storage**: Single SQLite database (`race_data.db`)
- **Real-time Updates**: WebSocket connections via Socket.IO
- **User Model**: Single-user system, no authentication

## Recent Changes Implemented
- **WebSocket Integration**: Replaced polling with real-time WebSocket updates
- **Frontend Status Display**: Fixed status rendering to show "On Track" when received
- **Track Switching**: Added automatic race data reset when changing tracks
- **Connection Management**: Implemented auto-reconnection with exponential backoff

## Target Architecture
- **Container Orchestration**: Docker Compose
- **Services**:
  - Backend API container (Flask-SocketIO + WebSocket parser)
  - Frontend container (Next.js with Socket.IO client)
  - PostgreSQL database (team data, user auth)
  - Redis (session management, WebSocket pub/sub)
  - Nginx (reverse proxy, WebSocket support)
- **Multi-Team Support**: Data isolation with shared resources (no tiers)

## Pre-Migration Checklist
- [ ] Backup current `race_data.db`
- [ ] Document current pm2 environment variables
- [ ] Test Docker installation on VPS
- [ ] Verify port availability
- [ ] Create rollback plan

## Migration Steps

### Phase 1: Database Preparation
```bash
# Backup existing data
cp race_data.db race_data.db.backup

# Run migration script to add team tables
python migrate_database.py

# Extract track data to shared read-only table
python extract_tracks.py  # Creates shared tracks reference
```

### Phase 2: Build Docker Images
```bash
# Build backend image
docker build -f Dockerfile.backend -t lt-analyzer-backend .

# Build frontend image
docker build -f Dockerfile.frontend -t lt-analyzer-frontend .
```

### Phase 3: Test Alongside pm2
```bash
# Start Docker containers on alternate ports
docker-compose -f docker-compose.test.yml up -d

# Verify functionality
curl http://localhost:5001/api/parser-status
curl http://localhost:3001
```

### Phase 4: Data Migration
```bash
# Export data from SQLite
python export_race_data.py

# Import into PostgreSQL with team assignments
docker exec -it lt-analyzer-postgres psql -U ltanalyzer -c "\i /migrations/import_teams.sql"
```

### Phase 5: Switch Over
```bash
# Stop pm2 processes
pm2 stop lt-analyzer-backend lt-analyzer-frontend
pm2 save

# Start production Docker setup
docker-compose up -d

# Monitor logs
docker-compose logs -f

# Verify WebSocket connections
docker exec lt-analyzer-backend python -c "import socketio; print('SocketIO ready')"
```

### Phase 6: Cleanup
```bash
# After verification (recommend 1 week)
pm2 delete all
pm2 unstartup

# Remove old virtual environment (optional)
# rm -rf racing-venv
```

## Rollback Procedure
If issues arise during migration:

```bash
# Stop Docker containers
docker-compose down

# Restore database
cp race_data.db.backup race_data.db

# Restart pm2
pm2 restart all
```

## Post-Migration Tasks
1. Update DNS/proxy settings if needed
2. Configure automated backups for PostgreSQL
3. Set up monitoring for Docker containers
4. Update documentation for team
5. Train users on new authentication system
6. Migrate WebSocket connection handling to Redis pub/sub for multi-instance support
7. Update nginx configuration for WebSocket proxying:
   ```nginx
   location /socket.io/ {
       proxy_pass http://backend:5000/socket.io/;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

## Team Data Isolation

### How Docker Enables Multi-Team Support

1. **Database Isolation**:
   - Single PostgreSQL instance with team_id column in user-generated tables
   - Shared read-only track database accessible to all teams
   - Track data structure:
     ```sql
     tracks (shared, read-only):
     - track_id, track_name, location, length, configuration
     
     race_data (team-specific):
     - race_id, team_id, track_id, race_date, lap_times, etc.
     ```
   - All queries filtered by team_id from JWT token (except tracks table)
   - Row-level security enforced at application level

2. **Multi-Tenant Backend**:
   - Single backend container handling all teams
   - Modified `apex_timing_parser.py` to manage WebSocket connections to race sources
   - One thread per unique race WebSocket URL (shared across teams watching same race)
   - Team-specific data filtering on top of shared race data

3. **WebSocket Management Architecture (Current Implementation)**:
   - **Race Data Collection**: ApexTimingWebSocketParser connects to Apex Timing
     - Parser runs in separate thread managed by Flask app
     - Real-time data parsing from Apex Timing WebSocket
     - Updates stored in global race_data dictionary
   - **Backend-to-Frontend Communication**: Flask-SocketIO broadcasts updates
     - Socket events: race_data_update, teams_update, gap_update, session_update
     - Automatic client room management with 'race_updates' room
     - Connection status tracking with reconnection support
   - **Data Flow**:
     ```
     Apex Timing WS → WebSocket Parser → race_data → Flask-SocketIO → Frontend
                                           ↓
                                    SQLite Database
     ```
   - **Recent Improvements**:
     - Status persistence: Frontend shows "On Track" when received from server
     - Track switching: Automatic race data reset via /api/reset-race-data
     - WebSocket callbacks: Modular event handling in frontend

4. **API & Frontend Modifications (Completed)**:
   - **Backend Changes**:
     - ✅ Replaced polling with Flask-SocketIO WebSocket server
     - ✅ Added differential updates (teams_update, gap_update events)
     - ✅ Implemented /api/reset-race-data endpoint for track changes
     - ✅ WebSocket event emission on data changes
   - **Frontend Changes**:
     - ✅ Removed polling logic from RaceDashboard
     - ✅ Created WebSocketService with auto-reconnect
     - ✅ Fixed status rendering (Status !== undefined check)
     - ✅ Added race data reset on track selection
     - ✅ Real-time updates without API polling

5. **Storage Isolation**:
   - Volume mounts: `/data/teams/` with subdirectories per team
   - Scraped data saved to `/data/teams/{team_id}/`
   - Team-specific configuration files

### Docker Volume Structure
```
/var/lib/docker/volumes/
├── ltanalyzer_teams/
│   ├── team_1/
│   │   ├── monitoring_config.json  # Which cars to track
│   │   ├── alerts.json            # Team-specific alerts
│   │   └── logs/
│   ├── team_2/
│   │   ├── monitoring_config.json
│   │   ├── alerts.json
│   │   └── logs/
│   └── team_3/
│       └── ...
└── ltanalyzer_shared/
    ├── race_cache/               # Shared race data from WebSockets
    ├── tracks_database/          # Read-only track configurations
    ├── static_assets/
    └── system_configs/
```

### Data Sharing Example
```
Race at Apex Timing URL: https://apex.com/race/123
- Team A: Monitors cars [1, 5, 7] with pit stop alerts
- Team B: Monitors cars [2, 5, 9] with gap tracking
- Team C: Monitors cars [5, 10] with lap time analysis

Backend creates ONE WebSocket connection to apex.com/race/123
- All teams receive updates for their monitored cars
- Each team has private monitoring settings
- Shared data cached, team-specific analytics calculated separately
```

## Environment Variables
```bash
# Current (pm2)
PYTHONUNBUFFERED=1
NODE_ENV=production

# Future (Docker)
DATABASE_URL=postgresql://user:pass@postgres:5432/ltanalyzer
REDIS_URL=redis://redis:6379
JWT_SECRET_KEY=<generated>
MAX_CONCURRENT_SCRAPERS=64  # Total unique race WebSockets
SCRAPER_TIMEOUT=172800  # 48 hours max per scraping session
CACHE_TTL=1  # Redis cache TTL in seconds for race data (1s for high reactivity)
WEBSOCKET_PING_INTERVAL=25  # Socket.IO ping interval
WEBSOCKET_PING_TIMEOUT=60   # Socket.IO timeout
```

## Monitoring & Maintenance

### Health Checks
```bash
# Check all services
docker-compose ps

# Team-specific metrics
docker exec lt-analyzer-backend python check_team_status.py --team-id=1
```

### Backup Strategy
```bash
# Automated daily backups
0 2 * * * /usr/local/bin/backup_team_data.sh
```

## Troubleshooting

### Common Issues
1. **Port Conflicts**: Ensure pm2 processes are stopped
2. **Permission Errors**: Check Docker volume permissions
3. **Memory Issues**: Adjust container limits in docker-compose.yml
4. **WebSocket Connection Issues**: 
   - Check CORS settings in Flask-SocketIO
   - Verify nginx WebSocket proxy headers
   - Test with polling transport first

### Debug Commands
```bash
# View container logs
docker logs lt-analyzer-backend

# Enter container shell
docker exec -it lt-analyzer-backend /bin/bash

# Check WebSocket status
docker exec lt-analyzer-backend python -c "from race_ui import connected_clients; print(f'Connected clients: {len(connected_clients)}')"

# Test WebSocket connection
docker exec lt-analyzer-backend python -m socketio.client -u http://localhost:5000

# Check team isolation
docker exec lt-analyzer-backend python -c "from app import check_team_isolation; check_team_isolation()"
```

### WebSocket-Specific Issues
1. **Client Not Receiving Updates**:
   - Check browser console for Socket.IO errors
   - Verify frontend WebSocketService is connecting to correct URL
   - Check if race_updates room is properly joined

2. **Frequent Disconnections**:
   - Adjust ping_interval and ping_timeout in Flask-SocketIO
   - Check for proxy timeout settings
   - Monitor network stability

3. **Race Data Reset Issues**:
   - Verify /api/reset-race-data endpoint is accessible
   - Check that WebSocket emits race_data_reset event
   - Ensure frontend handles onRaceDataReset callback

## Security Considerations
- All team data encrypted at rest
- JWT tokens expire after 24 hours
- API rate limiting per team
- Audit logs for compliance
- Track database mounted as read-only volume
- Database permissions:
  ```sql
  -- Tracks table: read-only for all application users
  GRANT SELECT ON tracks TO ltanalyzer_app;
  REVOKE INSERT, UPDATE, DELETE ON tracks FROM ltanalyzer_app;
  
  -- Team tables: full access filtered by team_id
  GRANT ALL ON race_data TO ltanalyzer_app;
  ```