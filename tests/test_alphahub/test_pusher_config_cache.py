"""End-to-end coverage of the Pusher-config cache in tracks.db.

Schema migration: the 4 pusher_* columns must exist after TrackDatabase init
on a fresh DB AND must be added by ALTER TABLE on an existing DB without
losing data. The dedicated writer (update_pusher_config) must round-trip
through get_all_tracks/get_track_by_id and clear safely when passed None.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch):
    """Isolated tracks.db rooted at tmp_path so this test never touches prod."""
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from database_manager import TrackDatabase
    return TrackDatabase(db_path=str(tmp_path / 'tracks.db'))


def _columns(db_path: str) -> list[str]:
    with sqlite3.connect(db_path) as c:
        return [r[1] for r in c.execute('PRAGMA table_info(tracks)').fetchall()]


class TestSchemaMigration:
    def test_fresh_db_has_all_pusher_columns(self, fresh_db, tmp_path):
        cols = _columns(str(tmp_path / 'tracks.db'))
        for c in (
            'pusher_key', 'pusher_cluster',
            'pusher_site', 'pusher_channel_suffix',
        ):
            assert c in cols, f"missing column {c} after fresh init"

    def test_existing_db_is_migrated_without_data_loss(self, tmp_path, monkeypatch):
        # Create a pre-pusher-cache tracks.db by hand, then let TrackDatabase
        # init migrate it.
        db_path = tmp_path / 'tracks.db'
        with sqlite3.connect(db_path) as c:
            c.execute('''
                CREATE TABLE tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_name TEXT NOT NULL UNIQUE,
                    timing_url TEXT NOT NULL,
                    websocket_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                INSERT INTO tracks (track_name, timing_url, websocket_url)
                VALUES ('Legacy Track', 'http://t/', 'wss://x/')
            ''')

        monkeypatch.chdir(tmp_path)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from database_manager import TrackDatabase
        TrackDatabase(db_path=str(db_path))

        cols = _columns(str(db_path))
        for c in (
            'pusher_key', 'pusher_cluster',
            'pusher_site', 'pusher_channel_suffix',
        ):
            assert c in cols

        # Existing row survives, new columns NULL by default.
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute('SELECT * FROM tracks WHERE track_name=?',
                            ('Legacy Track',)).fetchone()
        assert row is not None
        assert row['pusher_key'] is None
        assert row['pusher_site'] is None


class TestUpdatePusherConfig:
    def _add_alphahub_track(self, db) -> int:
        res = db.add_track(
            track_name='Buckmore Park',
            timing_url='https://www.alpharacehub.com/buckmore/live',
            websocket_url='https://www.alpharacehub.com/buckmore/live',
            provider='alphahub',
        )
        return res['id']

    def test_round_trip_via_get_all_tracks(self, fresh_db):
        tid = self._add_alphahub_track(fresh_db)
        assert fresh_db.update_pusher_config(
            tid, pusher_key='3aaffebc8193ea83cb2f',
            pusher_cluster='eu', pusher_site='buckmore',
            pusher_channel_suffix='live',
        ) is True
        all_tracks = {t['id']: t for t in fresh_db.get_all_tracks()}
        t = all_tracks[tid]
        assert t['pusher_key'] == '3aaffebc8193ea83cb2f'
        assert t['pusher_cluster'] == 'eu'
        assert t['pusher_site'] == 'buckmore'
        assert t['pusher_channel_suffix'] == 'live'

    def test_clearing_with_none_invalidates_cache(self, fresh_db):
        tid = self._add_alphahub_track(fresh_db)
        fresh_db.update_pusher_config(
            tid, pusher_key='k', pusher_cluster='eu',
            pusher_site='buckmore', pusher_channel_suffix='live',
        )
        # Now clear — mimics the auth-401 invalidation path.
        fresh_db.update_pusher_config(
            tid, pusher_key=None, pusher_cluster=None,
            pusher_site=None, pusher_channel_suffix=None,
        )
        t = next(t for t in fresh_db.get_all_tracks() if t['id'] == tid)
        assert t['pusher_key'] is None
        assert t['pusher_cluster'] is None
        assert t['pusher_site'] is None
        assert t['pusher_channel_suffix'] is None

    def test_apex_track_pusher_columns_default_to_null(self, fresh_db):
        # Apex tracks never populate these — they should never have non-null
        # pusher fields just from being added.
        res = fresh_db.add_track(
            track_name='Karting Mariembourg',
            timing_url='https://www.apex-timing.com/live-timing/karting-mariembourg/index.html',
            websocket_url='wss://www.apex-timing.com:8312/',
            provider='apex',
        )
        t = next(t for t in fresh_db.get_all_tracks() if t['id'] == res['id'])
        assert t['pusher_key'] is None
        assert t['pusher_site'] is None
