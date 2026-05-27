# LT-Analyzer

Real-time race-timing analysis for karting and endurance events. Multi-track
WebSocket scraper + Next.js dashboard for live standings, head-to-head
deltas, kart-fairness analytics, and stint planning. Deployed at
**https://kart.krranalyser.fr**.

---

## What it does

- Connects to multiple [Apex Timing](https://www.apex-timing.com/) live-timing
  WebSocket feeds in parallel (currently 11 tracks: Mariembourg, Spa, RKC,
  Solokart, South Garda, Ostricourt, Ouest Karting Essay, Kartland, KLL
  Douvrin, Eupen, Metz).
- Persists per-lap data, session metadata, and team statistics to per-track
  SQLite databases.
- Streams live updates over Socket.IO to the Next.js dashboard.
- Computes head-to-head gap deltas, adjusted gaps accounting for required
  pit stops, and tracks team progress over a race.
- Cross-track team profile: search a driver/team and see their history at
  every venue.
- Stint planner with named per-track presets, driver rotation, and live
  in-race timer.
- Fleet Tracker: a per-user pit-lane kanban for endurance races that tracks
  which physical kart each team is on (the number plate follows the team, so
  machine identity is supplied by the operator), ranks the fleet by inferred
  pace, and flags fast/slow karts entering the pits.
- Driver-level analytics: variance-deficit fairness test for the kart-draw
  question, per-driver best-pace leaderboard, alias merging for drivers
  who race under multiple team names.
- Self-service registration with email verification (Brevo), password
  reset, Cloudflare Turnstile, audit log, GDPR self-export/self-delete.

## Quick start

### Development setup

Requires Python 3.11+, Node 20+, and SQLite 3.35+.

```bash
# 1. Backend
git clone https://github.com/tankyx/LT-Analyzer.git
cd LT-Analyzer
python -m venv racing-venv
source racing-venv/bin/activate
pip install -r requirements.txt

# 2. Bootstrap empty DBs and the first admin user
cp .env.example .env
# edit .env: set FLASK_SECRET_KEY (`python -c "import secrets;print(secrets.token_hex(32))"`),
# ADMIN_USERNAME, ADMIN_PASSWORD (>=12 chars), CORS_ORIGINS
python initialize_databases.py
python scripts/migrate_phase1_auth.py
python scripts/migrate_phase2_prefs.py

# 3. Frontend
cd racing-analyzer
npm install
cp ../.env.example .env.local   # adjust NEXT_PUBLIC_API_URL / WS_URL for local dev

# 4. Run
cd ..
python race_ui.py                  # backend on :5000
# in another shell:
cd racing-analyzer && npm run dev  # frontend on :3000
```

Open http://localhost:3000 and log in with the admin credentials you set.

### Adding a track

Tracks live in `tracks.db`. The simplest way to add one is via the
admin UI at `/admin` → Tracks tab, or via SQL:

```bash
sqlite3 tracks.db "INSERT INTO tracks (track_name, location, length_meters, timing_url, websocket_url, is_active) VALUES ('My Track', 'Town, Country', 1200, 'https://www.apex-timing.com/...', 'ws://www.apex-timing.com:8585/', 1);"
# restart the backend so MultiTrackManager picks up the new entry
pm2 restart lt-analyzer-backend
```

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full picture.
Short version:

```
Apex Timing WS  →  TrackSpecificParser  →  race_data_track_N.db
                          ↓
                  MultiTrackManager
                          ↓
                  Flask-SocketIO  ⇄  Socket.IO rooms (track_N, all_tracks,
                                                       user_prefs_N)
                          ↓
                  Next.js dashboard
```

Backend is a single Flask process running `async_mode='threading'` under
Werkzeug. One asyncio loop in a background thread runs all 11 track
scrapers concurrently. Writes go straight to per-track SQLite DBs (WAL
mode, separate file per track).

## Configuration

Backend reads from `.env` (loaded by the Python process); frontend reads
from `racing-analyzer/.env.production` at build time. See
[`.env.example`](.env.example) for every supported variable and safe
defaults.

Most-load-bearing vars:

| Var | Purpose |
|---|---|
| `FLASK_SECRET_KEY` | session cookie signing, must be stable across restarts |
| `CORS_ORIGINS` | comma-separated whitelist for HTTP + SocketIO |
| `BREVO_API_KEY` | transactional email; empty → spool to `/tmp/lt-mail` (dev) |
| `TURNSTILE_SECRET_KEY` | Cloudflare anti-abuse; empty → soft-pass (dev) |
| `REGISTRATION_OPEN` | `false` = invite-code required; `true` = public sign-up |
| `SESSION_COOKIE_SECURE` | `true` in production (HTTPS); `false` only on `http://localhost` |
| `ENABLE_TEST_ENDPOINTS` | enables `/api/test/simulate-session/*`; **must be `false` in prod** |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | frontend Turnstile widget |
| `NEXT_PUBLIC_INVITE_REQUIRED` | shows the invite-code field on `/register` |

## Production deployment

Single VPS, two pm2 processes + a pm2 module. See
[`docs/DEPLOY.md`](docs/DEPLOY.md) for the full runbook (migrations,
rebuilds, log rotation, rollback). At a glance:

```bash
# Backend
pm2 start start-selenium.sh --name lt-analyzer-backend

# Frontend (after `npm run build`)
pm2 start start-frontend.sh --name lt-analyzer-frontend

# Log rotation
pm2 install pm2-logrotate
pm2 set pm2-logrotate:max_size 50M
pm2 set pm2-logrotate:retain 7
```

nginx terminates TLS and proxies `/` to `:3000` (Next.js) and
`/api/` + `/socket.io/` to `:5000` (Flask).

## API reference

REST + WebSocket events documented in [`docs/API.md`](docs/API.md).

## Testing

```bash
# Backend
source racing-venv/bin/activate
pytest --no-cov                           # all
pytest tests/test_auth -m unit            # unit tests only
pytest tests/test_phase2 -k user_prefs    # subset

# Frontend
cd racing-analyzer
npm test                                   # all
npm test -- --testPathPatterns=auth        # subset
```

Test layout, fixtures, and how to add new tests are in
[`TESTING.md`](TESTING.md).

GitHub Actions runs the suites + a Next.js production build on every
push to `main`/`develop` and on PRs ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

## Project structure

```
LT-Analyzer/
├── race_ui.py                  # Flask + Socket.IO app, all HTTP/WS handlers
├── multi_track_manager.py      # MultiTrackManager + per-track parsers
├── apex_timing_websocket.py    # base WebSocket parser
├── database_manager.py         # tracks.db helpers
├── email_service.py            # Brevo + Null senders (Phase 1)
├── turnstile.py                # Cloudflare verification (Phase 1)
├── initialize_databases.py     # one-shot DB bootstrap
├── wsgi.py                     # gunicorn entry point (Phase 3 future)
├── requirements.txt
├── start-selenium.sh           # pm2 backend launcher
├── start-frontend.sh           # pm2 frontend launcher
├── auth.db                     # users, sessions, prefs, audit, invites
├── tracks.db                   # track configurations
├── race_data_track_N.db        # per-track race history (one per track)
├── scripts/
│   ├── migrate_phase1_auth.py  # idempotent auth-schema migration
│   ├── migrate_phase2_prefs.py # idempotent user-prefs migration
│   ├── recover_merged_sessions.py  # detects + splits parser-merged sessions
│   └── test-{all,backend,frontend}.sh
├── tests/
│   ├── test_auth/              # registration, verify, login, CSRF, /me
│   ├── test_phase2/            # per-user prefs CRUD + isolation
│   ├── test_phase3/            # query cache + heavy-read rate limit
│   ├── test_fleet/             # Fleet Tracker: pace, CRUD, auth, E2E lifecycle
│   └── test_migrations/        # Phase 1 + 2 schema migrations
├── racing-analyzer/            # Next.js 15 dashboard
│   ├── app/
│   │   ├── components/RaceDashboard/   # main live view + sub-components
│   │   ├── services/                   # API clients + WebSocketService
│   │   ├── contexts/AuthContext.tsx
│   │   ├── login, register, verify-email, forgot-password, reset-password/  # auth pages
│   │   ├── privacy, terms/             # GDPR pages
│   │   ├── admin, data, team/[teamName]/
│   │   └── ...
│   ├── utils/                          # raceMath, persistence, config
│   ├── __tests__/                      # Jest tests (auth, phase2, utils, fleet)
│   ├── .env.production
│   └── package.json
└── docs/
    ├── ARCHITECTURE.md
    ├── DEPLOY.md
    └── API.md
```

## License

Private project. No public license declared.
