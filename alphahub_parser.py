"""
AlphaHub (alpharacehub.com) live-timing parser.

The track's data flow:
    HTML live page  →  reveals (Pusher key, cluster, site slug, channelSuffix,
                       per-session auth token "at-pst")
    REST snapshot   →  /api/v1/<site>/live/current  (full Competitors[] + Sequence)
    Pusher private  →  wss://ws-<cluster>.pusher.com/app/<key>?...
                       subscribe to "private-<site><channelSuffix>"
                       events:
                         update      delta with Sequence (apply if next)
                         refresh     re-fetch snapshot
                         new_session reset state + re-fetch snapshot

Why mirror the Apex flow this closely:
  - Reuses the per-track DB schema, monitor thread, session-id rollover, and
    the Socket.IO `track_update`/team-room broadcasts already implemented in
    TrackSpecificParser. We only need to keep `self.grid_data` populated like
    a parsed Apex tick, and the parent's `start_monitoring` -> `store_lap_data`
    pipeline does the rest.
  - But Apex's `start_monitoring` is hard-wired to its pipe-delimited message
    loop, so we override `start_monitoring` with the Pusher loop and only call
    the bits we need (session id determination, store_lap_data, emit).

Field mapping (from the captured payload):
    CompetitorNumber       -> Kart      (also stored as the row id)
    CompetitorName/Team    -> Team
    Position               -> Position
    LastLaptime  (ms)      -> Last Lap   "M:SS.mmm"
    BestLaptime  (ms)      -> Best Lap
    NumberOfLaps           -> Total Laps + tlp
    RunningTime  (ms)      -> RunTime    "MM:SS"
    GapToFirst   (ms)      -> Gap        leader = "" else "+S.mmm"
    LapsToFirst            -> "Tour N"   when applicable
    PitStops               -> Pit Stops  count
    InPit / Status         -> Status     "Pit-in" / "On Track" / "Finished"
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import ssl
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import requests
import websockets

from multi_track_manager import TrackSpecificParser


_PUSHER_KEY_RE = re.compile(r"""pusherKey\s*[:=]\s*['"]([^'"]+)['"]""")
_PUSHER_CLUSTER_RE = re.compile(r"""pusherCluster\s*[:=]\s*['"]([^'"]+)['"]""")
_SITE_RE = re.compile(r"""(?:siteSlug|siteName|site)\s*[:=]\s*['"]([a-z0-9_-]+)['"]""", re.I)
# channelSuffix=":live" → "private-<site>live"
_CHAN_SUFFIX_RE = re.compile(r"""channelSuffix\s*[:=]\s*['"]([^'"]+)['"]""")
# per-session auth token (at-pst) baked into the page as a Cookie or window.var
_AT_PST_COOKIE_RE = re.compile(r"""at-pst=([^;\"']+)""")
_AT_PST_VAR_RE = re.compile(r"""(?:atPst|at_pst|sessionToken)\s*[:=]\s*['"]([^'"]+)['"]""")
# `/buckmore/live` → site=buckmore (last-resort fallback)
_PATH_SITE_RE = re.compile(r"/([a-z0-9_-]+)/live\b", re.I)


_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _ms_to_laptime(ms: Optional[int]) -> str:
    """1234567 → '1:23.456'. None/<=0 → ''."""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return ''
    if ms <= 0:
        return ''
    minutes, rem = divmod(ms, 60_000)
    secs = rem / 1000.0
    if minutes:
        return f"{minutes}:{secs:06.3f}"
    return f"{secs:.3f}"


def _ms_to_runtime(ms: Optional[int]) -> str:
    """Cumulative race-time ms → 'MM:SS' (matches Apex 'otr')."""
    try:
        total = int(ms) // 1000
    except (TypeError, ValueError):
        return ''
    if total <= 0:
        return ''
    return f"{total // 60:02d}:{total % 60:02d}"


def _ms_to_gap(ms: Optional[int]) -> str:
    """Gap-to-leader in ms → '+S.mmm'; 0/None → ''."""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return ''
    if ms <= 0:
        return ''
    return f"+{ms/1000.0:.3f}"


def _safe_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


_DIGIT_RE = re.compile(r'^\d+$')


def _normalize_kart(number: Any) -> int:
    """AlphaHub CompetitorNumber → integer kart_number for the per-track DB
    (schema declares INTEGER and downstream queries cast to int).

    For all-digit IDs ("17", "23") that's just `int(...)` — matches Buckmore.
    For alpha-prefixed IDs ("C1", "C12" cadet class at Whilton Mill) we derive
    a deterministic 7-digit integer from MD5 of the full string. md5 (not
    Python `hash`) so the value is stable across processes/restarts; 7 digits
    fits any sensible session count (~10M slots) and avoids realistic
    collisions for the dozens of karts in a single session.
    """
    s = str(number or '').strip()
    if not s:
        return 0
    if _DIGIT_RE.match(s):
        return int(s)
    digest = hashlib.md5(s.encode('utf-8')).hexdigest()
    # 7 hex chars → max 0xFFFFFFF = 268M. Mod down to a 7-digit space and
    # ensure it doesn't collide with the natural 1-999 numeric range.
    return 1_000_000 + (int(digest[:7], 16) % 9_000_000)


def _looks_in_pit(comp: Dict[str, Any]) -> bool:
    for k in ('InPit', 'IsInPit', 'PitIn', 'InPits'):
        if comp.get(k):
            return True
    status = str(comp.get('Status', '') or '').lower()
    return 'pit' in status


def _derive_status(comp: Dict[str, Any]) -> str:
    """Map AlphaHub per-competitor flags to the Status strings the frontend
    knows ('On Track' | 'Pit-in' | 'Pit-out' | 'Finished' | 'Retired').

    Priority — the highest-priority signal wins:
      1. TakenChequered  → 'Finished'   (took the chequered flag; the race is
                                          over for this competitor)
      2. Retired         → 'Retired'    (DNF without taking the flag)
      3. explicit Status string (e.g. 'Pit-out') is preferred over inferring
         from a boolean — important because 'Pit-out' contains the substring
         'pit' and would otherwise route to 'Pit-in' via the fallback below.
      4. InPit / IsInPit → 'Pit-in'     (currently in the pit lane)
      5. (fallback)      → 'On Track'

    Without this mapping every finished competitor at a closed session reads
    'On Track' (the snapshot's per-competitor `Status` field is usually empty).
    """
    for k in ('TakenChequered', 'Chequered'):
        if comp.get(k):
            return 'Finished'
    if comp.get('Retired'):
        return 'Retired'
    explicit = str(comp.get('Status', '') or '').strip()
    if explicit:
        return explicit
    for k in ('InPit', 'IsInPit', 'PitIn', 'InPits'):
        if comp.get(k):
            return 'Pit-in'
    return 'On Track'


class AlphaHubConfig:
    """Page-scraped settings needed to subscribe."""

    def __init__(self, *, page_url: str, pusher_key: str, pusher_cluster: str,
                 site: str, channel_suffix: str, at_pst: Optional[str],
                 cookies: Optional[Dict[str, str]] = None,
                 referer: Optional[str] = None):
        self.page_url = page_url
        self.pusher_key = pusher_key
        self.pusher_cluster = pusher_cluster
        self.site = site
        self.channel_suffix = channel_suffix
        self.at_pst = at_pst
        self.cookies = cookies or {}
        self.referer = referer or page_url

    @property
    def channel(self) -> str:
        # Captured live: `private-<site><channelSuffix>` e.g. private-buckmorelive
        return f"private-{self.site}{self.channel_suffix}"

    @property
    def origin(self) -> str:
        parts = urllib.parse.urlparse(self.page_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def auth_url(self) -> str:
        return f"{self.origin}/pusher/auth"

    @property
    def snapshot_url(self) -> str:
        return f"{self.origin}/api/v1/{self.site}/live/current"

    @property
    def ws_url(self) -> str:
        # Standard Pusher endpoint: wss://ws-<cluster>.pusher.com/app/<key>
        return (
            f"wss://ws-{self.pusher_cluster}.pusher.com/app/{self.pusher_key}"
            f"?protocol=7&client=lt-analyzer&version=1.0.0&flash=false"
        )


def discover_config(page_url: str, *, session: Optional[requests.Session] = None,
                    logger: Optional[logging.Logger] = None) -> AlphaHubConfig:
    """Fetch the live page and extract Pusher key / site / channel / auth token.

    Raises ValueError when the page doesn't look like an AlphaHub live page.
    """
    log = logger or logging.getLogger(__name__)
    sess = session or requests.Session()
    sess.headers.update(_DEFAULT_HEADERS)

    resp = sess.get(page_url, timeout=20, allow_redirects=True)
    resp.raise_for_status()
    body = resp.text

    key_m = _PUSHER_KEY_RE.search(body)
    cluster_m = _PUSHER_CLUSTER_RE.search(body)
    # Site precedence: explicit JS var > URL path slug. The URL path is the
    # most reliable signal on alpharacehub.com (every live page is /<site>/live).
    site_m = _SITE_RE.search(body)
    suffix_m = _CHAN_SUFFIX_RE.search(body)
    at_pst = None
    cookie_pst = sess.cookies.get('at-pst')
    if cookie_pst:
        at_pst = cookie_pst
    else:
        m = _AT_PST_COOKIE_RE.search(body) or _AT_PST_VAR_RE.search(body)
        if m:
            at_pst = m.group(1)

    site = None
    if site_m:
        site = site_m.group(1)
    else:
        path_m = _PATH_SITE_RE.search(urllib.parse.urlparse(page_url).path)
        if path_m:
            site = path_m.group(1)

    if not (key_m and site):
        raise ValueError(
            f"AlphaHub config not detected on {page_url}: "
            f"pusher_key={bool(key_m)} site={site!r}"
        )

    cookies = {k: v for k, v in sess.cookies.get_dict().items()}
    cfg = AlphaHubConfig(
        page_url=page_url,
        pusher_key=key_m.group(1),
        pusher_cluster=(cluster_m.group(1) if cluster_m else 'eu'),
        site=site,
        channel_suffix=(suffix_m.group(1) if suffix_m else 'live'),
        at_pst=at_pst,
        cookies=cookies,
        referer=page_url,
    )
    log.info(
        f"AlphaHub config: site={cfg.site} key={cfg.pusher_key[:6]}… "
        f"cluster={cfg.pusher_cluster} channel={cfg.channel} at_pst={'yes' if at_pst else 'no'}"
    )
    return cfg


class AlphaHubParser(TrackSpecificParser):
    """Per-track parser feeding from alpharacehub.com's Pusher channel.

    Reuses TrackSpecificParser's DB plumbing (per-track db, session id rollover,
    monitor thread, Socket.IO broadcasts). Only the message ingress loop is
    AlphaHub-specific.
    """

    # Class-level counter assigning each new instance a sequential "startup
    # index" so we can stagger initial connects when many AlphaHub tracks are
    # configured. Without this, every parser hits discover_config in the same
    # millisecond on backend startup and trips alpharacehub.com's per-IP rate
    # limiter, leaving most parsers in a 429 retry loop. See
    # _START_STAGGER_SECONDS for the gap.
    _startup_counter = 0
    _startup_lock = __import__('threading').Lock()
    # ~1.5s between successive parser first-connects. Matches the rate at
    # which the discovery probe could safely hit the snapshot endpoint
    # serially without 429s.
    _START_STAGGER_SECONDS = 1.5

    def __init__(self, track_id: int, track_name: str, db_path: str,
                 socketio=None, manager=None):
        super().__init__(track_id, track_name, db_path, socketio=socketio, manager=manager)
        # `competitors` is the latest snapshot keyed by CompetitorNumber.
        # We rebuild self.grid_data from it on every tick, then call the parent's
        # store_lap_data / broadcast pipeline.
        self.competitors: Dict[str, Dict[str, Any]] = {}
        self.last_sequence: Optional[int] = None
        self._http = requests.Session()
        self._http.headers.update(_DEFAULT_HEADERS)
        self._cfg: Optional[AlphaHubConfig] = None
        self.is_connected = False
        self._ssl_ctx = ssl.create_default_context()
        with AlphaHubParser._startup_lock:
            self._startup_index = AlphaHubParser._startup_counter
            AlphaHubParser._startup_counter += 1

    # ---- snapshot / delta plumbing ------------------------------------------------
    def _fetch_snapshot(self) -> None:
        """Hard reset from the REST snapshot — used on first connect, on
        `refresh`, and on `new_session`. Sets self.competitors + last_sequence."""
        assert self._cfg is not None
        url = self._cfg.snapshot_url
        try:
            resp = self._http.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self.logger.warning(f"Track {self.track_id}: snapshot fetch failed: {e}")
            return
        comps = data.get('Competitors') or data.get('competitors') or []
        new_state: Dict[str, Dict[str, Any]] = {}
        for c in comps:
            num = str(c.get('CompetitorNumber') or c.get('Number') or c.get('Kart') or '')
            if not num:
                continue
            new_state[num] = dict(c)
        self.competitors = new_state
        self.last_sequence = _safe_int(data.get('Sequence'))
        self.logger.info(
            f"Track {self.track_id}: snapshot loaded ({len(self.competitors)} competitors, "
            f"sequence={self.last_sequence})"
        )

    def _apply_delta(self, payload: Dict[str, Any]) -> bool:
        """Merge a Pusher `update` payload into self.competitors. Returns True
        when something changed. If the Sequence ordering is broken we trigger a
        refresh from the snapshot rather than silently desynchronizing."""
        seq = _safe_int(payload.get('Sequence'))
        if seq is not None and self.last_sequence is not None and seq <= self.last_sequence:
            return False  # stale/duplicate
        if seq is not None and self.last_sequence is not None and seq > self.last_sequence + 50:
            # Big gap — likely missed packets. Refetch.
            self.logger.info(
                f"Track {self.track_id}: sequence jump "
                f"{self.last_sequence}→{seq}; refetching snapshot"
            )
            self._fetch_snapshot()
            return True
        comps = payload.get('Competitors') or payload.get('competitors') or []
        changed = False
        for c in comps:
            num = str(c.get('CompetitorNumber') or c.get('Number') or c.get('Kart') or '')
            if not num:
                continue
            cur = self.competitors.setdefault(num, {})
            for k, v in c.items():
                if cur.get(k) != v:
                    cur[k] = v
                    changed = True
        if seq is not None:
            self.last_sequence = seq
        return changed

    # ---- DataFrame construction --------------------------------------------------
    def get_current_standings(self) -> pd.DataFrame:
        """Build the same shape Apex's parent produces (sorted by Position).

        We re-derive it from self.competitors instead of self.grid_data so that
        whatever Apex-shaped row parsing the base class did is irrelevant here.
        """
        rows = []
        for num, c in self.competitors.items():
            pos = c.get('Position') or c.get('Rank') or c.get('Pos')
            laps = _safe_int(c.get('NumberOfLaps') or c.get('Laps') or c.get('TotalLaps'))
            gap_ms = _safe_int(c.get('GapToFirst') or c.get('GapToLeader'))
            laps_to_first = _safe_int(c.get('LapsToFirst'))
            gap_str = ''
            if laps_to_first and laps_to_first > 0:
                gap_str = f"Tour {laps_to_first}"
            elif gap_ms:
                gap_str = _ms_to_gap(gap_ms)
            status = _derive_status(c)
            raw_team = str(c.get('CompetitorName') or c.get('TeamName')
                           or c.get('Name') or c.get('Team') or '').strip()
            raw_num = str(num).strip()
            # Whilton Mill etc. use class-prefixed IDs ("C1"); the DB needs an
            # int, so we hash to a stable int and prepend the original label
            # to Team so the user can still see "C1 - CADET 1".
            if raw_num and not _DIGIT_RE.match(raw_num):
                team_display = f"{raw_num} - {raw_team}" if raw_team else raw_num
            else:
                team_display = raw_team
            rows.append({
                'Status': status,
                'Position': str(pos) if pos not in (None, '') else '',
                'Kart': str(_normalize_kart(raw_num)),
                'Team': team_display,
                'Last Lap': _ms_to_laptime(c.get('LastLaptime') or c.get('LastLap')),
                'Best Lap': _ms_to_laptime(c.get('BestLaptime') or c.get('BestLap')),
                'Gap': gap_str,
                'RunTime': _ms_to_runtime(c.get('RunningTime') or c.get('TotalTime')),
                'Pit Stops': str(_safe_int(c.get('PitStops') or c.get('NumberOfPitStops')) or 0),
            })

        def _pkey(r):
            try:
                return int(r['Position'])
            except (ValueError, TypeError):
                return 9999
        rows.sort(key=_pkey)
        return pd.DataFrame(rows)

    # ---- Pusher session ----------------------------------------------------------
    def _auth_subscribe(self, socket_id: str) -> Dict[str, str]:
        """Call /pusher/auth — succeeds only with Origin/Referer + at-pst/at-site."""
        assert self._cfg is not None
        headers = {
            'Origin': self._cfg.origin,
            'Referer': self._cfg.referer,
            'X-Requested-With': 'XMLHttpRequest',
            'at-site': self._cfg.site,
        }
        if self._cfg.at_pst:
            headers['at-pst'] = self._cfg.at_pst
        resp = self._http.post(
            self._cfg.auth_url,
            data={'socket_id': socket_id, 'channel_name': self._cfg.channel},
            headers=headers, cookies=self._cfg.cookies, timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    async def _pusher_loop(self) -> None:
        """One full lifecycle: connect → auth+subscribe → drain events until
        the websocket closes. Caller handles reconnection."""
        assert self._cfg is not None
        url = self._cfg.ws_url
        self.logger.info(f"Track {self.track_id}: connecting to Pusher {url}")
        async with websockets.connect(
            url,
            ssl=self._ssl_ctx,
            open_timeout=15,
            close_timeout=5,
            ping_interval=120,  # Pusher server side
            ping_timeout=30,
            max_size=2**22,
            origin=self._cfg.origin,
        ) as ws:
            self.is_connected = True
            self.websocket = ws  # so cleanup() can close it

            # 1) Wait for pusher:connection_established → grab socket_id
            socket_id: Optional[str] = None
            deadline = asyncio.get_event_loop().time() + 15
            while asyncio.get_event_loop().time() < deadline and not socket_id:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                env = self._parse_pusher_envelope(raw)
                if env and env.get('event') == 'pusher:connection_established':
                    inner = env.get('data') or {}
                    if isinstance(inner, str):
                        inner = json.loads(inner)
                    socket_id = inner.get('socket_id')
            if not socket_id:
                raise RuntimeError('No pusher:connection_established received')

            # 2) Auth and subscribe to the private channel
            auth = await asyncio.to_thread(self._auth_subscribe, socket_id)
            sub_payload = {
                'event': 'pusher:subscribe',
                'data': {
                    'auth': auth['auth'],
                    'channel': self._cfg.channel,
                },
            }
            if 'channel_data' in auth:
                sub_payload['data']['channel_data'] = auth['channel_data']
            await ws.send(json.dumps(sub_payload))
            self.logger.info(
                f"Track {self.track_id}: subscribe sent (socket_id={socket_id[:12]}…, "
                f"channel={self._cfg.channel})"
            )

            # 3) Snapshot first so deltas have somewhere to land
            await asyncio.to_thread(self._fetch_snapshot)
            await asyncio.to_thread(self._ingest_current_state)

            # 4) Drain events
            async for raw in ws:
                env = self._parse_pusher_envelope(raw)
                if not env:
                    continue
                ev = env.get('event')
                if ev == 'pusher_internal:subscription_succeeded':
                    self.logger.info(
                        f"Track {self.track_id}: subscription succeeded on {self._cfg.channel}"
                    )
                    continue
                if ev == 'pusher:error':
                    self.logger.warning(f"Track {self.track_id}: pusher error: {env.get('data')}")
                    continue
                if ev == 'pusher:ping':
                    await ws.send(json.dumps({'event': 'pusher:pong', 'data': {}}))
                    continue
                # Data events ride on our channel.
                data = env.get('data')
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        data = {'raw': data}
                if ev == 'update':
                    if self._apply_delta(data or {}):
                        await asyncio.to_thread(self._ingest_current_state)
                elif ev == 'refresh':
                    self.logger.info(f"Track {self.track_id}: refresh event — refetching snapshot")
                    await asyncio.to_thread(self._fetch_snapshot)
                    await asyncio.to_thread(self._ingest_current_state)
                elif ev == 'new_session':
                    self.logger.info(f"Track {self.track_id}: new_session event — resetting")
                    self.competitors = {}
                    self.last_sequence = None
                    # Force the session-id rollover machinery in
                    # check_and_update_session: clear cached leader lap so the
                    # next snapshot's lap=1 (or fresh data after a gap) opens a
                    # new session_id rather than appending to the old one.
                    self.session_ended = True
                    await asyncio.to_thread(self._fetch_snapshot)
                    await asyncio.to_thread(self._ingest_current_state)

    def _parse_pusher_envelope(self, raw) -> Optional[Dict[str, Any]]:
        """Pusher messages are JSON envelopes: {event, data, channel?}."""
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', 'replace')
        try:
            return json.loads(raw)
        except Exception:
            self.logger.debug(f"Track {self.track_id}: non-JSON frame ({len(raw)} bytes)")
            return None

    def _ingest_current_state(self) -> None:
        """One Apex-tick-equivalent: build standings DF → session id → store +
        broadcast. Mirrors the inner `if not df.empty:` block of
        TrackSpecificParser.start_monitoring."""
        df = self.get_current_standings()
        if df.empty:
            return
        leader_gap = ''
        if 'Position' in df.columns and 'Gap' in df.columns:
            leader_row = df[df['Position'].astype(str) == '1']
            if not leader_row.empty:
                leader_gap = leader_row.iloc[0].get('Gap', '')
        session_id = self.check_and_update_session(leader_gap)
        if session_id is None:
            # Mid-session start — open one (same heuristic as Apex parser).
            self.logger.info(
                f"Track {self.track_id}: AlphaHub mid-session start, opening session"
            )
            session_id = self.create_new_session()
            self.current_session_id = session_id
            self.current_leader_lap = 1
            self.session_ended = False
        self.session_active_status = True
        self.last_data_time = datetime.now()
        self.store_lap_data(session_id, df)

    # ---- public entrypoint -------------------------------------------------------
    async def start_monitoring(self, ws_url: str) -> None:
        """`ws_url` here is actually the live PAGE URL (alpharacehub.com/<site>/live).
        We scrape it for the Pusher config, then run the pusher loop with retries.
        """
        # Spin up the same session monitor thread the Apex parser uses.
        import threading
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_stop_event.clear()
            self.monitor_thread = threading.Thread(
                target=self.start_session_monitoring,
                name=f"SessionMonitor-Track{self.track_id}",
                daemon=True,
            )
            self.monitor_thread.start()
            self.logger.info(
                f"Started session monitoring thread for track {self.track_id} "
                f"({self.track_name}) [AlphaHub]"
            )

        # Stagger first connect across all AlphaHub parsers so we don't slam
        # alpharacehub.com with N simultaneous discovery GETs on startup
        # (every instance got a sequential index in __init__).
        if self._startup_index > 0:
            stagger = self._startup_index * self._START_STAGGER_SECONDS
            self.logger.info(
                f"Track {self.track_id}: AlphaHub startup stagger {stagger:.1f}s "
                f"(index {self._startup_index})"
            )
            await asyncio.sleep(stagger)

        # Start at 15s, not 5s — a 429 storm needs more breathing room than a
        # transient websocket drop. The 5s default is fine after a successful
        # connect; we reset it below.
        reconnect_delay = 15
        while True:
            try:
                # Re-discover the config every time we reconnect — the at-pst
                # token is per-session and rotates on the page; refreshing here
                # is what avoids the "401 after a few hours" failure mode.
                self._cfg = await asyncio.to_thread(
                    lambda: discover_config(ws_url, session=self._http, logger=self.logger)
                )
            except Exception as e:
                self.logger.error(
                    f"Track {self.track_id}: AlphaHub config discovery failed: {e}"
                )
                self.is_connected = False
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 300)
                continue

            try:
                await self._pusher_loop()
                reconnect_delay = 15  # reset to the cautious default
            except asyncio.CancelledError:
                self.logger.info(f"Track {self.track_id}: AlphaHub parser cancelled")
                raise
            except Exception as e:
                self.logger.warning(f"Track {self.track_id}: Pusher loop ended: {e}")
            finally:
                self.is_connected = False
                self.websocket = None

            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 300)
