"""Payload shape parity between compute_fleet_payload and /fleet/state, plus the
live location/alert layer. (Per-user: no shared broadcast.)"""

import pandas as pd

from .conftest import (
    login, seed_session, seed_fleet_kart, seed_laps, seed_assignment, TRACK_ID, SEED_USER_ID,
)

BASE = f"/api/track/{TRACK_ID}/fleet"

TOP_LEVEL_KEYS = {
    "track_id", "session_id", "timestamp",
    "field_ref_seconds", "fleet_median_residual", "karts", "unassigned_teams",
}
KART_KEYS = {
    "fleet_kart_id", "label", "holder_team", "holder_kart_number", "holder_position",
    "location", "stint_index", "mean_residual", "pace_delta_vs_fleet", "uncertainty",
    "sample_laps", "n_stints", "classification", "rank", "alerts",
}


def _seed_fast_fleet(conn, user_id):
    seed_session(conn, 200)
    ids = {}
    for label in ["A1", "A2", "A3", "A4", "F"]:
        ids[label] = seed_fleet_kart(conn, label, user_id=user_id)
    for i, label in enumerate(["A1", "A2", "A3", "A4"]):
        seed_laps(conn, 200, f"Avg{i}", [60.0] * 6, [0] * 6, kart_number=10 + i)
        seed_assignment(conn, 200, f"Avg{i}", ids[label], 0, user_id=user_id)
    seed_laps(conn, 200, "FastTeam", [54.0] * 6, [0] * 6, kart_number=77)
    seed_assignment(conn, 200, "FastTeam", ids["F"], 0, user_id=user_id)
    return ids


def test_payload_and_state_have_same_keys(fleet_app, track_conn, client, admin_user):
    uid = admin_user["id"]
    _seed_fast_fleet(track_conn, uid)
    payload = fleet_app.compute_fleet_payload(TRACK_ID, 200, uid)
    assert set(payload.keys()) == TOP_LEVEL_KEYS
    for k in payload["karts"]:
        assert set(k.keys()) == KART_KEYS

    login(client, admin_user["username"], admin_user["password"])
    state = client.get(f"{BASE}/state?session_id=200").get_json()
    assert set(state.keys()) == TOP_LEVEL_KEYS
    assert set(state["karts"][0].keys()) == KART_KEYS


def test_live_location_and_fast_in_pits_alert(fleet_app, track_conn):
    _seed_fast_fleet(track_conn, SEED_USER_ID)
    standings = pd.DataFrame([
        {"Team": "FastTeam", "Status": "Pit-in", "Kart": "77", "Position": "5"},
        {"Team": "Avg0", "Status": "On Track", "Kart": "10", "Position": "1"},
    ])
    payload = fleet_app._compute_live_fleet_pace(track_conn, 200, SEED_USER_ID, standings_df=standings)
    fast = next(k for k in payload["karts"] if k["label"] == "F")
    assert fast["location"] == "in-pits"
    assert fast["holder_position"] == 5
    assert "fast_kart_in_pits" in fast["alerts"]


def test_unassigned_teams_listed(fleet_app, track_conn):
    seed_session(track_conn, 201)
    seed_laps(track_conn, 201, "NoKart", [60.0] * 6, [0] * 6)
    payload = fleet_app._compute_live_fleet_pace(track_conn, 201, SEED_USER_ID)
    assert "NoKart" in payload["unassigned_teams"]


def test_fleet_is_isolated_per_user(fleet_app, track_conn):
    """A kart/assignment owned by one user is invisible to another's board."""
    seed_session(track_conn, 202)
    other = SEED_USER_ID + 99
    kid = seed_fleet_kart(track_conn, "Mine", user_id=other)
    seed_laps(track_conn, 202, "T", [60.0] * 6, [0] * 6, kart_number=3)
    seed_assignment(track_conn, 202, "T", kid, 0, user_id=other)
    # SEED_USER_ID has no fleet of their own in this session.
    mine = fleet_app._compute_live_fleet_pace(track_conn, 202, SEED_USER_ID)
    assert mine["karts"] == []
    theirs = fleet_app._compute_live_fleet_pace(track_conn, 202, other)
    assert [k["label"] for k in theirs["karts"]] == ["Mine"]
