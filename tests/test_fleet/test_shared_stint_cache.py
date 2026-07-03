"""Shared (track, session)-scoped stint-data cache: N users → one computation."""

from unittest.mock import patch

import pytest

from .conftest import seed_session, seed_fleet_kart, seed_laps, seed_assignment, TRACK_ID, SEED_USER_ID


@pytest.fixture
def clear_stint_cache(fleet_app):
    with fleet_app._fleet_stint_cache_lock:
        fleet_app._fleet_stint_cache.clear()
        fleet_app._fleet_stint_locks.clear()
    yield
    with fleet_app._fleet_stint_cache_lock:
        fleet_app._fleet_stint_cache.clear()
        fleet_app._fleet_stint_locks.clear()


def _seed_two_user_scenario(conn):
    seed_session(conn, 300)
    for i in range(4):
        seed_laps(conn, 300, f"T{i}", [60.0] * 6, [0] * 6, kart_number=i + 1)
    k1 = seed_fleet_kart(conn, "U1-K", user_id=1)
    k2 = seed_fleet_kart(conn, "U2-K", user_id=2)
    seed_assignment(conn, 300, "T0", k1, 0, user_id=1)
    seed_assignment(conn, 300, "T1", k2, 0, user_id=2)


def test_two_users_share_one_computation(fleet_app, track_conn, clear_stint_cache):
    _seed_two_user_scenario(track_conn)
    with patch.object(fleet_app, '_compute_session_stint_data',
                      wraps=fleet_app._compute_session_stint_data) as spy:
        p1 = fleet_app.compute_fleet_payload(TRACK_ID, 300, 1)
        p2 = fleet_app.compute_fleet_payload(TRACK_ID, 300, 2)
    assert spy.call_count == 1
    assert p1['karts'][0]['label'] == 'U1-K'
    assert p2['karts'][0]['label'] == 'U2-K'


def test_cache_expires_after_ttl(fleet_app, track_conn, clear_stint_cache, monkeypatch):
    _seed_two_user_scenario(track_conn)
    monkeypatch.setattr(fleet_app, 'FLEET_STINT_CACHE_TTL_SECONDS', 0.0)
    with patch.object(fleet_app, '_compute_session_stint_data',
                      wraps=fleet_app._compute_session_stint_data) as spy:
        fleet_app.compute_fleet_payload(TRACK_ID, 300, 1)
        fleet_app.compute_fleet_payload(TRACK_ID, 300, 2)
    assert spy.call_count == 2


def test_new_session_evicts_previous_sessions_entry(fleet_app, track_conn, clear_stint_cache):
    _seed_two_user_scenario(track_conn)
    seed_session(track_conn, 301)
    seed_laps(track_conn, 301, "NextRace", [60.0] * 6, [0] * 6)
    fleet_app.compute_fleet_payload(TRACK_ID, 300, 1)
    assert (TRACK_ID, 300) in fleet_app._fleet_stint_cache
    fleet_app.compute_fleet_payload(TRACK_ID, 301, 1)
    assert (TRACK_ID, 301) in fleet_app._fleet_stint_cache
    assert (TRACK_ID, 300) not in fleet_app._fleet_stint_cache


def test_shared_and_inline_paths_agree(fleet_app, track_conn, clear_stint_cache):
    """Golden equivalence: the board built from the shared cache must be
    identical to the board computed inline (pre-refactor behavior)."""
    _seed_two_user_scenario(track_conn)
    inline = fleet_app._compute_live_fleet_pace(track_conn, 300, SEED_USER_ID)
    shared = fleet_app._compute_live_fleet_pace(
        track_conn, 300, SEED_USER_ID,
        stint_data=fleet_app._get_session_stint_data(TRACK_ID, 300, conn=track_conn))
    assert inline == shared
