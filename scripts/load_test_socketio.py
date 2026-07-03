#!/usr/bin/env python3
"""Socket.IO load test: N authenticated websocket clients join a track room
and measure track_update inter-arrival latency (staleness).

Acceptance target (audit round 2026-07): p95 track_update staleness < 2s at
N=300 on the production VPS.

Speaks the Engine.IO/Socket.IO wire protocol directly over websocket-client
(already in racing-venv). The higher-level python-socketio client is NOT used
because websocket-client auto-sends `Origin: <ws host>`, which the server's
CORS whitelist rejects; the raw connection lets us set a whitelisted origin.

Auth: pass a signed Flask session cookie via --cookie (production logins go
through Turnstile, so scripted logins are blocked by design). Mint one with:

    set -a; . ./.env; set +a
    racing-venv/bin/python - <<'PY'
    import race_ui
    from flask.sessions import SecureCookieSessionInterface
    token = race_ui.create_session(<user_id>)
    print(SecureCookieSessionInterface()
          .get_signing_serializer(race_ui.app).dumps({'session_id': token}))
    PY

Usage:
    racing-venv/bin/python scripts/load_test_socketio.py \
        --ws-url ws://127.0.0.1:5000 --origin http://localhost:3000 \
        --track-id 2 --clients 100 --duration 60 --cookie "$COOKIE"
"""

import argparse
import statistics
import sys
import threading
import time

try:
    import websocket
except ImportError:
    sys.exit('missing dependency: pip install websocket-client')


class Stats:
    def __init__(self):
        self.intervals = []
        self.lock = threading.Lock()
        self.connected = 0
        self.rejected = 0
        self.errors = 0

    def record(self, dt: float):
        with self.lock:
            self.intervals.append(dt)


def run_client(idx: int, args, stats: Stats, stop: threading.Event):
    try:
        ws = websocket.create_connection(
            f'{args.ws_url}/socket.io/?EIO=4&transport=websocket',
            origin=args.origin,
            cookie=f'session={args.cookie}',
            timeout=20)
    except Exception as e:
        with stats.lock:
            stats.errors += 1
            if stats.errors <= 5:
                print(f'client {idx}: connect failed: {e}')
        return
    try:
        ws.recv()        # engine.io open
        ws.send('40')    # socket.io connect
        connected = False
        last_update = None
        ws.settimeout(5)
        deadline = time.monotonic() + args.duration
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                frame = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
            if not isinstance(frame, str):
                continue
            if frame.startswith('40{') and not connected:
                connected = True
                with stats.lock:
                    stats.connected += 1
                ws.send(f'42["join_track",{{"track_id":{args.track_id}}}]')
            elif frame.startswith('44'):
                with stats.lock:
                    stats.rejected += 1
                return
            elif frame.startswith('2'):     # engine.io ping
                ws.send('3')
            elif frame.startswith('42["track_update"'):
                now = time.monotonic()
                if last_update is not None:
                    stats.record(now - last_update)
                last_update = now
    finally:
        try:
            ws.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ws-url', default='ws://127.0.0.1:5000')
    ap.add_argument('--origin', default='http://localhost:3000')
    ap.add_argument('--track-id', type=int, default=1)
    ap.add_argument('--clients', type=int, default=50)
    ap.add_argument('--duration', type=int, default=60)
    ap.add_argument('--cookie', required=True, help='signed Flask session cookie value')
    args = ap.parse_args()

    stats = Stats()
    stop = threading.Event()
    threads = []
    print(f'spawning {args.clients} websocket clients against track {args.track_id}...')
    for i in range(args.clients):
        t = threading.Thread(target=run_client, args=(i, args, stats, stop), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.03)  # ~30 connects/s ramp

    for t in threads:
        t.join(timeout=args.duration + 30)
    stop.set()

    print(f'{stats.connected}/{args.clients} connected '
          f'({stats.rejected} rejected, {stats.errors} errors)')
    if not stats.intervals:
        print('NO track_update received — is a session active on this track?')
        return
    xs = sorted(stats.intervals)
    p = lambda q: xs[min(len(xs) - 1, int(q * len(xs)))]
    print(f'track_update inter-arrival over {len(xs)} samples across all clients:')
    print(f'  p50={statistics.median(xs):.3f}s  p95={p(0.95):.3f}s  '
          f'p99={p(0.99):.3f}s  max={xs[-1]:.3f}s')
    print('target: p95 < 2s')


if __name__ == '__main__':
    main()
