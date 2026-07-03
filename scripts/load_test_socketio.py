#!/usr/bin/env python3
"""Socket.IO load test: N authenticated clients join a track room and measure
track_update inter-arrival latency (staleness).

Acceptance target (audit round 2026-07): p95 track_update staleness < 2s at
N=300 on the production VPS.

Requires the client extra (not in requirements.txt — manual tool):
    racing-venv/bin/pip install "python-socketio[client]" websocket-client

Usage:
    python scripts/load_test_socketio.py \
        --base-url http://127.0.0.1:5000 --track-id 1 \
        --clients 100 --duration 60 \
        --username loadtest --password '...'

The user must exist (create a throwaway account). All clients share one
login session — server-side that's one user in the session cache, which is
representative for fan-out cost (rooms fan out per socket, not per user).
NOTE: the per-user session cap keeps ~10 DB session rows; sharing one cookie
across clients avoids tripping login rate limits.
"""

import argparse
import statistics
import sys
import threading
import time

try:
    import requests
    import socketio
except ImportError as exc:
    sys.exit(f"missing dependency: {exc}. pip install 'python-socketio[client]' requests")


def login(base_url: str, username: str, password: str) -> str:
    s = requests.Session()
    resp = s.post(f'{base_url}/api/auth/login', json={
        'username': username, 'password': password, 'turnstile_token': 'load-test',
    })
    if resp.status_code != 200:
        sys.exit(f'login failed ({resp.status_code}): {resp.text[:200]}')
    cookie = s.cookies.get('session')
    if not cookie:
        sys.exit('no session cookie returned — check SESSION_COOKIE_SECURE vs http')
    return cookie


class Client:
    def __init__(self, idx: int, base_url: str, cookie: str, track_id: int, stats: 'Stats'):
        self.idx = idx
        self.stats = stats
        self.track_id = track_id
        self.last_update = None
        self.sio = socketio.Client(reconnection=False, logger=False)
        self.sio.on('connect', self._on_connect)
        self.sio.on('track_update', self._on_track_update)
        self.base_url = base_url
        self.headers = {'Cookie': f'session={cookie}'}

    def _on_connect(self):
        self.stats.connected += 1
        self.sio.emit('join_track', {'track_id': self.track_id})

    def _on_track_update(self, data):
        now = time.monotonic()
        if self.last_update is not None:
            self.stats.record(now - self.last_update)
        self.last_update = now

    def start(self):
        try:
            self.sio.connect(self.base_url, headers=self.headers,
                             transports=['websocket'], wait_timeout=15)
        except Exception as e:
            self.stats.errors += 1
            if self.stats.errors <= 5:
                print(f'client {self.idx}: connect failed: {e}')

    def stop(self):
        try:
            self.sio.disconnect()
        except Exception:
            pass


class Stats:
    def __init__(self):
        self.intervals = []
        self.lock = threading.Lock()
        self.connected = 0
        self.errors = 0

    def record(self, dt: float):
        with self.lock:
            self.intervals.append(dt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-url', default='http://127.0.0.1:5000')
    ap.add_argument('--track-id', type=int, default=1)
    ap.add_argument('--clients', type=int, default=50)
    ap.add_argument('--duration', type=int, default=60)
    ap.add_argument('--username', required=True)
    ap.add_argument('--password', required=True)
    args = ap.parse_args()

    cookie = login(args.base_url, args.username, args.password)
    print(f'logged in; spawning {args.clients} websocket clients...')

    stats = Stats()
    clients = [Client(i, args.base_url, cookie, args.track_id, stats)
               for i in range(args.clients)]
    threads = []
    for c in clients:
        t = threading.Thread(target=c.start, daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.05)  # gentle ramp: 20 connects/s
    for t in threads:
        t.join(timeout=20)

    print(f'{stats.connected}/{args.clients} connected ({stats.errors} errors); '
          f'measuring for {args.duration}s...')
    time.sleep(args.duration)

    for c in clients:
        c.stop()

    if not stats.intervals:
        print('NO track_update received — is a session active on this track? '
              '(use POST /api/test/simulate-session/<id> or a live race)')
        return

    xs = sorted(stats.intervals)
    p = lambda q: xs[min(len(xs) - 1, int(q * len(xs)))]
    print(f'track_update inter-arrival over {len(xs)} samples:')
    print(f'  p50={statistics.median(xs):.3f}s  p95={p(0.95):.3f}s  '
          f'p99={p(0.99):.3f}s  max={xs[-1]:.3f}s')
    print('target: p95 < 2s')


if __name__ == '__main__':
    main()
