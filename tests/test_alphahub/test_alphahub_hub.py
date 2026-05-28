"""Unit tests for the shared-connection AlphaHub hub.

The hub centralizes Pusher I/O across all alphahub tracks: one shared
requests.Session, one shared Pusher WebSocket, N channel subscriptions.
These tests verify the wiring without spinning up real WebSockets:
  * channel registration is idempotent and round-trips track_id + name
  * the hub scrapes the live page ONLY ONCE regardless of channel count
  * per-channel events dispatch to the right AlphaHubChannel.on_event
  * one channel's auth failure doesn't kill the rest
  * AlphaHubChannel preserves the surface MultiTrackManager expects
    (track_name, get_current_standings, is_connected, cleanup)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from alphahub_hub import AlphaHubChannel, AlphaHubHub
from alphahub_parser import AlphaHubConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_db_paths(tmp_path: Path) -> Path:
    from multi_track_manager import MultiTrackManager
    mgr = MultiTrackManager(socketio=None)
    mgr.get_database_path = lambda tid: str(tmp_path / f'race_data_track_{tid}.db')
    for tid in (701, 702, 703):
        mgr.initialize_track_database(tid)
    return tmp_path


def _make_channel(tmp_path, track_id, site, suffix='live'):
    db_path = str(tmp_path / f'race_data_track_{track_id}.db')
    ch_name = f'private-{site}{suffix}'
    page = f'https://www.alpharacehub.com/{site}/live'
    return AlphaHubChannel(
        track_id, f'Track {track_id}', db_path,
        channel_name=ch_name, page_url=page,
        socketio=None, manager=None,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_adds_to_both_indices(self, fresh_db_paths):
        hub = AlphaHubHub()
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        hub.register(ch)
        assert hub.tracks[701] is ch
        assert hub.channels['private-buckmorelive'] is ch
        assert ch.hub is hub

    def test_register_is_idempotent_per_channel_name(self, fresh_db_paths):
        hub = AlphaHubHub()
        ch1 = _make_channel(fresh_db_paths, 701, 'buckmore')
        ch2 = _make_channel(fresh_db_paths, 702, 'buckmore')   # same channel
        hub.register(ch1)
        hub.register(ch2)
        # The channels-by-name index keeps only the latest registration —
        # that's fine; a duplicate channel name is a config error caller-side.
        assert hub.channels['private-buckmorelive'] is ch2

    def test_unregister_removes_both(self, fresh_db_paths):
        hub = AlphaHubHub()
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        hub.register(ch)
        hub.unregister(701)
        assert 701 not in hub.tracks
        assert 'private-buckmorelive' not in hub.channels


# ---------------------------------------------------------------------------
# Single-scrape discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_ensure_app_cfg_scrapes_once_then_caches(self, fresh_db_paths):
        hub = AlphaHubHub()
        for tid, site in ((701, 'buckmore'), (702, 'whiltonmill'), (703, 'rye')):
            hub.register(_make_channel(fresh_db_paths, tid, site))

        fake_cfg = AlphaHubConfig(
            page_url='https://www.alpharacehub.com/buckmore/live',
            pusher_key='k', pusher_cluster='eu', site='buckmore',
            channel_suffix='live', at_pst=None,
        )

        with patch('alphahub_hub.discover_config', return_value=fake_cfg) as m:
            hub._ensure_app_cfg()
            hub._ensure_app_cfg()
            hub._ensure_app_cfg()
        # Three channels registered, three _ensure calls — but only ONE actual
        # scrape. That's the whole point of the refactor.
        assert m.call_count == 1
        assert hub._app_cfg is fake_cfg

    def test_ensure_app_cfg_raises_when_no_channels(self):
        hub = AlphaHubHub()
        with pytest.raises(RuntimeError, match='no channels'):
            hub._ensure_app_cfg()


# ---------------------------------------------------------------------------
# Per-channel event dispatch
# ---------------------------------------------------------------------------

class TestEventDispatch:
    @pytest.mark.asyncio
    async def test_envelope_routed_to_named_channel(self, fresh_db_paths):
        hub = AlphaHubHub()
        ch_a = _make_channel(fresh_db_paths, 701, 'buckmore')
        ch_b = _make_channel(fresh_db_paths, 702, 'whiltonmill')
        hub.register(ch_a)
        hub.register(ch_b)

        received_a = []
        received_b = []
        async def fake_on_event(channel, event, data):
            (received_a if channel.track_id == 701 else received_b).append((event, data))
        # Patch each channel's on_event independently
        ch_a.on_event = lambda event, data: fake_on_event(ch_a, event, data)
        ch_b.on_event = lambda event, data: fake_on_event(ch_b, event, data)

        # Hand-craft a pusher envelope for channel B only.
        await hub._handle_envelope({
            'event': 'update',
            'channel': 'private-whiltonmilllive',
            'data': {'Sequence': 1, 'Competitors': []},
        })
        assert received_a == []
        assert received_b == [('update', {'Sequence': 1, 'Competitors': []})]

    @pytest.mark.asyncio
    async def test_envelope_for_unknown_channel_is_ignored(self, fresh_db_paths):
        hub = AlphaHubHub()
        # No envelope-handler should raise on an unrecognized channel name
        # (Pusher sometimes echoes events for channels we didn't subscribe to).
        await hub._handle_envelope({
            'event': 'update',
            'channel': 'private-noonelive',
            'data': {},
        })  # must not raise

    @pytest.mark.asyncio
    async def test_subscription_succeeded_marks_channel_connected(self, fresh_db_paths):
        hub = AlphaHubHub()
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        hub.register(ch)
        assert ch.is_connected is False
        await hub._handle_envelope({
            'event': 'pusher_internal:subscription_succeeded',
            'channel': 'private-buckmorelive',
        })
        assert ch.is_connected is True
        assert 'private-buckmorelive' in hub._subscribed


# ---------------------------------------------------------------------------
# AlphaHubChannel — compatibility surface
# ---------------------------------------------------------------------------

class TestChannelSurface:
    def test_get_current_standings_empty_when_no_data(self, fresh_db_paths):
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        df = ch.get_current_standings()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_get_current_standings_builds_rows_from_competitors(self, fresh_db_paths):
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        ch.competitors = {
            '6': {'CompetitorNumber': 6, 'Position': 1, 'CompetitorName': 'A',
                  'NumberOfLaps': 10, 'LastLaptime': 75000, 'BestLaptime': 74000,
                  'TakenChequered': False, 'InPit': False},
            '7': {'CompetitorNumber': 7, 'Position': 2, 'CompetitorName': 'B',
                  'NumberOfLaps': 10, 'LastLaptime': 76000, 'BestLaptime': 75000,
                  'TakenChequered': False, 'InPit': True},
        }
        df = ch.get_current_standings()
        assert list(df['Kart']) == ['6', '7']
        assert list(df['Status']) == ['On Track', 'Pit-in']
        assert df.iloc[0]['Last Lap'] == '1:15.000'

    def test_apply_delta_merges_in_place(self, fresh_db_paths):
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        ch.competitors = {'1': {'CompetitorNumber': 1, 'NumberOfLaps': 5}}
        changed = ch._apply_delta({
            'Sequence': 10,
            'Competitors': [{'CompetitorNumber': 1, 'NumberOfLaps': 6}],
        })
        assert changed is True
        assert ch.competitors['1']['NumberOfLaps'] == 6
        assert ch.last_sequence == 10

    def test_apply_delta_ignores_stale_sequence(self, fresh_db_paths):
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        ch.last_sequence = 50
        changed = ch._apply_delta({
            'Sequence': 30,
            'Competitors': [{'CompetitorNumber': 1, 'NumberOfLaps': 99}],
        })
        assert changed is False
        assert '1' not in ch.competitors

    @pytest.mark.asyncio
    async def test_on_event_update_triggers_ingest(self, fresh_db_paths):
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        called = []
        ch._ingest_current_state = lambda: called.append(True)
        await ch.on_event('update', {
            'Sequence': 1,
            'Competitors': [{'CompetitorNumber': 6, 'Position': 1,
                             'CompetitorName': 'A', 'NumberOfLaps': 1}],
        })
        assert called == [True]

    @pytest.mark.asyncio
    async def test_on_event_new_session_resets_state(self, fresh_db_paths):
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        ch.competitors = {'1': {'CompetitorNumber': 1}}
        ch.last_sequence = 99
        ch.session_ended = False
        await ch.on_event('new_session', {})
        assert ch.competitors == {}
        assert ch.last_sequence is None
        assert ch.session_ended is True

    @pytest.mark.asyncio
    async def test_on_event_refresh_is_noop_in_hub_mode(self, fresh_db_paths):
        # The hub deliberately doesn't fetch snapshots to stay polite. A
        # refresh event should be logged-and-ignored, NOT trigger HTTP.
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        ch.competitors = {'1': {'CompetitorNumber': 1}}
        await ch.on_event('refresh', {})
        assert ch.competitors == {'1': {'CompetitorNumber': 1}}   # unchanged

    def test_channel_exposes_parser_compat_surface(self, fresh_db_paths):
        # MultiTrackManager.get_all_tracks_status reads these attributes off
        # whatever is in manager.parsers[track_id]. The channel MUST expose
        # them or the dashboard breaks.
        ch = _make_channel(fresh_db_paths, 701, 'buckmore')
        for attr in ('track_name', 'is_connected', 'session_active_status',
                     'last_data_time', 'current_session_id',
                     'get_current_standings', 'cleanup'):
            assert hasattr(ch, attr), f"channel missing required attr {attr!r}"


# ---------------------------------------------------------------------------
# One bad auth doesn't kill the rest
# ---------------------------------------------------------------------------

class TestPartialAuthFailure:
    @pytest.mark.asyncio
    async def test_one_channel_auth_failure_does_not_abort_others(self, fresh_db_paths):
        hub = AlphaHubHub()
        for tid, site in ((701, 'buckmore'), (702, 'whiltonmill'),
                          (703, 'rye')):
            hub.register(_make_channel(fresh_db_paths, tid, site))
        hub._app_cfg = AlphaHubConfig(
            page_url='https://x/y/live',
            pusher_key='k', pusher_cluster='eu', site='buckmore',
            channel_suffix='live', at_pst=None,
        )
        sent = []
        class _FakeWS:
            async def send(self, payload): sent.append(payload)
        hub._ws = _FakeWS()

        import requests
        def fake_auth(ch_name, sid):
            if 'whiltonmill' in ch_name:
                err = requests.exceptions.HTTPError('401')
                err.response = MagicMock(status_code=401)
                raise err
            return {'auth': f'tok-{ch_name}'}
        hub._auth_with_gate = fake_auth

        await hub._subscribe_all('socket-xyz')
        # Two successful subscribes (buckmore + rye), one auth failure
        # (whiltonmill) — but the loop kept going.
        subscribed_channels = [s for s in sent if 'pusher:subscribe' in s]
        assert len(subscribed_channels) == 2
        assert any('buckmorelive' in s for s in subscribed_channels)
        assert any('ryelive' in s for s in subscribed_channels)
        assert all('whiltonmilllive' not in s for s in subscribed_channels)
