"""Device hub: the in-memory side of the `/api/device/*` surface.

A datalogger on a kart follows one team over cellular. It cannot log in with
Turnstile, cannot inflate gzip, cannot speak Engine.IO, and pays for every
byte. This module holds what those constraints need on the server:

- token helpers (generation, hashing) — the DB side lives in the blueprint;
- per-(account, track, team) sequence numbers, so a quiet lap is a `304`;
- live SSE subscribers, one per open `/api/device/stream`, woken by the
  parser's update listener and by pit alerts;
- pit-alert routing to the *right* board (subscription scope + explicit
  targets), with a short per-device replay buffer for dropped connections.

No Flask imports: everything here is plain Python so it can be tested
without an app context. The blueprint (`race_app/blueprints/device_routes.py`)
adapts it to HTTP.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Iterable, Optional


TOKEN_LIFETIME_DAYS = 90
TOKEN_BYTES = 32                    # entropy of a freshly issued token
HEARTBEAT_SECONDS = 15              # SSE comment line cadence while quiet
SSE_RETRY_MS = 5000                 # reconnect backoff handed to the board
ALERT_BUFFER_PER_DEVICE = 5         # replayed on reconnect while still fresh
ALERT_REPLAY_CAP_MS = 120_000       # never replay an alert older than this
MAX_STREAMS_PER_DEVICE = 3          # a reconnect race may briefly overlap
MAX_STREAMS_TOTAL = 200             # each stream pins one gunicorn thread


def utc_now_iso() -> str:
    """Zone-suffixed timestamp for device routes (the board correlates it
    with its own flash log, so the zone must be unambiguous)."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def generate_token() -> str:
    """Opaque base64url token with TOKEN_BYTES of entropy. Shown once."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """Tokens are 256-bit random values, so an unsalted SHA-256 is enough:
    a stolen auth.db does not yield usable credentials."""
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


# --- Team matching -----------------------------------------------------------

def _strip_class_prefix(name: str) -> str:
    """`"1 - TEAM"` -> `"TEAM"`; anything else unchanged."""
    s = (name or '').strip()
    if len(s) > 4 and s[0].isdigit() and s[1:4] == ' - ':
        return s[4:].strip()
    return s


def _norm(name: str) -> str:
    return _strip_class_prefix(name).casefold()


def teams_equal(a: str, b: str) -> bool:
    """Loose equality used for alert scope: case-insensitive, class prefix
    optional on either side."""
    return _norm(a) == _norm(b)


def match_team(teams: list, query: str) -> Optional[int]:
    """Index of the row the board follows, or None.

    Exact name first (what the feed sends, what the web UI shows), then a
    case-insensitive / prefix-less match, then the kart number, so a board
    configured with either the name or the plate resolves.
    """
    q = (query or '').strip()
    if not q:
        return None
    for i, t in enumerate(teams):
        if (t.get('Team') or '') == q:
            return i
    nq = _norm(q)
    for i, t in enumerate(teams):
        if _norm(t.get('Team') or '') == nq:
            return i
    for i, t in enumerate(teams):
        if str(t.get('Kart') or '').strip() == q:
            return i
    return None


# --- SSE framing -------------------------------------------------------------

def sse_event(event: str, data: dict, event_id=None) -> str:
    """One SSE frame. `data` is compact JSON on a single line."""
    body = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    lines = []
    if event_id is not None:
        lines.append(f'id: {event_id}')
    lines.append(f'event: {event}')
    lines.append(f'data: {body}')
    return '\n'.join(lines) + '\n\n'


SSE_HEARTBEAT = ': heartbeat\n\n'
SSE_RETRY = f'retry: {SSE_RETRY_MS}\n\n'


# --- Subscribers -------------------------------------------------------------

class Subscriber:
    """One open `/api/device/stream`. Woken by data (coalesced to a flag) and
    by alerts (queued, never coalesced — the pit crew acts on every one)."""

    __slots__ = ('device_id', 'device_label', 'user_id', 'track_id', 'team',
                 'matched_team', 'last_seq', '_cond', '_data_pending',
                 '_alerts', 'closed')

    def __init__(self, device_id: int, device_label: str, user_id: int,
                 track_id: int, team: str):
        self.device_id = device_id
        self.device_label = device_label
        self.user_id = user_id
        self.track_id = track_id
        self.team = team
        self.matched_team: Optional[str] = None
        self.last_seq: Optional[int] = None
        self._cond = threading.Condition()
        self._data_pending = False
        self._alerts: deque = deque()
        self.closed = False

    def follows(self, track_id: int, team_name: Optional[str]) -> bool:
        if self.track_id != track_id:
            return False
        if not team_name:
            return True
        return teams_equal(self.team, team_name) or (
            self.matched_team is not None and teams_equal(self.matched_team, team_name))

    def signal_data(self) -> None:
        with self._cond:
            self._data_pending = True
            self._cond.notify()

    def push_alert(self, alert: dict) -> None:
        with self._cond:
            self._alerts.append(alert)
            self._cond.notify()

    def wait(self, timeout: float):
        """Block until data or an alert arrives, or `timeout` elapses.
        Returns (data_pending, [alerts])."""
        with self._cond:
            if not self._data_pending and not self._alerts:
                self._cond.wait(timeout)
            data = self._data_pending
            self._data_pending = False
            alerts = list(self._alerts)
            self._alerts.clear()
            return data, alerts


class DeviceHub:
    def __init__(self):
        self._lock = threading.Lock()
        # (user_id, track_id, matched_team) -> (seq, fingerprint, updated_at)
        self._seq: dict = {}
        # device_id -> set[Subscriber]
        self._subs: dict = {}
        # device_id -> deque[(alert, expires_monotonic)]
        self._alert_buffer: dict = {}
        self._alert_counter = 0

    # -- rows ----------------------------------------------------------------

    def build_row(self, user_id: int, track_id: int, session_id,
                  teams: list, team_query: str) -> Optional[dict]:
        """The flat object served by `/api/device/live` and pushed as
        `event: team`. None when the team is not in the standings.

        `seq` moves only when a displayed value changes, so the board's
        `If-None-Match` turns a quiet lap into an empty `304`.
        """
        from multi_track_manager import compute_team_gaps  # local: keeps this module light to import

        idx = match_team(teams, team_query)
        if idx is None:
            return None
        team = teams[idx]
        gaps = compute_team_gaps(teams, idx)
        matched = team.get('Team') or ''
        laps_raw = str(team.get('Total Laps') or '').strip()
        laps = int(laps_raw) if laps_raw.isdigit() else None
        content = {
            'track_id': int(track_id),
            'session_id': session_id,
            'team': team_query,
            'matched_team': matched,
            'kart': str(team.get('Kart') or ''),
            'position': gaps['position'],
            'gap_to_front': gaps['gap_to_front'],
            'gap_to_behind': gaps['gap_to_behind'],
            'last_lap': team.get('Last Lap') or '',
            'best_lap': team.get('Best Lap') or '',
            'laps': laps,
            'pit_stops': str(team.get('Pit Stops') or '0'),
            'status': team.get('Status') or 'On Track',
        }
        fingerprint = json.dumps(content, sort_keys=True, separators=(',', ':'))
        key = (user_id, int(track_id), matched)
        now_sec = int(time.time())
        with self._lock:
            prev = self._seq.get(key)
            if prev and prev[1] == fingerprint:
                seq, _, updated_at = prev
            else:
                seq = max(now_sec, (prev[0] + 1) if prev else 0)
                updated_at = utc_now_iso()
                self._seq[key] = (seq, fingerprint, updated_at)
        return {'seq': seq, **content, 'updated_at': updated_at}

    # -- subscribers ---------------------------------------------------------

    def subscribe(self, device_id: int, device_label: str, user_id: int,
                  track_id: int, team: str) -> Optional[Subscriber]:
        """Register a stream. None when the per-device or global cap is hit."""
        with self._lock:
            mine = self._subs.setdefault(device_id, set())
            total = sum(len(s) for s in self._subs.values())
            if len(mine) >= MAX_STREAMS_PER_DEVICE or total >= MAX_STREAMS_TOTAL:
                return None
            sub = Subscriber(device_id, device_label, user_id, int(track_id), team)
            mine.add(sub)
            return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            sub.closed = True
            subs = self._subs.get(sub.device_id)
            if subs:
                subs.discard(sub)
                if not subs:
                    del self._subs[sub.device_id]

    def notify_track(self, track_id, session_id=None, timestamp=None) -> None:
        """Parser update listener: wake every stream on this track."""
        try:
            tid = int(track_id)
        except (TypeError, ValueError):
            return
        with self._lock:
            targets = [s for subs in self._subs.values() for s in subs if s.track_id == tid]
        for s in targets:
            s.signal_data()

    def online_devices(self, user_id: int) -> set:
        with self._lock:
            return {did for did, subs in self._subs.items()
                    if any(s.user_id == user_id for s in subs)}

    def stream_count(self) -> int:
        with self._lock:
            return sum(len(s) for s in self._subs.values())

    # -- alerts --------------------------------------------------------------

    def deliver_alert(self, user_id: int, alert: dict, *, track_id, team_name=None,
                      target_device_ids: Optional[Iterable[int]] = None,
                      known_device_ids: Iterable[int] = (),
                      exclude_device_id: Optional[int] = None) -> dict:
        """Route a pit alert to the boards that should buzz.

        Candidates are the caller's devices whose stream follows `track_id`
        (and `team_name` when given); `target_device_ids` narrows that to an
        explicit set. Returns {delivered_to, devices_online, event_id} —
        honest numbers, because the pit crew acts on them.

        Alerts are also buffered per targeted device so a board that dropped
        its connection gets it on reconnect while it is still fresh.
        """
        try:
            tid = int(track_id)
        except (TypeError, ValueError):
            tid = track_id
        targets = set(int(d) for d in target_device_ids) if target_device_ids is not None else None
        duration_ms = int(alert.get('duration_ms') or ALERT_REPLAY_CAP_MS)
        expires = time.monotonic() + min(duration_ms, ALERT_REPLAY_CAP_MS) / 1000.0

        with self._lock:
            self._alert_counter += 1
            event_id = int(time.time() * 1000) * 1000 + (self._alert_counter % 1000)
            payload = dict(alert, event_id=event_id)

            written = set()
            online = set()
            for did, subs in self._subs.items():
                for s in subs:
                    if s.user_id != user_id:
                        continue
                    online.add(did)
                    if did == exclude_device_id:
                        continue
                    if targets is not None and did not in targets:
                        continue
                    if not s.follows(tid, team_name):
                        continue
                    s.push_alert(payload)
                    written.add(did)

            # Buffer for every device that *should* receive it, online or not,
            # so a reconnecting board still gets a fresh alert.
            buffer_for = targets if targets is not None else (set(int(d) for d in known_device_ids) | online)
            for did in buffer_for:
                if did == exclude_device_id:
                    continue
                buf = self._alert_buffer.setdefault(did, deque(maxlen=ALERT_BUFFER_PER_DEVICE))
                buf.append((payload, expires, tid, team_name))

        return {'delivered_to': len(written), 'devices_online': len(online), 'event_id': event_id}

    def take_pending_alerts(self, sub: Subscriber) -> list:
        """Buffered alerts for a (re)connecting stream that are still inside
        their window and match its subscription. Delivered once."""
        now = time.monotonic()
        out = []
        with self._lock:
            buf = self._alert_buffer.get(sub.device_id)
            if not buf:
                return out
            keep = deque(maxlen=ALERT_BUFFER_PER_DEVICE)
            for payload, expires, tid, team_name in buf:
                if expires <= now:
                    continue
                if sub.follows(tid, team_name):
                    out.append(payload)
                else:
                    keep.append((payload, expires, tid, team_name))
            if keep:
                self._alert_buffer[sub.device_id] = keep
            else:
                del self._alert_buffer[sub.device_id]
        return out

    def reset(self) -> None:
        """Test helper."""
        with self._lock:
            self._seq.clear()
            self._subs.clear()
            self._alert_buffer.clear()


hub = DeviceHub()
