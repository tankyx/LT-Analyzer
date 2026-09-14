"""Team pace tracking: pace against the field at the same moment, stint by
stint, and the keep-or-switch read that follows from it."""

from datetime import datetime, timedelta

import pytest

from tests.test_fleet.conftest import (  # noqa: F401 — fixtures
    seed_session,
    seed_laps,
    seed_fleet_kart,
    seed_assignment,
    TRACK_ID,
    SEED_USER_ID,
)

BASE = datetime(2026, 5, 26, 12, 0, 0)
SESSION = 500


def _report(app, conn, team="US", user_id=None):
    return app._compute_team_pace(conn, SESSION, team, user_id=user_id)


def _seed_field(conn, lap_secs, teams=("A", "B", "C", "D"), base=None, pits=None):
    """A field of evenly matched teams, so the median is lap_secs."""
    for i, t in enumerate(teams):
        seed_laps(conn, SESSION, t, lap_secs, pits or [0] * len(lap_secs),
                  base=base or BASE, kart_number=10 + i)


def test_pace_is_measured_against_the_field_not_the_clock(fleet_app, track_conn):
    """A team lapping 1.5s under the field median reads as 1.5s faster."""
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 12)
    seed_laps(track_conn, SESSION, "US", [58.5] * 12, [0] * 12, base=BASE, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert report["matched_team"] == "US"
    assert report["current"]["residual"] == pytest.approx(-1.5, abs=0.05)
    assert report["current"]["field_median"] == pytest.approx(60.0, abs=0.05)


def test_our_own_laps_are_left_out_of_the_field_median(fleet_app, track_conn):
    """On a small grid, a dominant team must not flatter its own reference."""
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 12, teams=("A", "B"))
    seed_laps(track_conn, SESSION, "US", [50.0] * 12, [0] * 12, base=BASE, kart_number=7)

    report = _report(fleet_app, track_conn)
    # Field median is 60.0 (A and B only), not pulled down towards 50.
    assert report["current"]["field_median"] == pytest.approx(60.0, abs=0.05)
    assert report["current"]["residual"] == pytest.approx(-10.0, abs=0.05)


def test_ghost_rows_never_enter_the_field_median(fleet_app, track_conn):
    """"G - " rows are timing artefacts, not cars."""
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 12, teams=("A", "B", "C"))
    seed_laps(track_conn, SESSION, "G - GHOST", [200.0] * 12, [0] * 12, base=BASE, kart_number=99)
    seed_laps(track_conn, SESSION, "US", [60.0] * 12, [0] * 12, base=BASE, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert report["current"]["field_median"] == pytest.approx(60.0, abs=0.05)
    assert report["current"]["residual"] == pytest.approx(0.0, abs=0.05)


def test_conditions_are_cancelled_so_a_slower_clock_is_not_a_slower_kart(fleet_app, track_conn):
    """Everyone slows by 3s (rain, dusk). Our pace vs the field is unchanged."""
    seed_session(track_conn, SESSION)
    # Stint 1: field 60.0, us 59.0.  Stint 2: field 63.0, us 62.0.
    _seed_field(track_conn, [60.0] * 8)
    seed_laps(track_conn, SESSION, "US", [59.0] * 8, [0] * 8, base=BASE, kart_number=7)

    later = BASE + timedelta(minutes=30)
    _seed_field(track_conn, [63.0] * 8, base=later, pits=[1] * 8)
    seed_laps(track_conn, SESSION, "US", [62.0] * 8, [1] * 8, base=later, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert len(report["stints"]) == 2
    # Raw means differ by 3s; residuals do not.
    assert report["stints"][0]["residual"] == pytest.approx(-1.0, abs=0.1)
    assert report["stints"][1]["residual"] == pytest.approx(-1.0, abs=0.1)
    assert report["verdict"]["verdict"] == "keep"


def test_a_slower_kart_than_our_own_norm_suggests_switching(fleet_app, track_conn):
    """Two good stints then a bad one: the kart, not the conditions."""
    seed_session(track_conn, SESSION)
    for stint, (field, us) in enumerate([(60.0, 59.0), (60.0, 59.0), (60.0, 61.5)]):
        base = BASE + timedelta(minutes=30 * stint)
        _seed_field(track_conn, [field] * 8, base=base, pits=[stint] * 8)
        seed_laps(track_conn, SESSION, "US", [us] * 8, [stint] * 8, base=base, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert len(report["stints"]) == 3
    assert report["own_norm_residual"] == pytest.approx(-1.0, abs=0.1)
    assert report["verdict"]["verdict"] in ("switch", "consider_switch")
    assert report["verdict"]["delta_vs_own_norm"] == pytest.approx(2.5, abs=0.2)


def test_a_kart_matching_our_norm_is_kept(fleet_app, track_conn):
    seed_session(track_conn, SESSION)
    for stint in range(3):
        base = BASE + timedelta(minutes=30 * stint)
        _seed_field(track_conn, [60.0] * 8, base=base, pits=[stint] * 8)
        seed_laps(track_conn, SESSION, "US", [59.0] * 8, [stint] * 8, base=base, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert report["verdict"]["verdict"] == "keep"
    assert abs(report["verdict"]["delta_vs_own_norm"]) < 0.3


def test_a_fading_stint_is_detected(fleet_app, track_conn):
    """Second half of the stint is 1s slower while the field holds steady."""
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 14)
    seed_laps(track_conn, SESSION, "US", [59.0] * 7 + [60.2] * 7, [0] * 14, base=BASE, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert report["trend"] == "fading"
    assert report["trend_drift"] > 0


def test_a_steady_stint_is_not_called_fading(fleet_app, track_conn):
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 14)
    seed_laps(track_conn, SESSION, "US", [59.0] * 14, [0] * 14, base=BASE, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert report["trend"] == "stable"


def test_recent_pace_reflects_the_last_few_laps(fleet_app, track_conn):
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 14)
    seed_laps(track_conn, SESSION, "US", [59.0] * 9 + [62.0] * 5, [0] * 14, base=BASE, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert report["recent"]["laps"] == 5
    assert report["recent"]["residual"] == pytest.approx(2.0, abs=0.1)


def test_too_few_laps_reads_insufficient_rather_than_guessing(fleet_app, track_conn):
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 10)
    seed_laps(track_conn, SESSION, "US", [59.0] * 3, [0] * 3, base=BASE, kart_number=7)

    report = _report(fleet_app, track_conn)
    assert report["verdict"]["verdict"] == "insufficient"
    assert report["current"]["confidence"] == "low"


def test_a_team_with_no_laps_is_reported_not_crashed(fleet_app, track_conn):
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 10)

    report = _report(fleet_app, track_conn, team="NOT RACING")
    assert report["matched_team"] is None
    assert report["stints"] == []
    assert report["verdict"]["verdict"] == "insufficient"


def test_team_name_matching_tolerates_case_and_spacing(fleet_app, track_conn):
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 10)
    seed_laps(track_conn, SESSION, "Us Racing", [59.0] * 10, [0] * 10, base=BASE, kart_number=7)

    report = _report(fleet_app, track_conn, team="  us racing ")
    assert report["matched_team"] == "Us Racing"


def test_the_physical_kart_is_named_when_a_fleet_is_configured(fleet_app, track_conn):
    seed_session(track_conn, SESSION)
    _seed_field(track_conn, [60.0] * 10)
    seed_laps(track_conn, SESSION, "US", [59.0] * 10, [0] * 10, base=BASE, kart_number=7)
    kid = seed_fleet_kart(track_conn, "K-12")
    seed_assignment(track_conn, SESSION, "US", kid, 0)

    report = _report(fleet_app, track_conn, user_id=SEED_USER_ID)
    assert report["kart"] == {"fleet_kart_id": kid, "label": "K-12"}


def test_confidence_grows_with_laps(fleet_app, track_conn):
    assert fleet_app._confidence_for(2) == "low"
    assert fleet_app._confidence_for(6) == "medium"
    assert fleet_app._confidence_for(15) == "high"
