"""Locust HTTP load profile for LT-Analyzer.

Models a live-race dashboard user: /fleet/state every 3s (the dominant
request), plus an occasional leaderboard read.

Acceptance target (audit round 2026-07): p95 /fleet/state < 300ms at N=300.

Requires locust (not in requirements.txt — manual tool):
    racing-venv/bin/pip install locust

Usage (headless, 300 users, 10/s ramp, 3 minutes):
    LOADTEST_SESSION_COOKIE="$COOKIE" LOADTEST_TRACK_ID=2 \
    locust -f scripts/locustfile.py \
        --host http://127.0.0.1:5000 --headless -u 300 -r 10 -t 3m

Auth: production logins go through Turnstile (fail-closed), so scripted
logins are blocked by design. Instead pass a signed Flask session cookie via
LOADTEST_SESSION_COOKIE — mint one with race_ui.create_session + the app's
session serializer (see scripts/load_test_socketio.py docstring). All
simulated users share that one session (representative: fan-out and fleet
computation cost are per-request, and the shared fleet-pace cache is per
(track, session) anyway).

The occasional /top-teams read trips the per-IP heavy_read limiter by design
when every simulated user shares 127.0.0.1 — 429s there are counted as
successes so they don't pollute the failure stats.
"""

import os
import random

from locust import HttpUser, between, task


TRACK_ID = int(os.environ.get('LOADTEST_TRACK_ID', '1'))
SESSION_COOKIE = os.environ.get('LOADTEST_SESSION_COOKIE', '')


class DashboardUser(HttpUser):
    # The frontend throttles /fleet/state to one call per 3s.
    wait_time = between(2.8, 3.4)

    def on_start(self):
        if not SESSION_COOKIE:
            raise RuntimeError('LOADTEST_SESSION_COOKIE env var is required')
        self.client.cookies.set('session', SESSION_COOKIE)

    @task(20)
    def fleet_state(self):
        self.client.get(f'/api/track/{TRACK_ID}/fleet/state', name='/fleet/state')

    @task(1)
    def top_teams(self):
        limit = random.choice([10, 20, 30])
        with self.client.get(
            f'/api/team-data/top-teams?track_id={TRACK_ID}&limit={limit}',
            name='/team-data/top-teams', catch_response=True,
        ) as resp:
            if resp.status_code == 429:
                resp.success()  # per-IP heavy_read limiter working as intended

    @task(1)
    def tracks_status(self):
        self.client.get('/api/tracks/status', name='/tracks/status')
