"""GET /api/team-data/session-gaps — per-lap gap history for the Delta chart.

The endpoint returns user-independent timing data (each kart's gap-to-leader
per completed lap); the client computes head-to-head deltas against its own
team, so nothing per-user is exposed here.
"""

from datetime import datetime, timedelta

import pytest

from tests.test_team_data.conftest import (  # noqa: F401 — fixtures
    client,
    normal_user,
    track_conn,
    login,
    TRACK_ID,
)

pytestmark = pytest.mark.integration

SESSION = 900
BASE = datetime(2026, 5, 26, 12, 0, 0)
URL = "/api/team-data/session-gaps"


def _seed(conn):
    conn.execute(
        "INSERT INTO race_sessions (session_id, start_time, name, track) "
        "VALUES (?, ?, ?, 'Test Track')",
        (SESSION, BASE.isoformat(), "Delta Test"),
    )
    # (kart, team, gap, lap_time, cumulative pit count)
    rows = [
        (1, "US", "", "1:00.000", 0),
        (1, "US", "0.500", "1:00.100", 0),
        (1, "US", "1.000", "1:00.200", 1),
        (7, "RIVAL", "2.000", "1:01.000", 0),
        (7, "RIVAL", "3 Tours", "1:01.100", 0),
        (7, "RIVAL", "4.500", "1:01.200", 1),
    ]
    for i, (kart, team, gap, lap_time, pit) in enumerate(rows):
        ts = (BASE + timedelta(seconds=i)).isoformat()
        conn.execute(
            "INSERT INTO lap_history (session_id, timestamp, kart_number, team_name, "
            "lap_number, lap_time, gap, position_after_lap, pit_this_lap) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (SESSION, ts, kart, team, i, lap_time, gap, 1, pit),
        )
    conn.commit()


def test_requires_login(client):
    resp = client.get(f"{URL}?track_id={TRACK_ID}&session_id={SESSION}")
    assert resp.status_code == 401


def test_returns_a_per_lap_series(client, normal_user, track_conn):
    _seed(track_conn)
    login(client, normal_user["username"], normal_user["password"])

    resp = client.get(f"{URL}?track_id={TRACK_ID}&session_id={SESSION}&karts=1,7")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["track_id"] == TRACK_ID
    assert body["session_id"] == SESSION

    us = body["series"]["1"]
    assert us["team"] == "US"
    assert [lap["gap_seconds"] for lap in us["laps"]] == [0.0, 0.5, 1.0]
    assert [lap["pit_stops"] for lap in us["laps"]] == [0, 0, 1]
    assert [lap["lap"] for lap in us["laps"]] == [1, 2, 3]

    rival = body["series"]["7"]
    # a lapped gap keeps its raw string but reports no seconds figure
    assert rival["laps"][1]["gap"] == "3 Tours"
    assert rival["laps"][1]["gap_seconds"] is None
    assert rival["laps"][2]["gap_seconds"] == 4.5


def test_kart_filter_restricts_the_series(client, normal_user, track_conn):
    _seed(track_conn)
    login(client, normal_user["username"], normal_user["password"])

    resp = client.get(f"{URL}?track_id={TRACK_ID}&session_id={SESSION}&karts=1")
    assert resp.status_code == 200
    assert set(resp.get_json()["series"].keys()) == {"1"}


def test_no_live_session_404s(client, normal_user):
    login(client, normal_user["username"], normal_user["password"])
    resp = client.get(f"{URL}?track_id={TRACK_ID}")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "no_live_session"


def test_missing_track_id_400s(client, normal_user):
    login(client, normal_user["username"], normal_user["password"])
    assert client.get(URL).status_code == 400


def test_invalid_karts_400s(client, normal_user, track_conn):
    _seed(track_conn)
    login(client, normal_user["username"], normal_user["password"])
    resp = client.get(f"{URL}?track_id={TRACK_ID}&session_id={SESSION}&karts=abc")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_karts"
