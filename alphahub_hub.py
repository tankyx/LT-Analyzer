"""Shared-connection AlphaHub driver.

Why this exists (architectural):
  AlphaHub data flows over Pusher — a SaaS pub/sub layer on top of WebSocket.
  Pusher itself supports many channels per connection, but each private
  channel subscription requires an HMAC-signed token from the venue's own
  auth endpoint (alpharacehub.com/pusher/auth). Cloudflare sits in front
  of alpharacehub.com and rate-limits requests per source IP.

  The old design ran one full AlphaHubParser per track: each had its own
  HTTP session, scraped the live page, did /pusher/auth, fetched a snapshot,
  and opened its own Pusher WebSocket. N tracks = N page scrapes + N auths +
  N snapshots + N websockets. At N=29 this trivially trips Cloudflare and
  drops us in a multi-hour block.

  This module replaces that with:
    * ONE shared requests.Session (one cookie jar — Cloudflare sees a single
      stable "browser session")
    * ONE shared Pusher WebSocket (Pusher multiplexes all channels)
    * ONE page scrape per process to seed the cookies + harvest the Pusher
      app config (key/cluster — identical across every alpharacehub venue)
    * N per-channel auth POSTs, paced gently through the existing
      _HTTP_GATE so even bursts stay polite
    * Per-track AlphaHubChannel state holders that look just like the old
      parser to MultiTrackManager (start_monitoring, get_current_standings,
      cleanup, is_connected, track_name, etc.) — pure compatibility shim.

  Net effect: 29 tracks generate ~30 alpharacehub HTTP requests at process
  startup spread over a few minutes, then zero ongoing HTTP load. Same as
  Apex from Cloudflare's perspective.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import requests
import websockets

from alphahub_parser import (
    AlphaHubConfig,
    TrackSpecificParser,
    _DEFAULT_HEADERS,
    _derive_status,
    _gate_acquire,
    _ms_to_gap,
    _ms_to_laptime,
    _ms_to_runtime,
    _normalize_kart,
    _safe_int,
    _DIGIT_RE,
    _looks_in_pit,
    discover_config,
)


_module_logger = logging.getLogger(__name__)


class AlphaHubHub:
    """Process-singleton-ish driver for all AlphaHub tracks. Owns the shared
    HTTP session, the shared Pusher WebSocket, and the registry of per-track
    channels."""

    def __init__(self, socketio=None, manager=None):
        self.socketio = socketio
        self.manager = manager
        self.logger = _module_logger
        self.channels: Dict[str, 'AlphaHubChannel'] = {}   # channel_name -> channel
        self.tracks: Dict[int, 'AlphaHubChannel'] = {}     # track_id     -> channel
        self._http = requests.Session()
        self._http.headers.update(_DEFAULT_HEADERS)
        self._ssl_ctx = ssl.create_default_context()
        self._lock = asyncio.Lock()
        self._ws = None
        self._socket_id: Optional[str] = None
        # Pusher app config (key + cluster) is identical across every
        # alpharacehub venue we've inspected (Buckmore, Whilton, etc.).
        # Discover once per process from any registered channel's page URL.
        self._app_cfg: Optional[AlphaHubConfig] = None
        self._run_task: Optional[asyncio.Task] = None
        # Per-channel subscription state — set true after Pusher sends
        # subscription_succeeded; cleared on reconnect.
        self._subscribed: set[str] = set()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, channel: 'AlphaHubChannel') -> None:
        """Add a track's channel to the hub. Idempotent on the channel name."""
        self.tracks[channel.track_id] = channel
        self.channels[channel.channel_name] = channel
        channel.hub = self
        self.logger.info(
            f"AlphaHubHub: registered track {channel.track_id} "
            f"({channel.track_name}, channel={channel.channel_name})"
        )

    def unregister(self, track_id: int) -> None:
        ch = self.tracks.pop(track_id, None)
        if ch:
            self.channels.pop(ch.channel_name, None)
            self._subscribed.discard(ch.channel_name)
            self.logger.info(f"AlphaHubHub: unregistered track {track_id}")

    # ------------------------------------------------------------------
    # Discovery (one page scrape per process)
    # ------------------------------------------------------------------
    def _ensure_app_cfg(self) -> AlphaHubConfig:
        """Block until self._app_cfg is populated. Uses the first registered
        channel's page URL — every alpharacehub venue serves the same Pusher
        app config, so any page works."""
        if self._app_cfg is not None:
            return self._app_cfg
        if not self.channels:
            raise RuntimeError("AlphaHubHub: no channels registered; nothing to scrape")
        seed_channel = next(iter(self.channels.values()))
        self.logger.info(
            f"AlphaHubHub: scraping {seed_channel.page_url} to seed shared "
            f"Pusher config + cookies"
        )
        cfg = discover_config(seed_channel.page_url, session=self._http,
                              logger=self.logger)
        self._app_cfg = cfg
        self.logger.info(
            f"AlphaHubHub: shared Pusher app config — key={cfg.pusher_key[:8]}… "
            f"cluster={cfg.pusher_cluster} cookies={sorted(self._http.cookies.get_dict().keys())}"
        )
        return cfg

    def _auth_subscribe(self, channel_name: str, socket_id: str) -> Dict[str, str]:
        """POST /pusher/auth for one channel through the shared HTTP session.
        Caller has already acquired the HTTP gate."""
        cfg = self._app_cfg
        assert cfg is not None
        # Some venues require an `at-site` header that matches the channel's
        # site slug. Derive from the channel name (private-<site><suffix>).
        site = channel_name.removeprefix('private-')
        for suffix in ('live', 'rooms'):
            if site.endswith(suffix):
                site = site[: -len(suffix)]
                break
        headers = {
            'Origin': cfg.origin,
            'Referer': cfg.referer,
            'X-Requested-With': 'XMLHttpRequest',
            'at-site': site,
        }
        if cfg.at_pst:
            headers['at-pst'] = cfg.at_pst
        resp = self._http.post(
            cfg.auth_url,
            data={'socket_id': socket_id, 'channel_name': channel_name},
            headers=headers, timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Pusher loop
    # ------------------------------------------------------------------
    async def _pusher_loop(self) -> None:
        """One full lifecycle of the shared Pusher WebSocket. Reconnects are
        handled by run()."""
        cfg = await asyncio.to_thread(self._ensure_app_cfg)
        self.logger.info(f"AlphaHubHub: connecting to Pusher {cfg.ws_url}")
        async with websockets.connect(
            cfg.ws_url,
            ssl=self._ssl_ctx,
            open_timeout=15,
            close_timeout=5,
            ping_interval=120,
            ping_timeout=30,
            max_size=2 ** 22,
            origin=cfg.origin,
        ) as ws:
            self._ws = ws
            self._subscribed.clear()

            # 1) Wait for pusher:connection_established → socket_id
            socket_id: Optional[str] = None
            deadline = asyncio.get_event_loop().time() + 15
            while asyncio.get_event_loop().time() < deadline and not socket_id:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                env = self._parse_envelope(raw)
                if env and env.get('event') == 'pusher:connection_established':
                    inner = env.get('data') or {}
                    if isinstance(inner, str):
                        inner = json.loads(inner)
                    socket_id = inner.get('socket_id')
            if not socket_id:
                raise RuntimeError('No pusher:connection_established received')
            self._socket_id = socket_id
            self.logger.info(
                f"AlphaHubHub: socket_id={socket_id[:12]}…, subscribing to "
                f"{len(self.channels)} channels"
            )

            # 2) Subscribe to all channels, paced through the HTTP gate so we
            # never burst alpharacehub.com.
            asyncio.create_task(self._subscribe_all(socket_id))

            # 3) Drain events forever — dispatch to per-channel handlers.
            async for raw in ws:
                env = self._parse_envelope(raw)
                if not env:
                    continue
                await self._handle_envelope(env)

    async def _subscribe_all(self, socket_id: str) -> None:
        """Walk every registered channel and subscribe one by one. Each
        auth POST acquires the HTTP gate (3s min spacing) so even at N=29
        we send roughly 1 auth/3s — well under Cloudflare's threshold."""
        for ch_name, channel in list(self.channels.items()):
            try:
                auth = await asyncio.to_thread(
                    self._auth_with_gate, ch_name, socket_id
                )
                if self._ws is None:
                    return
                sub_payload = {
                    'event': 'pusher:subscribe',
                    'data': {'auth': auth['auth'], 'channel': ch_name},
                }
                if 'channel_data' in auth:
                    sub_payload['data']['channel_data'] = auth['channel_data']
                await self._ws.send(json.dumps(sub_payload))
                channel.mark_subscribing()
            except requests.exceptions.HTTPError as e:
                code = getattr(e.response, 'status_code', None)
                self.logger.warning(
                    f"AlphaHubHub: auth failed for {ch_name} (status {code}); "
                    f"will retry on next reconnect"
                )
                # Don't abort the loop — other channels may still succeed.
            except Exception as e:
                self.logger.warning(
                    f"AlphaHubHub: subscribe failed for {ch_name}: {e}"
                )

    def _auth_with_gate(self, ch_name: str, socket_id: str):
        _gate_acquire()
        return self._auth_subscribe(ch_name, socket_id)

    async def _handle_envelope(self, env: Dict[str, Any]) -> None:
        ev = env.get('event')
        ch_name = env.get('channel')
        if ev == 'pusher:ping':
            if self._ws:
                await self._ws.send(json.dumps({'event': 'pusher:pong', 'data': {}}))
            return
        if ev == 'pusher:error':
            self.logger.warning(f"AlphaHubHub: pusher error: {env.get('data')}")
            return
        # Channel-scoped events
        channel = self.channels.get(ch_name) if ch_name else None
        if channel is None:
            return
        if ev == 'pusher_internal:subscription_succeeded':
            self._subscribed.add(ch_name)
            channel.mark_subscribed()
            return
        data = env.get('data')
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = {'raw': data}
        try:
            await channel.on_event(ev, data or {})
        except Exception as e:
            self.logger.warning(
                f"AlphaHubHub: channel {ch_name} handler raised: {e}"
            )

    def _parse_envelope(self, raw) -> Optional[Dict[str, Any]]:
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', 'replace')
        try:
            return json.loads(raw)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """Maintain the shared Pusher WebSocket forever. Exponential backoff
        on disconnect/error."""
        delay = 15
        while True:
            try:
                await self._pusher_loop()
                delay = 15
            except asyncio.CancelledError:
                self.logger.info("AlphaHubHub: cancelled")
                raise
            except Exception as e:
                self.logger.warning(f"AlphaHubHub: loop ended: {e}")
            finally:
                self._ws = None
                self._socket_id = None
                self._subscribed.clear()
                # Mark all channels disconnected so the dashboard reflects it.
                for ch in self.channels.values():
                    ch.is_connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

    async def cleanup(self) -> None:
        """Close the shared WebSocket. The asyncio task is cancelled by the
        manager."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None


class AlphaHubChannel(TrackSpecificParser):
    """Per-track state holder — subclasses TrackSpecificParser so it inherits
    the per-track DB plumbing (session id rollover, store_lap_data,
    track_update broadcasts) AND so it presents the same surface the rest of
    the system expects (track_name, get_current_standings, is_connected, …).

    Unlike AlphaHubParser, this class does NOT own a Pusher connection. The
    hub feeds it events via on_event(). start_monitoring is a no-op that
    just keeps the asyncio task alive — the manager spawns one per track for
    its bookkeeping, but only ONE hub task does the real I/O work."""

    def __init__(self, track_id: int, track_name: str, db_path: str,
                 channel_name: str, page_url: str,
                 socketio=None, manager=None):
        super().__init__(track_id, track_name, db_path,
                         socketio=socketio, manager=manager)
        self.channel_name = channel_name
        self.page_url = page_url
        self.competitors: Dict[str, Dict[str, Any]] = {}
        self.last_sequence: Optional[int] = None
        self.hub: Optional[AlphaHubHub] = None
        # is_connected reflects "this channel is subscribed and receiving
        # data" — independent of whether the parent hub's WebSocket is up.
        self.is_connected = False

    # ----- standings + ingest (lifted from old AlphaHubParser) ---------
    def get_current_standings(self) -> pd.DataFrame:
        rows = []
        for num, c in self.competitors.items():
            pos = c.get('Position') or c.get('Rank') or c.get('Pos')
            gap_ms = _safe_int(c.get('GapToFirst') or c.get('GapToLeader'))
            laps_to_first = _safe_int(c.get('LapsToFirst'))
            if laps_to_first and laps_to_first > 0:
                gap_str = f"Tour {laps_to_first}"
            elif gap_ms:
                gap_str = _ms_to_gap(gap_ms)
            else:
                gap_str = ''
            status = _derive_status(c)
            raw_team = str(c.get('CompetitorName') or c.get('TeamName')
                           or c.get('Name') or c.get('Team') or '').strip()
            raw_num = str(num).strip()
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

    def _apply_delta(self, payload: Dict[str, Any]) -> bool:
        seq = _safe_int(payload.get('Sequence'))
        if seq is not None and self.last_sequence is not None and seq <= self.last_sequence:
            return False
        if (seq is not None and self.last_sequence is not None
                and seq > self.last_sequence + 50):
            # Big sequence jump — we'd need a snapshot to resync. Without
            # snapshot fetching (the hub deliberately avoids them on startup
            # to stay polite), we just accept the drift and keep merging.
            self.logger.info(
                f"Track {self.track_id}: sequence jump {self.last_sequence}→{seq}; "
                f"continuing without snapshot resync (hub mode)"
            )
        comps = payload.get('Competitors') or payload.get('competitors') or []
        changed = False
        for c in comps:
            num = str(c.get('CompetitorNumber') or c.get('Number')
                      or c.get('Kart') or '')
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

    def _ingest_current_state(self) -> None:
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
            session_id = self.create_new_session()
            self.current_session_id = session_id
            self.current_leader_lap = 1
            self.session_ended = False
        self.session_active_status = True
        self.last_data_time = datetime.now()
        self.store_lap_data(session_id, df)

    # ----- event dispatch from the hub ---------------------------------
    async def on_event(self, event: str, data: Dict[str, Any]) -> None:
        """Called by AlphaHubHub when an envelope arrives on this channel."""
        if event == 'update':
            if self._apply_delta(data):
                await asyncio.to_thread(self._ingest_current_state)
        elif event == 'refresh':
            # In hub mode we DON'T fetch the snapshot — the whole point is to
            # avoid HTTP storms. Deltas alone are eventually consistent.
            self.logger.debug(f"Track {self.track_id}: refresh event ignored (hub mode)")
        elif event == 'new_session':
            self.logger.info(f"Track {self.track_id}: new_session event — resetting state")
            self.competitors = {}
            self.last_sequence = None
            self.session_ended = True

    def mark_subscribing(self) -> None:
        """Called by the hub right after sending pusher:subscribe."""
        self.logger.info(
            f"Track {self.track_id}: subscribe sent on shared connection "
            f"(channel={self.channel_name})"
        )

    def mark_subscribed(self) -> None:
        """Called by the hub when pusher_internal:subscription_succeeded arrives."""
        self.is_connected = True
        self.session_active_status = True
        self.logger.info(
            f"Track {self.track_id}: subscription succeeded on {self.channel_name}"
        )

    # ----- compatibility with MultiTrackManager ------------------------
    async def start_monitoring(self, ws_url: str) -> None:
        """No-op for hub-managed channels. The hub owns the WebSocket loop.
        Returning here would cause MultiTrackManager.start_track_parser to
        complete the await and the task would end — so we sleep forever
        instead, holding the task slot for bookkeeping. Cancellation
        propagates normally via cleanup."""
        # Spin up the session monitor thread (same as the parent does) so the
        # session_status events still fire when data goes stale.
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_stop_event.clear()
            self.monitor_thread = threading.Thread(
                target=self.start_session_monitoring,
                name=f"SessionMonitor-Track{self.track_id}",
                daemon=True,
            )
            self.monitor_thread.start()
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    async def cleanup(self) -> None:
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_stop_event.set()
            self.monitor_thread.join(timeout=5)
        if self.hub is not None:
            self.hub.unregister(self.track_id)
        # Don't close any websocket — that's the hub's job.


# Keep the local import here, after class definition, to avoid a circular
# import when alphahub_parser pulls TrackSpecificParser back through this
# file in some test harnesses.
import threading  # noqa: E402
