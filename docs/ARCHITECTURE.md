# Architecture

## Process topology

```
                ┌───────────────────────────────────────────────────────┐
                │                   nginx (TLS termination)             │
                │   kart.krranalyser.fr  → 80/443                        │
                └────────────────┬──────────────────────────────────────┘
                                 │
                ┌────────────────┴───────────────┐
                ▼                                ▼
        /  (Next.js, :3000)              /api/, /socket.io/ (:5000)
        pm2: lt-analyzer-frontend         pm2: lt-analyzer-backend
                                                  │
                                       ┌──────────┼─────────────┐
                                       ▼          ▼             ▼
                                Werkzeug+threading   MultiTrackManager
                                  (Flask app)        (asyncio loop in
                                                      a daemon thread)
                                                          │
                                                ┌─────────┴─────────┐
                                                ▼ ... × 11           ▼
                                       TrackSpecificParser   broadcast_all_tracks_status
                                            │
                                            ▼
                                  race_data_track_N.db (WAL, busy=5s)
```

Single backend process. `async_mode='threading'` means Socket.IO uses
real OS threads (one per connected client), serialised behind the GIL
and `connected_clients_lock`. The asyncio scrapers run in a separate
background thread on their own event loop (`multi_track_loop`), so the
Flask request-handling threads never block on WebSocket I/O.

There's exactly one Flask process today (Werkzeug dev server). The
gunicorn migration is intentionally deferred — see "Phase 3d" in
[`DEPLOY.md`](DEPLOY.md).

## Data layer

Three classes of database, all SQLite, all in the project root:

| File | Purpose | Schema |
|---|---|---|
| `auth.db` | users, sessions, login attempts, audit log, rate-limit events, invite codes, per-user prefs, driver-alias dictionary | created by `initialize_databases.py`, extended by `scripts/migrate_phase{1,2}_*.py` |
| `tracks.db` | configured tracks: id, name, location, length, Apex Timing URL + WebSocket URL, layout definitions | created by `database_manager.py:TrackDatabase.init_database()` |
| `race_data_track_N.db` | per-track lap data: `race_sessions`, `lap_times`, `lap_history` | created on first scrape by `MultiTrackManager._setup_track_database()`; one file per track |

All have `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`. The
per-track DBs use a separate writer thread (the parser) and many reader
threads (Flask handlers).

## Per-track database

```sql
CREATE TABLE race_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TIMESTAMP,
    name TEXT,
    track TEXT,
    layout_id INTEGER,
    is_excluded INTEGER DEFAULT 0
);

CREATE TABLE lap_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    timestamp TEXT,
    position INTEGER,
    kart_number INTEGER,
    team_name TEXT,
    last_lap TEXT,
    best_lap TEXT,
    gap TEXT,
    RunTime TEXT,         -- INTEGER affinity, schema is legacy
    pit_stops INTEGER
);

CREATE TABLE lap_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    timestamp TEXT,
    kart_number INTEGER,
    team_name TEXT,
    lap_number INTEGER,
    lap_time TEXT,
    position_after_lap INTEGER,
    pit_this_lap INTEGER
);
```

**Indexes on `lap_times`** (post-2026-05-26 cleanup):

- `idx_lap_times_session` (session_id, timestamp) — legacy
- `idx_lap_times_team` (team_name, session_id) — legacy
- `idx_lap_times_session_kart` (session_id, kart_number, timestamp DESC)
- `idx_lap_times_team_best` (team_name, best_lap)

Two duplicates (`idx_lap_times_session_time`, `idx_lap_times_team_session`)
were dropped in the storage cleanup and are no longer recreated by
`MultiTrackManager`.

## Write-volume design

`lap_history` records one row per completed lap (driven by Apex Timing's
`last_lap` value changing). `lap_times` historically wrote one row per
parser tick (~1s) for every team, which produced 500× the row count of
`lap_history` and was a major storage waste.

Since the 2026-05-26 perf pass, `lap_times` is write-deduplicated: a new
row is inserted only when `(position, last_lap, best_lap, pit_stops)`
differs from the cached previous state for that `(session_id, kart_number)`.
First sighting of a kart in a session always records as a baseline.
`gap` and `RunTime` are captured at the moment of the recorded change
and are slightly stale by design — live state for the dashboard comes
from the in-memory parser snapshot via Socket.IO.

## Authentication architecture (Phase 1)

- Passwords: `bcrypt` (with a transparent legacy-SHA256 upgrade path on
  successful login).
- Sessions: 32-byte URL-safe tokens stored in `auth.db.sessions`, 24h
  expiry, lookup-by-token on every `@login_required`/`@admin_required`
  call. Cookie is `HttpOnly`, `Secure`, `SameSite=Lax`.
- CSRF: server issues a per-session token at `GET /api/auth/csrf`; the
  client sends it as `X-CSRF-Token` on unsafe methods. A `@before_request`
  guard enforces matching on `/api/*` (anonymous endpoints in
  `CSRF_EXEMPT_PATHS` are skipped because they're protected by Turnstile
  instead).
- Turnstile: `@require_turnstile` decorator on `register`,
  `forgot-password`, `resend-verification`, `login`. Empty
  `TURNSTILE_SECRET_KEY` → soft-pass with a warning (dev).
- Email: `email_service.py` abstracts Brevo + a NullEmailSender (logs to
  `/tmp/lt-mail/`). Templates for verification, password reset, welcome.
- Rate limits: shared `rate_limit_events` table with per-IP and per-email
  buckets. Generic `_rate_limit_hit(bucket, key, max, window_seconds)`
  helper.
- Audit log: `auth.db.audit_log`, append-only, hooked into every
  authentication event and admin action (user CRUD, alias add/remove,
  session exclude, mass delete, prefs update, etc.).
- ProxyFix wraps `app.wsgi_app` so `request.remote_addr` reflects the
  real client IP behind nginx (matters for the rate-limit keys).

## Per-user state (Phase 2)

Before Phase 2, `race_data['monitored_teams']`, `race_data['my_team']`
and the pit-config trio were module-globals — two concurrent users
clobbered each other. Phase 2 moved them to `user_track_prefs`, keyed by
`(user_id, track_id)`:

```sql
CREATE TABLE user_track_prefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    my_team TEXT,
    monitored_teams TEXT,        -- JSON array of kart numbers
    pit_stop_time INTEGER,
    required_pit_stops INTEGER,
    default_lap_time REAL,
    stint_planner_config TEXT,
    stint_planner_presets TEXT,
    stint_assignments TEXT,      -- JSON array
    driver_names TEXT,
    current_driver_index INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, track_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

Plus `users.selected_track_id` for the "currently viewing" track (a
per-user setting, not per-track).

Frontend reads via `GET /api/me/prefs/<track_id>` on track change and
writes via `PUT /api/me/prefs/<track_id>` debounced by 500ms.

## Cross-device live sync

`socketio.emit('prefs_updated', ..., room=f'user_prefs_{user_id}')` on
every successful `PUT /api/me/prefs/<track_id>`. The client joins that
room from `AuthContext` after login.

Receiver flow on `prefs_updated`:
1. Compare `event.updated_at` against `getLastSeenUpdatedAt(track_id)`.
   Match → skip (own echo).
2. `flush()` the local debouncer so any in-flight local edits are sent
   before we refetch (prevents a stale snapshot from overwriting them).
3. `fetchPrefs(track_id)`.
4. Apply per-field, except `stint_planner_config` (deliberate exclusion
   — it raced with local preset selection and the race is asymmetric).

Same shape for `selected_track_updated` (per-user, not per-track).

## Delta math

Backend stopped computing head-to-head deltas in Phase 2 — that math
is now done client-side in `racing-analyzer/utils/raceMath.ts`. Backend
ships only:

- `track_update` Socket.IO events on `track_N` rooms with the current
  `teams` snapshot
- The Apex Timing `Gap` field unchanged (gap-to-leader)

Frontend computes head-to-head as `mon.gap_to_leader - my.gap_to_leader`,
then applies the user's pit config to derive `adjusted_gap`. Lapped
teams (`"1 Tour"` etc.) cause the gap to return `NaN` — the UI shows
`—` rather than misleading math.

## Performance (Phase 3)

Three things shipped:

- **TTL cache** on `top-teams`, `cross-track-sessions`, `search-all`
  (default 60s, env-tunable). Lives in-process in `race_ui.py`'s
  `_query_cache` dict + lock. Invalidated by prefix on admin writes
  that could surface stale results.
- **Per-IP rate limit** on the same three heavy reads (default 120/h/IP).
- **lap_times write-dedup** in the parser (see "Write-volume design").

Deferred:

- **gunicorn migration** — risky because of the asyncio scraper. Needs
  its own session with a staging test of eventlet vs gthread workers.

## Frontend architecture

Next.js 15 (App Router), React 19, TypeScript, Tailwind. Pages and
state organisation:

- `app/contexts/AuthContext.tsx` — single source of truth for `user`,
  CSRF token, `apiFetch` helper, login/logout, Socket.IO user-prefs
  room subscription.
- `app/services/`
  - `WebSocketService.ts` — singleton, Socket.IO client. Lifecycle is
    independent of any React tree; consumers subscribe via callbacks +
    add-listener APIs.
  - `ApiService.ts` — REST helpers.
  - `UserPrefsService.ts` — Phase 2 per-(user, track) prefs CRUD,
    debouncer, last-seen `updated_at` map for echo dedup.
  - `SelectedTrackService.ts` — per-user "currently viewing" track.
- `app/components/RaceDashboard/index.tsx` — main live view. Owns
  `selectedTrackId`, `monitoredTeams`, `myTeam`, pit config. Wires the
  debouncer to the prefs PUT and subscribes to both `prefs_updated`
  and `selected_track_updated`.
- `app/components/RaceDashboard/StintPlanner.tsx` — stint planner.
  Same pattern: pushes via debouncer, listens for live sync (driver
  names + presets + current driver index; **not** stint_planner_config —
  see live-sync section).
- Auth pages (`/login`, `/register`, `/verify-email`,
  `/forgot-password`, `/reset-password`, `/privacy`, `/terms`).
- Admin (`/admin`) for tracks, users, aliases, invite codes.
- `/data` for team/driver search + top-teams + cross-track profile.
- `/team/[teamName]` for full per-driver history.
