# LT-Analyzer Project Guide

## Project Overview

LT-Analyzer is a comprehensive racing telemetry analysis system that collects, processes, and displays real-time kart racing data from Apex Timing systems. The project consists of a Python Flask backend for data collection and processing, and a Next.js/React frontend for visualization and analysis.

### Key Features
- Real-time race data collection via WebSocket and browser scraping
- Multi-track support with separate databases per track
- Team-specific data filtering and analysis
- Android overlay API for live position tracking
- Historical data analysis and session management
- WebSocket-based live updates with Socket.IO

## Technology Stack

### Backend
- **Python 3.10-3.12** with Flask framework
- **Flask-SocketIO** for real-time WebSocket communication
- **SQLite** databases for data persistence (separate DB per track)
- **asyncio** for concurrent WebSocket connections
- **pandas** for data manipulation and analysis
- **websockets** library for Apex Timing WebSocket connections
- **BeautifulSoup** for HTML parsing (fallback mode)

### Frontend
- **Next.js 15** with React 19
- **TypeScript** for type safety
- **Tailwind CSS** for styling
- **Socket.IO Client** for real-time updates
- **Jest** with React Testing Library for testing
- **Framer Motion** for animations

### Development Tools
- **Make** for build automation
- **pytest** for backend testing with coverage
- **GitHub Actions** for CI/CD
- **PM2** for production process management

## Project Structure

```
LT-Analyzer/
├── race_ui.py                    # Main Flask backend application
├── apex_timing_websocket.py      # WebSocket parser for Apex Timing
├── multi_track_manager.py        # Manages multiple track parsers
├── database_manager.py          # Track database management
├── wsgi.py                      # WSGI entry point for production
├── migrations/                  # Database migration scripts
├── tests/                       # Backend test suite
│   ├── conftest.py             # Test configuration and fixtures
│   ├── test_api/               # API endpoint tests
│   └── test_websocket/         # WebSocket parser tests
├── racing-analyzer/            # Next.js frontend application
│   ├── app/                    # Next.js app directory
│   │   ├── components/         # React components
│   │   ├── contexts/           # React contexts (AuthContext)
│   │   ├── dashboard/          # Dashboard pages
│   │   ├── login/              # Authentication pages
│   │   ├── team/[teamName]/    # Team-specific pages
│   │   └── services/           # API and WebSocket services
│   ├── __tests__/              # Frontend test suite
│   ├── public/                 # Static assets
│   └── utils/                  # Utility functions
├── scripts/                    # Development and deployment scripts
└── requirements.txt            # Python dependencies (implied)
```

## Build and Development Commands

### Quick Start
```bash
# Install all dependencies and start development
make install
make dev
```

### Development Commands
```bash
# Frontend development
cd racing-analyzer
npm run dev          # Start Next.js dev server (port 3000)
npm run build        # Build for production
npm test            # Run frontend tests
npm run test:watch  # Run tests in watch mode

# Backend development
python race_ui.py   # Start Flask backend (port 5000)

# Testing
make test           # Run all tests
make test-frontend  # Run frontend tests only
make test-backend   # Run backend tests only
make test-coverage  # Run tests with coverage reports

# Production
make build          # Build frontend for production
make start          # Start production servers with PM2
make clean          # Clean build artifacts and caches
```

## Code Style Guidelines

### Python Backend
- Use **type hints** for function parameters and return values
- Follow **PEP 8** naming conventions
- Use **async/await** for asynchronous operations
- Implement proper **error handling** with try-except blocks
- Use **logging** instead of print statements
- Keep functions **focused and small** (single responsibility)

### TypeScript/React Frontend
- Use **functional components** with hooks
- Implement **proper TypeScript types** for all props and state
- Use **Tailwind CSS** classes for styling (avoid inline styles)
- Follow **React best practices** for component structure
- Use **context providers** for global state management
- Implement **proper error boundaries** where appropriate

### Database Conventions
- Use **separate SQLite databases** per track (`race_data_track_{id}.db`)
- Maintain **persistent track configuration** in `tracks.db`
- Use **WAL mode** for better concurrent access
- Implement **proper connection management** with context managers
- Use **parameterized queries** to prevent SQL injection

## Testing Strategy

### Backend Testing
- **Unit tests** for individual functions and parsers
- **Integration tests** for API endpoints
- **WebSocket tests** for real-time communication
- **Mock external dependencies** (databases, WebSocket connections)
- Use **pytest fixtures** for reusable test data
- Aim for **80%+ code coverage**

### Frontend Testing
- **Component tests** for React components
- **Service tests** for API and WebSocket interactions
- **User interaction tests** with React Testing Library
- **Mock external dependencies** (API calls, WebSocket)
- Test **accessibility** and **responsive behavior**

### Running Tests
```bash
# Backend tests with coverage
pytest --cov=. --cov-report=html

# Frontend tests with coverage
npm run test:coverage

# Specific test files
pytest tests/test_api/test_race_endpoints.py
npm test -- RaceDashboard.test.tsx
```

## Parser Modes

The system supports three data collection modes:

1. **Hybrid Mode** (Recommended): Auto-detects WebSocket availability, falls back to browser scraping
2. **WebSocket Mode**: Direct WebSocket connection for lowest latency (~100ms updates)
3. **Playwright Mode**: Traditional browser scraping for maximum compatibility

## WebSocket Integration

### Server Events (Backend → Frontend)
- `race_data_update`: Real-time race data updates
- `team_specific_update`: Team-specific position and gap data
- `track_update`: All teams data for a track
- `session_status`: Active/inactive session status
- `team_room_joined`: Confirmation of team room subscription
- `team_room_error`: Error when joining team room

### Client Events (Frontend → Backend)
- `join_track`: Subscribe to track updates
- `join_team_room`: Subscribe to specific team updates
- `leave_track`: Unsubscribe from track updates
- `leave_team_room`: Unsubscribe from team updates

## Android Overlay API

The system provides a Socket.IO API for Android overlay applications:

### Key Endpoints
- `GET /api/admin/tracks`: List available tracks
- `GET /api/team-data/search`: Search for team names
- `GET /api/tracks/status`: Get track activity status

### Team-Specific Data Format
```json
{
  "position": 3,
  "gap_to_leader": "+12.345",
  "gap_to_front": "+2.156", 
  "gap_to_behind": "-5.234",
  "last_lap": "1:02.345",
  "best_lap": "1:01.234",
  "pit_stops": 2,
  "status": "On Track"
}
```

## Security Considerations

- **CORS configuration** restricts origins to specific domains
- **Session management** with secure secret keys
- **Input validation** for all API endpoints
- **SQL injection prevention** with parameterized queries
- **WebSocket authentication** through room-based access control
- **Rate limiting** considerations for production deployment

## Deployment Notes

### Production Setup
- Use **PM2** for process management (configured in Makefile)
- **Nginx** reverse proxy for SSL termination and static file serving
- **Environment variables** for sensitive configuration
- **Log rotation** for long-running processes
- **Database backups** for historical data preservation

### Performance Optimization
- **WebSocket connections** are more efficient than browser scraping
- **Separate databases** per track prevent lock contention
- **Async processing** for non-blocking data collection
- **Connection pooling** for database operations
- **Caching strategies** for frequently accessed data

## Common Development Tasks

### Adding a New Parser Mode
1. Create parser class in appropriate module
2. Implement standard parser interface methods
3. Add mode selection logic to `race_ui.py`
4. Update frontend UI for mode selection
5. Add comprehensive tests

### Adding New API Endpoints
1. Define route in `race_ui.py`
2. Implement proper error handling
3. Add input validation
4. Create corresponding tests
5. Update frontend services if needed

### Modifying Database Schema
1. Create migration script in `migrations/` directory
2. Test migration on development database
3. Update database manager classes
4. Update affected API endpoints
5. Add tests for schema changes

## Troubleshooting

### Common Issues
- **WebSocket connection failures**: Check CORS configuration and network connectivity
- **Database lock errors**: Ensure proper connection management and WAL mode
- **High memory usage**: Consider switching from Playwright to WebSocket mode
- **Test failures**: Check mock configurations and fixture setup
- **Build errors**: Verify Node.js and Python version compatibility

### Debug Mode
- Enable **Flask debug mode** for detailed error messages
- Use **pytest verbose mode** (`-v` or `-vv`) for test debugging
- Check **log files** in project root for runtime issues
- Use **browser DevTools** for frontend debugging
- Monitor **WebSocket messages** in browser network tab

This guide should be updated as the project evolves and new features are added.