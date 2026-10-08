"""Tests for the lap_history.gap schema migration and its backfill script.

The Delta chart reads `lap_history.gap` (per-lap gap-to-leader). Track DBs
created before that column existed must get it added additively, and their
historical rows must be fillable from the `lap_times` snapshot taken on the
same tick.
"""

import sqlite3

import pytest

from multi_track_manager import MultiTrackManager
from migrations.backfill_lap_history_gap import backfill_db, main

pytestmark = pytest.mark.integration


# Pre-gap schema: `lap_history` has no gap column, `lap_times` does.
OLD_SCHEMA = """
CREATE TABLE lap_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    timestamp TEXT,
    kart_number INTEGER,
    team_name TEXT,
    lap_number INTEGER,
    lap_time TEXT,
    position_after_lap INTEGER,
    pit_this_lap INTEGER
);
CREATE TABLE lap_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    timestamp TEXT,
    position INTEGER,
    kart_number INTEGER,
    team_name TEXT,
    last_lap TEXT,
    best_lap TEXT,
    gap TEXT,
    RunTime TEXT,
    pit_stops INTEGER
);
"""


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _make_old_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_SCHEMA)
        conn.execute(
            "INSERT INTO lap_history (session_id, timestamp, kart_number, team_name, "
            "lap_number, lap_time, position_after_lap, pit_this_lap) "
            "VALUES (1, '2026-05-26T12:00:00', 7, 'US', 1, '1:00.000', 1, 0)"
        )
        conn.execute(
            "INSERT INTO lap_times (session_id, timestamp, kart_number, team_name, "
            "last_lap, gap) VALUES (1, '2026-05-26T12:00:00', 7, 'US', '1:00.000', '3.5')"
        )
        conn.commit()


def test_initialize_track_database_adds_gap_column_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = "race_data_track_1.db"
    _make_old_db(db)

    MultiTrackManager().initialize_track_database(1)
    with sqlite3.connect(db) as conn:
        assert 'gap' in _columns(conn, 'lap_history')
        # The pre-existing (gap-less) row is preserved.
        assert conn.execute("SELECT COUNT(*) FROM lap_history").fetchone()[0] == 1

    # Running again must not raise or duplicate the column.
    MultiTrackManager().initialize_track_database(1)
    with sqlite3.connect(db) as conn:
        assert _columns(conn, 'lap_history').count('gap') == 1


def test_backfill_fills_gap_from_a_matching_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = "race_data_track_1.db"
    _make_old_db(db)

    missing, updated = backfill_db(db)
    assert missing == 1
    assert updated == 1
    with sqlite3.connect(db) as conn:
        stored = conn.execute("SELECT gap FROM lap_history").fetchone()[0]
    assert stored == '3.5'


def test_backfill_falls_back_to_a_lap_time_match_on_clock_skew(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = "race_data_track_1.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(OLD_SCHEMA)
        conn.execute('ALTER TABLE lap_history ADD COLUMN gap TEXT')
        conn.execute(
            "INSERT INTO lap_history (session_id, timestamp, kart_number, team_name, "
            "lap_number, lap_time, gap, position_after_lap, pit_this_lap) "
            "VALUES (1, '2026-05-26T12:00:01', 7, 'US', 1, '1:00.000', NULL, 1, 0)"
        )
        # Timestamp differs by a second, but the lap time is the same.
        conn.execute(
            "INSERT INTO lap_times (session_id, timestamp, kart_number, team_name, "
            "last_lap, gap) VALUES (1, '2026-05-26T12:00:00', 7, 'US', '1:00.000', '9.9')"
        )
        conn.commit()

    missing, updated = backfill_db(db)
    assert (missing, updated) == (1, 1)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT gap FROM lap_history").fetchone()[0] == '9.9'


def test_backfill_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = "race_data_track_1.db"
    _make_old_db(db)

    backfill_db(db)
    # Second pass: no row is missing a gap anymore.
    missing, updated = backfill_db(db)
    assert missing == 0
    assert updated == 0


def test_backfill_skips_databases_without_the_tables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = "race_data_track_1.db"
    sqlite3.connect(db).close()

    assert backfill_db(db) == (0, 0)


def test_dry_run_reports_without_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = "race_data_track_1.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(OLD_SCHEMA)
        conn.execute(
            "INSERT INTO lap_history (session_id, timestamp, kart_number, team_name, "
            "lap_number, lap_time, position_after_lap, pit_this_lap) "
            "VALUES (1, 't1', 7, 'US', 1, '1:00.000', 1, 0)"
        )
        conn.execute(
            "INSERT INTO lap_times (session_id, timestamp, kart_number, team_name, "
            "last_lap, gap) VALUES (1, 't1', 7, 'US', '1:00.000', '3.5')"
        )
        conn.commit()

    assert main(['--dry-run', db]) == 0
    # Dry run must not add the column.
    with sqlite3.connect(db) as conn:
        assert 'gap' not in _columns(conn, 'lap_history')
