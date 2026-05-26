# Deployment Runbook

This is the operational reference for the live deployment at
**https://kart.krranalyser.fr**. Solo operator, single VPS, pm2 +
nginx. Read top-to-bottom on first read; later visits use the section
index.

## Topology

- Single OVH VPS, Ubuntu, ~155 GB disk.
- nginx terminates TLS, proxies to two pm2 processes:
  - `lt-analyzer-backend` → Flask on `127.0.0.1:5000`
  - `lt-analyzer-frontend` → Next.js on `127.0.0.1:3000`
- pm2 module `pm2-logrotate` keeps logs bounded (50 MB cap, 7-copy
  retention, daily rotate at midnight, compressed).
- Three SQLite files in the project root: `auth.db`, `tracks.db`, and
  one `race_data_track_N.db` per active track.

## Initial deployment

Done once, captured here for re-do or staging clone:

```bash
# Code
git clone git@github.com:tankyx/LT-Analyzer.git
cd LT-Analyzer

# Backend venv
python -m venv racing-venv
source racing-venv/bin/activate
pip install -r requirements.txt

# Frontend build
cd racing-analyzer
npm ci
# fill in .env.production (NEXT_PUBLIC_API_URL, _WS_URL, _TURNSTILE_SITE_KEY,
# _INVITE_REQUIRED)
npm run build
cd ..

# Env file
cp .env.example .env
# edit .env: FLASK_SECRET_KEY (32-byte hex), CORS_ORIGINS, BREVO_API_KEY,
# TURNSTILE_SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD, FRONTEND_BASE_URL,
# SESSION_COOKIE_SECURE=true, ENABLE_TEST_ENDPOINTS=false.
chmod 600 .env

# Bootstrap DBs
python initialize_databases.py     # users + sessions + login_attempts tables, admin user
python scripts/migrate_phase1_auth.py
python scripts/migrate_phase2_prefs.py

# pm2 processes
pm2 start start-selenium.sh --name lt-analyzer-backend
pm2 start start-frontend.sh --name lt-analyzer-frontend
pm2 install pm2-logrotate
pm2 set pm2-logrotate:max_size 50M
pm2 set pm2-logrotate:retain 7
pm2 set pm2-logrotate:compress true
pm2 set pm2-logrotate:rotateInterval '0 0 * * *'
pm2 save  # persist process list across reboots
pm2 startup  # follow printed instructions to set up boot persistence
```

nginx config lives at `/etc/nginx/sites-available/kart.krranalyser.fr`,
symlinked into `sites-enabled/`. Outline:

```nginx
server {
    listen 443 ssl http2;
    server_name kart.krranalyser.fr;
    # ... Let's Encrypt certs ...

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /socket.io/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

The `X-Forwarded-For` header is mandatory — Flask's `ProxyFix` middleware
reads it to populate `request.remote_addr`, which the rate limiter keys on.

## Routine deploy (code change)

```bash
git pull
source racing-venv/bin/activate
pip install -r requirements.txt        # only if requirements.txt changed
cd racing-analyzer && npm ci && npm run build && cd ..
pm2 restart lt-analyzer-backend lt-analyzer-frontend --update-env
pm2 logs lt-analyzer-backend --lines 20
```

`--update-env` re-reads `.env` for the backend (without it, pm2 keeps
the old env). Frontend rebuild is required for any `NEXT_PUBLIC_*`
change because Next bakes them into the bundle at build time.

## Running a migration

All migrations are idempotent — safe to re-run. They also re-run
defensively at backend boot via `_ensure_auth_schema()`. To apply a new
migration explicitly:

```bash
cp auth.db auth.db.bak-before-<thing>     # 1. snapshot
python scripts/migrate_<thing>.py         # 2. apply
sqlite3 auth.db "<verify>"                # 3. confirm
pm2 restart lt-analyzer-backend           # 4. pick up any code changes
```

When writing a new migration, follow the pattern in
`scripts/migrate_phase2_prefs.py`: `PRAGMA table_info()` + `sqlite_master`
checks before each `ALTER`/`CREATE`, abort with `RuntimeError` if the
DB is in an unexpected state.

## Opening the gate (closed beta → general availability)

After a successful closed-beta window:

```bash
# .env
sed -i 's/^REGISTRATION_OPEN=false$/REGISTRATION_OPEN=true/' .env
# racing-analyzer/.env.production
sed -i 's/^NEXT_PUBLIC_INVITE_REQUIRED=true$/NEXT_PUBLIC_INVITE_REQUIRED=false/' racing-analyzer/.env.production

cd racing-analyzer && npm run build && cd ..
pm2 restart lt-analyzer-backend lt-analyzer-frontend --update-env
```

Frontend rebuild is mandatory — `NEXT_PUBLIC_INVITE_REQUIRED` is baked.

## Adding a new track

Operational steps to add a 12th+ track:

1. Get the Apex Timing live-timing URL and the WebSocket URL.
2. Insert into `tracks.db`:

   ```bash
   sqlite3 tracks.db <<'SQL'
   INSERT INTO tracks (track_name, location, length_meters, timing_url, websocket_url, is_active)
   VALUES ('New Track', 'City, Country', 1300,
           'https://www.apex-timing.com/live-timing/.../index.html',
           'ws://www.apex-timing.com:8585/', 1);
   SQL
   ```

3. `pm2 restart lt-analyzer-backend` — `MultiTrackManager` picks up new
   entries from `tracks.db` on init and starts a `TrackSpecificParser`.
4. The first scrape creates `race_data_track_<id>.db` automatically
   with the right schema and indexes.

Or use the admin UI at `/admin → Tracks tab → Add track`.

## Backup + restore

The race-data DBs are large (~40 GB total post-cleanup). Backups:

```bash
# Daily snapshot of auth.db + tracks.db (small, critical)
mkdir -p ~/backups
sqlite3 auth.db ".backup '$HOME/backups/auth-$(date +%Y%m%d).db'"
sqlite3 tracks.db ".backup '$HOME/backups/tracks-$(date +%Y%m%d).db'"

# Optional: per-track race data (only worth doing periodically given size)
for db in race_data_track_*.db; do
  sqlite3 "$db" ".backup '$HOME/backups/${db%.db}-$(date +%Y%m%d).db'"
done
```

Restore from a snapshot:

```bash
pm2 stop lt-analyzer-backend
cp ~/backups/auth-20260526.db auth.db
pm2 start lt-analyzer-backend
```

## Storage cleanup (run-it-when-needed)

On 2026-05-26 a one-time storage pass dropped duplicate indexes +
deleted lap rows from `is_excluded=1` sessions + VACUUMed every track
DB. Recovered ~26 GB. To re-run later if needed:

```bash
pm2 stop lt-analyzer-backend
for tid in 9 11 6 7 4 2 8 5 1 3 10; do
  db="race_data_track_${tid}.db"
  sqlite3 "$db" <<'SQL'
DROP INDEX IF EXISTS idx_lap_times_session_time;
DROP INDEX IF EXISTS idx_lap_times_team_session;
DELETE FROM lap_times   WHERE session_id IN (SELECT session_id FROM race_sessions WHERE is_excluded = 1);
DELETE FROM lap_history WHERE session_id IN (SELECT session_id FROM race_sessions WHERE is_excluded = 1);
VACUUM;
SQL
done
pm2 start lt-analyzer-backend
```

Order matters when disk is tight — vacuum smallest first so freed
space accumulates before the larger files.

## Rollback

A bad deploy:

```bash
git log --oneline -5     # find the last-known-good SHA
git checkout <sha>       # detached HEAD
# rebuild frontend if frontend files were touched
cd racing-analyzer && npm run build && cd ..
pm2 restart lt-analyzer-backend lt-analyzer-frontend --update-env
# investigate, then either:
git checkout main && git revert <bad-sha> ... && deploy properly
```

A bad migration: see "Backup + restore". `auth.db.bak-<phase>` files
in the project root are point-in-time snapshots taken before each
phase's migration; copy back, restart.

## Smoke tests after a deploy

```bash
curl -sS -o /dev/null -w "auth/check:    HTTP %{http_code}\n"  http://127.0.0.1:5000/api/auth/check
curl -sS -o /dev/null -w "auth/csrf:     HTTP %{http_code}\n"  http://127.0.0.1:5000/api/auth/csrf
curl -sS -o /dev/null -w "me/prefs anon: HTTP %{http_code}\n"  http://127.0.0.1:5000/api/me/prefs/1
pm2 logs lt-analyzer-backend --lines 30 --nostream | grep -iE 'error|traceback|exception' | head
```

Expected: 200, 200, 401, no errors in the log scan. Then browser
smoke: log in, switch tracks, modify a stint, confirm cross-device
sync (second browser as same user).

## Email infrastructure

- Brevo (https://www.brevo.com) — free tier 300 mails/day. API key in
  `.env` as `BREVO_API_KEY`.
- Sender: `noreply@krranalyser.fr`. SPF + DKIM + DMARC configured via
  Cloudflare (krranalyser.fr is on Cloudflare DNS).
- VPS public IP must be on Brevo's authorised list:
  https://app.brevo.com/security/authorised_ips. New IP = blocked
  sends with `401 unauthorized`.
- Test deliverability without registering a throwaway:

  ```bash
  curl -X POST https://api.brevo.com/v3/smtp/email \
    -H "api-key: $(grep '^BREVO_API_KEY=' .env | cut -d= -f2)" \
    -H "content-type: application/json" \
    -d '{"sender":{"name":"LT-Analyzer","email":"noreply@krranalyser.fr"},
         "to":[{"email":"<your-inbox>"}],
         "subject":"Test","textContent":"."}'
  ```

  Check Gmail → Show original. Want SPF/DKIM/DMARC = PASS.

## Cloudflare Turnstile

Dashboard: https://dash.cloudflare.com → Turnstile. Site key is in
`racing-analyzer/.env.production` (`NEXT_PUBLIC_TURNSTILE_SITE_KEY`),
secret key in backend `.env` (`TURNSTILE_SECRET_KEY`).

Allowed hostnames in the site config must include
`kart.krranalyser.fr` exactly (Turnstile does not match subdomains
implicitly). For local dev, also add `localhost`.

Empty `TURNSTILE_SECRET_KEY` on the backend → soft-pass with a warning
log. Useful escape hatch if Cloudflare is globally down.

## Phase 3d (gunicorn) — deferred

The current backend runs Werkzeug + `async_mode='threading'`. The
asyncio scraper makes the gunicorn migration risky: `eventlet` workers
monkey-patch socket primitives globally, which can subtly break
`apex_timing_websocket.py`'s `websockets` library. `gthread` workers
don't carry Socket.IO's WebSocket transport.

If gunicorn becomes necessary (multi-worker, concurrent users beyond
~hundreds):

1. Provision a staging copy of the VPS (or a `:5001` instance).
2. Install `gunicorn`, set `USE_EVENTLET=true`, restart with the new
   start script:

   ```bash
   exec gunicorn --worker-class eventlet --workers 1 \
       --bind 127.0.0.1:5000 --timeout 120 \
       --access-logfile - --error-logfile - \
       wsgi:app
   ```

3. Verify all 11 scrapers reconnect cleanly and the dashboard streams
   updates. Watch the scraper logs for `EventletDeprecationWarning` or
   silent hangs.
4. If eventlet breaks the scraper: fall back to gthread + accept
   long-polling-only Socket.IO. Or run the scraper in a separate
   process and have the Flask process consume from a queue.

This isn't a small change. Don't combine it with anything else.
