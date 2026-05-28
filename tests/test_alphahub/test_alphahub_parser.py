"""Unit tests for the AlphaHub parser: format helpers, snapshot/delta merge,
standings DataFrame, config discovery, and channel-name construction.

These tests touch zero network: discover_config takes a fake `requests.Session`,
and the snapshot/delta methods are exercised by setting `parser._cfg` + a
monkey-patched `_http`. The parser's full Pusher lifecycle is covered by the
live verification (Buckmore), not by mocking out `websockets`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from alphahub_parser import (
    AlphaHubConfig,
    AlphaHubParser,
    _looks_in_pit,
    _ms_to_gap,
    _ms_to_laptime,
    _ms_to_runtime,
    _normalize_kart,
    _safe_int,
    discover_config,
)


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

class TestFormatHelpers:
    @pytest.mark.parametrize("ms,expected", [
        (0, ''),
        (None, ''),
        (-1, ''),
        (1000, '1.000'),
        (1234, '1.234'),
        (59999, '59.999'),
        (60000, '1:00.000'),
        (83456, '1:23.456'),
        (74099, '1:14.099'),
    ])
    def test_ms_to_laptime(self, ms, expected):
        assert _ms_to_laptime(ms) == expected

    def test_ms_to_laptime_bad_input(self):
        assert _ms_to_laptime('not a number') == ''
        assert _ms_to_laptime({}) == ''

    @pytest.mark.parametrize("ms,expected", [
        (0, ''),
        (None, ''),
        (1000, '00:01'),
        (62000, '01:02'),
        (3600_000, '60:00'),
    ])
    def test_ms_to_runtime(self, ms, expected):
        assert _ms_to_runtime(ms) == expected

    @pytest.mark.parametrize("ms,expected", [
        (0, ''),
        (None, ''),
        (2345, '+2.345'),
        (12_500, '+12.500'),
    ])
    def test_ms_to_gap(self, ms, expected):
        assert _ms_to_gap(ms) == expected

    @pytest.mark.parametrize("payload,expected", [
        ({'InPit': True}, True),
        ({'IsInPit': 1}, True),
        ({'PitIn': True}, True),
        ({'InPits': True}, True),
        ({'Status': 'Pit-in'}, True),
        ({'Status': 'On Track'}, False),
        ({}, False),
    ])
    def test_looks_in_pit(self, payload, expected):
        assert _looks_in_pit(payload) is expected

    def test_safe_int(self):
        assert _safe_int(42) == 42
        assert _safe_int('17') == 17
        assert _safe_int(None) is None
        assert _safe_int('abc') is None


class TestNormalizeKart:
    def test_all_digits_passes_through(self):
        # Buckmore-style numeric IDs are preserved exactly.
        assert _normalize_kart('17') == 17
        assert _normalize_kart(23) == 23
        assert _normalize_kart('1') == 1

    def test_empty_returns_zero(self):
        assert _normalize_kart('') == 0
        assert _normalize_kart(None) == 0

    def test_alpha_prefixed_is_deterministic_and_distinct(self):
        # Whilton Mill cadet class IDs ("C1", "C12") must map to distinct ints.
        c1_a = _normalize_kart('C1')
        c1_b = _normalize_kart('C1')
        c12 = _normalize_kart('C12')
        assert c1_a == c1_b                # stable
        assert c1_a != c12                 # distinct
        assert c1_a >= 1_000_000           # above the natural 1-999 numeric range
        assert c12 >= 1_000_000

    def test_does_not_collide_with_numeric_ids(self):
        # An alpha ID must never produce a value in the 1-999 native range.
        for label in ('C1', 'K1', 'C12', 'A99', 'X'):
            assert _normalize_kart(label) >= 1_000_000

    def test_md5_based_not_python_hash(self):
        # Python hash() is salted per-process — verify our value matches the
        # actual md5 derivation so it's stable across restarts.
        import hashlib
        digest = hashlib.md5(b'C1').hexdigest()
        expected = 1_000_000 + (int(digest[:7], 16) % 9_000_000)
        assert _normalize_kart('C1') == expected


# ---------------------------------------------------------------------------
# AlphaHubConfig URL construction
# ---------------------------------------------------------------------------

class TestAlphaHubConfig:
    def _cfg(self, **kw):
        defaults = dict(
            page_url='https://www.alpharacehub.com/buckmore/live',
            pusher_key='3aaffebc8193ea83cb2f',
            pusher_cluster='eu',
            site='buckmore',
            channel_suffix='live',
            at_pst='token-xyz',
        )
        defaults.update(kw)
        return AlphaHubConfig(**defaults)

    def test_channel_name_matches_live_capture(self):
        # Verified live (Buckmore): private-<site><channelSuffix>
        assert self._cfg().channel == 'private-buckmorelive'

    def test_channel_suffix_with_colon_prefix(self):
        # Captured payload sometimes uses ":live" as the suffix; we don't
        # strip it because Pusher matches the channel name exactly.
        cfg = self._cfg(channel_suffix=':live')
        assert cfg.channel == 'private-buckmore:live'

    def test_origin_strips_path(self):
        assert self._cfg().origin == 'https://www.alpharacehub.com'

    def test_endpoint_urls(self):
        c = self._cfg()
        assert c.snapshot_url == 'https://www.alpharacehub.com/api/v1/buckmore/live/current'
        assert c.auth_url == 'https://www.alpharacehub.com/pusher/auth'
        assert c.ws_url.startswith('wss://ws-eu.pusher.com/app/3aaffebc8193ea83cb2f')
        assert 'protocol=7' in c.ws_url


# ---------------------------------------------------------------------------
# Config discovery (HTML scraping; no network)
# ---------------------------------------------------------------------------

class TestDiscoverConfig:
    def _mock_session(self, body: str, cookies: dict | None = None,
                      url: str = 'https://www.alpharacehub.com/buckmore/live'):
        sess = MagicMock()
        # `.headers.update(...)` is called inside discover_config — make it a no-op.
        sess.headers = MagicMock()
        # Cookies behave like requests.cookies.RequestsCookieJar (.get, .get_dict)
        cookies = cookies or {}
        sess.cookies.get = lambda name, default=None: cookies.get(name, default)
        sess.cookies.get_dict = lambda: dict(cookies)
        resp = MagicMock()
        resp.text = body
        resp.raise_for_status = MagicMock()
        sess.get = MagicMock(return_value=resp)
        return sess

    def test_extracts_pusher_key_and_site(self):
        body = """
        <script>
          var pusherKey = '3aaffebc8193ea83cb2f';
          var pusherCluster = 'eu';
          var siteSlug = 'buckmore';
          var channelSuffix = 'live';
        </script>
        """
        sess = self._mock_session(body)
        cfg = discover_config(
            'https://www.alpharacehub.com/buckmore/live', session=sess
        )
        assert cfg.pusher_key == '3aaffebc8193ea83cb2f'
        assert cfg.pusher_cluster == 'eu'
        assert cfg.site == 'buckmore'
        assert cfg.channel_suffix == 'live'
        assert cfg.channel == 'private-buckmorelive'

    def test_site_fallback_to_url_path(self):
        # No siteSlug var in body — must fall back to /<site>/live in the URL.
        body = "<script>var pusherKey = 'k';</script>"
        sess = self._mock_session(body)
        cfg = discover_config(
            'https://www.alpharacehub.com/whilton-mill/live', session=sess
        )
        assert cfg.site == 'whilton-mill'

    def test_at_pst_from_cookie(self):
        body = "<script>var pusherKey = 'k';</script>"
        sess = self._mock_session(body, cookies={'at-pst': 'cookie-token'})
        cfg = discover_config(
            'https://www.alpharacehub.com/buckmore/live', session=sess
        )
        assert cfg.at_pst == 'cookie-token'

    def test_at_pst_from_body_var(self):
        body = """
        <script>
          var pusherKey = 'k';
          window.atPst = 'inline-token';
        </script>
        """
        sess = self._mock_session(body)
        cfg = discover_config(
            'https://www.alpharacehub.com/buckmore/live', session=sess
        )
        assert cfg.at_pst == 'inline-token'

    def test_missing_pusher_key_raises(self):
        body = "<html>nothing useful here</html>"
        sess = self._mock_session(body)
        with pytest.raises(ValueError):
            discover_config(
                'https://www.alpharacehub.com/buckmore/live', session=sess
            )


# ---------------------------------------------------------------------------
# Snapshot ingest + delta merge + standings DataFrame
# ---------------------------------------------------------------------------

@pytest.fixture
def parser(tmp_path: Path) -> AlphaHubParser:
    # We need a working db (TrackSpecificParser.__init__ doesn't touch the FS,
    # but session creation does). Initialize a per-track DB via the manager.
    from multi_track_manager import MultiTrackManager
    db_path = tmp_path / 'race_data_track_99.db'
    mgr = MultiTrackManager(socketio=None)
    mgr.get_database_path = lambda _id: str(db_path)  # type: ignore
    mgr.initialize_track_database(99)
    p = AlphaHubParser(99, 'Buckmore (test)', str(db_path),
                       socketio=None, manager=mgr)
    # Pin a config so snapshot URL is well-formed if anything calls it.
    p._cfg = AlphaHubConfig(
        page_url='https://www.alpharacehub.com/buckmore/live',
        pusher_key='k', pusher_cluster='eu', site='buckmore',
        channel_suffix='live', at_pst=None,
    )
    return p


class TestStandingsBuild:
    def test_empty_state_returns_empty_dataframe(self, parser: AlphaHubParser):
        df = parser.get_current_standings()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_full_row_mapping(self, parser: AlphaHubParser):
        parser.competitors = {
            '17': {
                'CompetitorNumber': 17,
                'CompetitorName': 'Team Alpha',
                'Position': 1,
                'NumberOfLaps': 42,
                'LastLaptime': 74099,
                'BestLaptime': 73500,
                'GapToFirst': 0,
                'RunningTime': 1260_000,
                'PitStops': 2,
                'InPit': False,
            },
            '23': {
                'CompetitorNumber': 23,
                'CompetitorName': 'Team Bravo',
                'Position': 2,
                'NumberOfLaps': 42,
                'LastLaptime': 75200,
                'BestLaptime': 74100,
                'GapToFirst': 2345,
                'RunningTime': 1262_345,
                'PitStops': 2,
                'InPit': True,
            },
        }
        df = parser.get_current_standings()
        assert list(df['Kart']) == ['17', '23']
        leader = df.iloc[0]
        assert leader['Team'] == 'Team Alpha'
        assert leader['Position'] == '1'
        assert leader['Last Lap'] == '1:14.099'
        assert leader['Best Lap'] == '1:13.500'
        assert leader['Gap'] == ''               # leader gap blanked
        assert leader['RunTime'] == '21:00'
        assert leader['Pit Stops'] == '2'
        assert leader['Status'] == 'On Track'
        second = df.iloc[1]
        assert second['Gap'] == '+2.345'
        assert second['Status'] == 'Pit-in'      # InPit=True wins over Status

    def test_lapped_competitor_uses_lap_gap(self, parser: AlphaHubParser):
        parser.competitors = {
            '1': {'CompetitorNumber': 1, 'Position': 1, 'NumberOfLaps': 50,
                  'CompetitorName': 'Lead', 'BestLaptime': 60000},
            '2': {'CompetitorNumber': 2, 'Position': 2, 'NumberOfLaps': 48,
                  'CompetitorName': 'Lapped', 'BestLaptime': 61000,
                  'LapsToFirst': 2, 'GapToFirst': 0},
        }
        df = parser.get_current_standings()
        assert df.iloc[1]['Gap'] == 'Tour 2'

    def test_sorted_by_position(self, parser: AlphaHubParser):
        parser.competitors = {
            'A': {'CompetitorNumber': 'A', 'Position': 5, 'CompetitorName': 'E'},
            'B': {'CompetitorNumber': 'B', 'Position': 1, 'CompetitorName': 'A'},
            'C': {'CompetitorNumber': 'C', 'Position': 3, 'CompetitorName': 'C'},
        }
        df = parser.get_current_standings()
        assert list(df['Position']) == ['1', '3', '5']

    def test_alpha_prefixed_kart_number(self, parser: AlphaHubParser):
        # Whilton Mill style: CompetitorNumber like "C1" must produce a
        # numeric Kart (so the int-typed DB column is happy) and surface
        # the original label in Team as "C1 - CADET 1".
        parser.competitors = {
            'C1':  {'CompetitorNumber': 'C1',  'Position': 1,
                    'CompetitorName': 'CADET 1', 'LastLaptime': 33822,
                    'BestLaptime': 33819, 'NumberOfLaps': 7},
            'C12': {'CompetitorNumber': 'C12', 'Position': 2,
                    'CompetitorName': 'CADET 12', 'LastLaptime': 34100,
                    'BestLaptime': 33950, 'NumberOfLaps': 7},
        }
        df = parser.get_current_standings()
        # Kart values are integers (no "C" prefix) and they're distinct.
        karts = [int(k) for k in df['Kart']]
        assert all(k >= 1_000_000 for k in karts)
        assert karts[0] != karts[1]
        # Team carries the original label so the user can still see "C1".
        assert df.iloc[0]['Team'].startswith('C1 - ')
        assert 'CADET 1' in df.iloc[0]['Team']
        assert df.iloc[1]['Team'].startswith('C12 - ')

    def test_numeric_kart_does_not_get_prepended(self, parser: AlphaHubParser):
        # Buckmore-style numeric ID must keep Team clean (no "17 - " prefix).
        parser.competitors = {
            '17': {'CompetitorNumber': 17, 'Position': 1,
                   'CompetitorName': 'Team Alpha', 'LastLaptime': 75000},
        }
        df = parser.get_current_standings()
        assert df.iloc[0]['Team'] == 'Team Alpha'
        assert df.iloc[0]['Kart'] == '17'

    def test_alpha_kart_without_team_name(self, parser: AlphaHubParser):
        # Edge case: alpha ID + missing team — Team falls back to bare ID.
        parser.competitors = {
            'C1': {'CompetitorNumber': 'C1', 'Position': 1},
        }
        df = parser.get_current_standings()
        assert df.iloc[0]['Team'] == 'C1'

    def test_alt_field_names(self, parser: AlphaHubParser):
        # Some venues use TeamName/Rank/Laps/TotalTime/NumberOfPitStops instead.
        parser.competitors = {
            '9': {
                'CompetitorNumber': 9,
                'TeamName': 'Alt',
                'Rank': 1,
                'Laps': 10,
                'LastLap': 80000,
                'BestLap': 79000,
                'GapToLeader': 0,
                'TotalTime': 800_000,
                'NumberOfPitStops': 1,
            },
        }
        df = parser.get_current_standings()
        row = df.iloc[0]
        assert row['Team'] == 'Alt'
        assert row['Last Lap'] == '1:20.000'
        assert row['Best Lap'] == '1:19.000'
        assert row['Pit Stops'] == '1'


class TestDeltaMerge:
    def test_apply_first_delta_when_no_prior_sequence(self, parser: AlphaHubParser):
        parser.competitors = {
            '17': {'CompetitorNumber': 17, 'CompetitorName': 'A', 'NumberOfLaps': 1},
        }
        parser.last_sequence = None
        changed = parser._apply_delta({
            'Sequence': 5,
            'Competitors': [
                {'CompetitorNumber': 17, 'NumberOfLaps': 2, 'LastLaptime': 75000},
            ],
        })
        assert changed is True
        assert parser.competitors['17']['NumberOfLaps'] == 2
        assert parser.competitors['17']['LastLaptime'] == 75000
        assert parser.competitors['17']['CompetitorName'] == 'A'  # preserved
        assert parser.last_sequence == 5

    def test_stale_sequence_ignored(self, parser: AlphaHubParser):
        parser.competitors = {
            '17': {'CompetitorNumber': 17, 'NumberOfLaps': 5},
        }
        parser.last_sequence = 10
        changed = parser._apply_delta({
            'Sequence': 8,
            'Competitors': [{'CompetitorNumber': 17, 'NumberOfLaps': 99}],
        })
        assert changed is False
        assert parser.competitors['17']['NumberOfLaps'] == 5
        assert parser.last_sequence == 10

    def test_duplicate_sequence_ignored(self, parser: AlphaHubParser):
        parser.last_sequence = 10
        changed = parser._apply_delta({
            'Sequence': 10,
            'Competitors': [{'CompetitorNumber': 1, 'NumberOfLaps': 99}],
        })
        assert changed is False
        assert '1' not in parser.competitors

    def test_huge_sequence_jump_triggers_resync(self, parser: AlphaHubParser):
        # When the seq jumps by >50 we assume missed packets and re-snapshot.
        parser.competitors = {'17': {'CompetitorNumber': 17, 'NumberOfLaps': 1}}
        parser.last_sequence = 1

        snapshot_called = []
        def fake_snap():
            snapshot_called.append(True)
            parser.competitors = {'42': {'CompetitorNumber': 42, 'NumberOfLaps': 99}}
            parser.last_sequence = 100
        parser._fetch_snapshot = fake_snap

        changed = parser._apply_delta({
            'Sequence': 200,  # jump 1→200 >> 50
            'Competitors': [{'CompetitorNumber': 17, 'NumberOfLaps': 7}],
        })
        assert changed is True
        assert snapshot_called == [True]
        # State now reflects the snapshot, not the delta we tried to apply.
        assert '42' in parser.competitors
        assert parser.competitors['42']['NumberOfLaps'] == 99

    def test_delta_without_sequence_is_applied(self, parser: AlphaHubParser):
        # Some events omit Sequence (heartbeats / partial updates).
        parser.competitors = {'1': {'CompetitorNumber': 1, 'NumberOfLaps': 3}}
        parser.last_sequence = None
        changed = parser._apply_delta({
            'Competitors': [{'CompetitorNumber': 1, 'NumberOfLaps': 4}],
        })
        assert changed is True
        assert parser.competitors['1']['NumberOfLaps'] == 4


# ---------------------------------------------------------------------------
# Snapshot fetch (uses a mocked HTTP session)
# ---------------------------------------------------------------------------

class TestSnapshotFetch:
    def test_snapshot_populates_competitors_and_sequence(self, parser: AlphaHubParser):
        payload = {
            'Sequence': 42,
            'Competitors': [
                {'CompetitorNumber': 17, 'CompetitorName': 'A', 'NumberOfLaps': 10},
                {'CompetitorNumber': 23, 'CompetitorName': 'B', 'NumberOfLaps': 9},
            ],
        }
        resp = MagicMock(); resp.json.return_value = payload
        resp.raise_for_status = MagicMock()
        parser._http = MagicMock()
        parser._http.get = MagicMock(return_value=resp)

        parser._fetch_snapshot()

        assert parser.last_sequence == 42
        assert set(parser.competitors.keys()) == {'17', '23'}
        assert parser.competitors['17']['CompetitorName'] == 'A'

    def test_snapshot_failure_keeps_existing_state(self, parser: AlphaHubParser):
        parser.competitors = {'1': {'CompetitorNumber': 1, 'NumberOfLaps': 5}}
        parser.last_sequence = 7
        parser._http = MagicMock()
        parser._http.get = MagicMock(side_effect=RuntimeError('boom'))

        parser._fetch_snapshot()  # logs + returns; must not raise

        assert parser.competitors['1']['NumberOfLaps'] == 5
        assert parser.last_sequence == 7
