"""Broadcast paths only build/serialize payloads for occupied rooms."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

import multi_track_manager as mtm


pytestmark = pytest.mark.unit


def _socketio_with_rooms(rooms: dict):
    """Fake socketio whose server.manager.rooms mimics python-socketio."""
    sio = MagicMock()
    sio.server.manager.rooms = {'/': {name: dict.fromkeys(sids, True)
                                      for name, sids in rooms.items()}}
    return sio


class TestRoomHelpers:
    def test_room_occupied_true(self):
        sio = _socketio_with_rooms({'track_1': ['sidA']})
        assert mtm._room_occupied(sio, 'track_1') is True

    def test_room_occupied_false_for_missing_or_empty(self):
        sio = _socketio_with_rooms({'track_1': []})
        assert mtm._room_occupied(sio, 'track_1') is False
        assert mtm._room_occupied(sio, 'track_2') is False

    def test_room_occupied_fails_open(self):
        broken = MagicMock()
        broken.server.manager.rooms.get.side_effect = RuntimeError('boom')
        assert mtm._room_occupied(broken, 'track_1') is True

    def test_any_room_with_prefix(self):
        sio = _socketio_with_rooms({'team_track_3_Alpha': ['sidA'], 'track_3': ['sidB']})
        assert mtm._any_room_with_prefix(sio, 'team_track_3_') is True
        assert mtm._any_room_with_prefix(sio, 'team_track_4_') is False


class TestTeamSpecificEmits:
    def _parser(self, sio):
        """Minimal stand-in with the attributes emit_team_specific_updates uses."""
        parser = SimpleNamespace(
            socketio=sio,
            track_id=3,
            logger=MagicMock(),
        )
        parser.emit_team_specific_updates = (
            mtm.TrackSpecificParser.emit_team_specific_updates.__get__(parser))
        return parser

    def _standings(self):
        return pd.DataFrame([
            {'Team': 'Alpha', 'Position': '1', 'Gap': '', 'Last Lap': '1:02.0',
             'Best Lap': '1:01.0', 'Pit Stops': '0', 'Status': 'On Track'},
            {'Team': 'Beta', 'Position': '2', 'Gap': '+1.500', 'Last Lap': '1:02.5',
             'Best Lap': '1:01.5', 'Pit Stops': '0', 'Status': 'On Track'},
        ])

    def test_emits_only_to_occupied_team_rooms(self):
        sio = _socketio_with_rooms({'team_track_3_Alpha': ['sidA']})
        parser = self._parser(sio)
        parser.emit_team_specific_updates(self._standings(), 42, 'ts')
        emitted_rooms = [kwargs['room'] for _, kwargs in sio.emit.call_args_list]
        assert emitted_rooms == ['team_track_3_Alpha']

    def test_no_emits_when_no_team_rooms(self):
        sio = _socketio_with_rooms({})
        parser = self._parser(sio)
        parser.emit_team_specific_updates(self._standings(), 42, 'ts')
        assert sio.emit.call_count == 0


class TestAllTracksStatus:
    def _manager_with_parser(self, sio, teams_count=7):
        mgr = mtm.MultiTrackManager(socketio=sio)
        parser = SimpleNamespace(
            track_name='Testville',
            session_active_status=True,
            last_data_time=None,
            is_connected=True,
            provider='apex',
            get_teams_count=lambda: teams_count,
        )
        mgr.parsers[1] = parser
        return mgr

    def test_status_uses_cheap_count_not_dataframe(self):
        sio = _socketio_with_rooms({'all_tracks': ['sidA']})
        mgr = self._manager_with_parser(sio, teams_count=12)
        status = mgr.get_all_tracks_status()
        assert status[0]['teams_count'] == 12

    def test_broadcast_skipped_when_room_empty(self):
        sio = _socketio_with_rooms({})
        mgr = self._manager_with_parser(sio)
        mgr.broadcast_all_tracks_status()
        assert sio.emit.call_count == 0

    def test_broadcast_sent_when_room_occupied(self):
        sio = _socketio_with_rooms({'all_tracks': ['sidA']})
        mgr = self._manager_with_parser(sio)
        mgr.broadcast_all_tracks_status()
        assert sio.emit.call_count == 1
        assert sio.emit.call_args[1]['room'] == 'all_tracks'
