"""End-to-end Fleet Tracker lifecycle, driven entirely through the HTTP API on
a simulated endurance session: auto-populate -> pace ranking -> a team pits
(timing moves it to In pit + fast-kart alert) -> release to a lane -> pick up a
spare -> correct an assignment -> per-user isolation.

The live-timing layer (_live_standings_df) is monkeypatched so the timing-driven
On track / In pit transitions are exercised too. The per-(track,user) cache is
cleared whenever the simulated standings change (no mutation invalidates it).
"""

from datetime import datetime, timedelta

import pandas as pd

from .conftest import login, TRACK_ID
import sqlite3

SID = 900
DB = f"race_data_track_{TRACK_ID}.db"
BASE = f"/api/track/{TRACK_ID}/fleet"


def _hdr(token):
    return {"X-CSRF-Token": token}


def _seed_session():
    """5 teams: four ~60s, ECHO (#5) ~54s (clearly fast). Writes lap_times (for
    team discovery) + lap_history (for pace), with distinct lap strings."""
    base = datetime(2026, 5, 27, 12, 0, 0)
    teams = [("ALPHA", 1, 60.0), ("BRAVO", 2, 60.0), ("CHARLIE", 3, 60.0),
             ("DELTA", 4, 60.0), ("ECHO", 5, 54.0)]
    with sqlite3.connect(DB) as conn:
        conn.execute("INSERT INTO race_sessions (session_id, start_time) VALUES (?, ?)",
                     (SID, base.isoformat()))
        for name, num, secs in teams:
            for i in range(6):
                ts = (base + timedelta(minutes=i)).isoformat()
                lap = f"{secs + i * 0.001:.3f}"
                conn.execute(
                    "INSERT INTO lap_times (session_id, timestamp, position, kart_number, team_name, "
                    "last_lap, best_lap, pit_stops) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                    (SID, ts, num, num, name, lap, lap))
                conn.execute(
                    "INSERT INTO lap_history (session_id, timestamp, kart_number, team_name, "
                    "lap_number, lap_time, position_after_lap, pit_this_lap) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                    (SID, ts, num, name, i, lap, num))
        conn.commit()


def _state(client, fleet_app, standings=None):
    """Clear the per-user cache, set the simulated standings, fetch the board."""
    fleet_app._fleet_cache.clear()
    fleet_app._live_standings_df = lambda _tid: standings  # type: ignore
    body = client.get(f"{BASE}/state?session_id={SID}").get_json()
    return {k["label"]: k for k in body["karts"]}, body


def test_full_endurance_lifecycle(client, admin_user, fleet_app, monkeypatch):
    token = login(client, admin_user["username"], admin_user["password"])
    _seed_session()

    # 1) Auto-populate the roster from the session.
    r = client.post(f"{BASE}/auto-populate", json={"session_id": SID}, headers=_hdr(token))
    assert r.status_code == 201
    body = r.get_json()
    assert body["created_assignments"] == 5
    assert all(k["label"].startswith("K-") for k in body["created_karts"])

    # 2) No live standings yet -> all held karts read On track; ECHO's K-5 is fast.
    karts, board = _state(client, fleet_app, standings=None)
    assert set(karts) == {"K-1", "K-2", "K-3", "K-4", "K-5"}
    assert karts["K-5"]["classification"] == "fast"
    assert karts["K-5"]["holder_team"] == "ECHO"
    assert all(k["column"] == "on_track" for k in karts.values())
    assert board["field_ref_seconds"] == pytest_approx(60.0)

    # 3) ECHO pits -> timing moves K-5 to In pit and raises the fast-kart alert.
    pit = pd.DataFrame([
        {"Team": "ECHO", "Status": "Pit-in", "Kart": "5", "Position": "5"},
        {"Team": "ALPHA", "Status": "On Track", "Kart": "1", "Position": "1"},
    ])
    karts, _ = _state(client, fleet_app, standings=pit)
    assert karts["K-5"]["column"] == "in_pit"
    assert "fast_kart_in_pits" in karts["K-5"]["alerts"]

    # 4) Release K-5 into lane 1 (ECHO drops it).
    k5_id = karts["K-5"]["fleet_kart_id"]
    assert client.post(f"{BASE}/release", json={"session_id": SID, "fleet_kart_id": k5_id, "lane": 1},
                       headers=_hdr(token)).status_code == 200
    karts, board = _state(client, fleet_app, standings=pit)
    assert karts["K-5"]["column"] == "available" and karts["K-5"]["lane"] == 1
    assert "ECHO" in board["unassigned_teams"]

    # 5) ECHO picks up a spare from the pit lane.
    spare = client.post(f"{BASE}/karts", json={"label": "K-99"}, headers=_hdr(token)).get_json()["kart"]["id"]
    assert client.post(f"{BASE}/assignments",
                       json={"session_id": SID, "team_name": "ECHO", "fleet_kart_id": spare},
                       headers=_hdr(token)).status_code == 201
    karts, board = _state(client, fleet_app, standings=pit)
    assert karts["K-99"]["holder_team"] == "ECHO"
    assert "ECHO" not in board["unassigned_teams"]

    # 6) Correct ALPHA onto a different kart and confirm re-attribution.
    spare2 = client.post(f"{BASE}/karts", json={"label": "K-77"}, headers=_hdr(token)).get_json()["kart"]["id"]
    rows = client.get(f"{BASE}/assignments?session_id={SID}").get_json()["assignments"]
    alpha = next(r for r in rows if r["team_name"] == "ALPHA" and not r["superseded"])
    assert client.post(f"{BASE}/assignments/correct",
                       json={"assignment_id": alpha["id"], "fleet_kart_id": spare2},
                       headers=_hdr(token)).status_code == 201
    karts, _ = _state(client, fleet_app, standings=None)
    assert karts["K-77"]["holder_team"] == "ALPHA"


def test_other_user_sees_empty_board(client, admin_user, normal_user, fleet_app, monkeypatch):
    # Operator builds a fleet...
    token = login(client, admin_user["username"], admin_user["password"])
    _seed_session()
    client.post(f"{BASE}/auto-populate", json={"session_id": SID}, headers=_hdr(token))
    # ...a different user's board is empty (per-user isolation, end to end).
    login(client, normal_user["username"], normal_user["password"])
    fleet_app._fleet_cache.clear()
    fleet_app._live_standings_df = lambda _tid: None  # type: ignore
    body = client.get(f"{BASE}/state?session_id={SID}").get_json()
    assert body["karts"] == []


def pytest_approx(v):
    from pytest import approx
    return approx(v, abs=0.05)
