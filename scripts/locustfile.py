"""Locust HTTP load profile for LT-Analyzer.

Models a live-race dashboard user: /fleet/state every 3s (the dominant
request), plus an occasional leaderboard read.

Acceptance target (audit round 2026-07): p95 /fleet/state < 300ms at N=300.

Requires locust (not in requirements.txt — manual tool):
    racing-venv/bin/pip install locust

Usage (headless, 300 users, 10/s ramp, 3 minutes):
    racing-venv/bin/locust -f scripts/locustfile.py \
        --host http://127.0.0.1:5000 --headless -u 300 -r 10 -t 3m \
        LOADTEST_USERNAME=loadtest LOADTEST_PASSWORD=... (env vars)

All simulated users share one account login (representative: fan-out and
fleet computation cost are per-request, and the shared fleet-pace cache is
per (track, session) anyway). Create a throwaway user first.
"""

import os
import random

from locust import HttpUser, between, task


TRACK_ID = int(os.environ.get('LOADTEST_TRACK_ID', '1'))
USERNAME = os.environ.get('LOADTEST_USERNAME', 'loadtest')
PASSWORD = os.environ.get('LOADTEST_PASSWORD', '')


class DashboardUser(HttpUser):
    # The frontend throttles /fleet/state to one call per 3s.
    wait_time = between(2.8, 3.4)

    def on_start(self):
        resp = self.client.post('/api/auth/login', json={
            'username': USERNAME, 'password': PASSWORD, 'turnstile_token': 'load-test',
        })
        if resp.status_code != 200:
            raise RuntimeError(f'login failed: {resp.status_code} {resp.text[:200]}')

    @task(20)
    def fleet_state(self):
        self.client.get(f'/api/track/{TRACK_ID}/fleet/state', name='/fleet/state')

    @task(1)
    def top_teams(self):
        limit = random.choice([10, 20, 30])
        self.client.get(f'/api/team-data/top-teams?track_id={TRACK_ID}&limit={limit}',
                        name='/team-data/top-teams')

    @task(1)
    def tracks_status(self):
        self.client.get('/api/tracks/status', name='/tracks/status')
