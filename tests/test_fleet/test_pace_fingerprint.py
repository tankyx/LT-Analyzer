"""Core fleet pace-fingerprint math: residuals, field reference, classification,
attribution, and re-attribution when an assignment changes."""

from datetime import datetime, timedelta

import pytest

from .conftest import seed_session, seed_fleet_kart, seed_laps, seed_assignment, TRACK_ID, SEED_USER_ID


def _by_label(payload, label):
    return next(k for k in payload["karts"] if k["label"] == label)


def _scenario(conn):
    """4 average teams @60.0 + 1 fast team @54.0, one kart each."""
    seed_session(conn, 100)
    kart_ids = {}
    for i, label in enumerate(["K1", "K2", "K3", "K4", "K5"]):
        kart_ids[label] = seed_fleet_kart(conn, label)
    for i, label in enumerate(["K1", "K2", "K3", "K4"]):
        team = f"T{i + 1}"
        seed_laps(conn, 100, team, [60.0] * 6, [0] * 6, kart_number=i + 1)
        seed_assignment(conn, 100, team, kart_ids[label], 0)
    seed_laps(conn, 100, "T5", [54.0] * 6, [0] * 6, kart_number=5)
    seed_assignment(conn, 100, "T5", kart_ids["K5"], 0)
    return kart_ids


def test_field_reference_is_field_median(fleet_app, track_conn):
    _scenario(track_conn)
    payload = fleet_app._compute_live_fleet_pace(track_conn, 100, SEED_USER_ID)
    # 24 laps @~60 + 6 laps @~54 -> median ~60.0
    assert payload["field_ref_seconds"] == pytest.approx(60.0, abs=0.05)


def test_residual_equals_stint_mean_minus_field_ref(fleet_app, track_conn):
    _scenario(track_conn)
    payload = fleet_app._compute_live_fleet_pace(track_conn, 100, SEED_USER_ID)
    assert _by_label(payload, "K5")["mean_residual"] == pytest.approx(-6.0, abs=0.05)  # 54 - 60
    assert _by_label(payload, "K1")["mean_residual"] == pytest.approx(0.0, abs=0.05)


def test_fast_kart_classified_fast(fleet_app, track_conn):
    _scenario(track_conn)
    payload = fleet_app._compute_live_fleet_pace(track_conn, 100, SEED_USER_ID)
    assert _by_label(payload, "K5")["classification"] == "fast"
    assert _by_label(payload, "K1")["classification"] == "neutral"


def test_fastest_kart_ranked_first(fleet_app, track_conn):
    _scenario(track_conn)
    payload = fleet_app._compute_live_fleet_pace(track_conn, 100, SEED_USER_ID)
    assert _by_label(payload, "K5")["rank"] == 1


def test_insufficient_below_min_laps(fleet_app, track_conn):
    seed_session(track_conn, 101)
    kid = seed_fleet_kart(track_conn, "Solo")
    # 3 raw laps -> _segment_stints drops the first -> 2 clean laps (< 5)
    seed_laps(track_conn, 101, "SoloTeam", [60.0, 60.0, 60.0], [0, 0, 0])
    seed_assignment(track_conn, 101, "SoloTeam", kid, 0)
    payload = fleet_app._compute_live_fleet_pace(track_conn, 101, SEED_USER_ID)
    k = _by_label(payload, "Solo")
    assert k["classification"] == "insufficient"
    assert k["sample_laps"] == 2


def test_unassigned_team_listed_and_available_kart(fleet_app, track_conn):
    seed_session(track_conn, 102)
    seed_fleet_kart(track_conn, "Empty")  # registered but never assigned
    seed_laps(track_conn, 102, "Ghost", [60.0] * 6, [0] * 6)
    payload = fleet_app._compute_live_fleet_pace(track_conn, 102, SEED_USER_ID)
    assert "Ghost" in payload["unassigned_teams"]
    assert _by_label(payload, "Empty")["location"] == "available"


def test_reattribution_follows_assignment_change(fleet_app, track_conn):
    """Superseding an assignment moves the stint's residual to the new kart."""
    seed_session(track_conn, 103)
    # field anchor: four average teams
    for i in range(4):
        seed_laps(track_conn, 103, f"Avg{i}", [60.0] * 6, [0] * 6, kart_number=10 + i)
    k_fast = seed_fleet_kart(track_conn, "Fast")
    k_other = seed_fleet_kart(track_conn, "Other")
    seed_laps(track_conn, 103, "Hot", [54.0] * 6, [0] * 6, kart_number=99)
    aid = seed_assignment(track_conn, 103, "Hot", k_fast, 0)

    before = fleet_app._compute_live_fleet_pace(track_conn, 103, SEED_USER_ID)
    assert _by_label(before, "Fast")["mean_residual"] == pytest.approx(-6.0, abs=0.05)
    assert _by_label(before, "Other")["mean_residual"] is None

    # Correct: supersede old, reassign the same stint to the Other kart.
    track_conn.execute("UPDATE fleet_assignments SET superseded = 1 WHERE id = ?", (aid,))
    seed_assignment(track_conn, 103, "Hot", k_other, 0, source="correction")

    after = fleet_app._compute_live_fleet_pace(track_conn, 103, SEED_USER_ID)
    assert _by_label(after, "Other")["mean_residual"] == pytest.approx(-6.0, abs=0.05)
    assert _by_label(after, "Fast")["mean_residual"] is None


def test_rolling_window_excludes_old_laps(fleet_app, track_conn):
    """Laps older than the rolling window don't drag the field reference."""
    seed_session(track_conn, 104)
    old = datetime(2026, 5, 26, 10, 0, 0)            # ~2h before the recent block
    recent = datetime(2026, 5, 26, 12, 0, 0)
    # Old slow laps that would pull an all-time median upward.
    seed_laps(track_conn, 104, "OldTeam", [90.0] * 6, [0] * 6, base=old, kart_number=1)
    # Recent laps clustered at 60.0 inside the 10-min window.
    seed_laps(track_conn, 104, "NewTeam", [60.0] * 6, [0] * 6, base=recent, kart_number=2)
    payload = fleet_app._compute_live_fleet_pace(track_conn, 104, SEED_USER_ID)
    assert payload["field_ref_seconds"] == pytest.approx(60.0, abs=0.05)
