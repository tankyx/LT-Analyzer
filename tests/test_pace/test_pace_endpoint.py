"""HTTP surface of the team-pace endpoint."""

from datetime import datetime

from tests.test_fleet.conftest import (  # noqa: F401 — fixtures
    seed_session,
    seed_laps,
    login,
    TRACK_ID,
)

BASE = datetime(2026, 5, 26, 12, 0, 0)
SESSION = 700
URL = f"/api/track/{TRACK_ID}/pace/team"


def _seed(conn):
    seed_session(conn, SESSION)
    for i, team in enumerate(("A", "B", "C")):
        seed_laps(conn, SESSION, team, [60.0] * 10, [0] * 10, base=BASE, kart_number=10 + i)
    seed_laps(conn, SESSION, "US", [58.0] * 10, [0] * 10, base=BASE, kart_number=7)


def test_requires_login(client):
    assert client.get(f"{URL}?team=US&session_id={SESSION}").status_code == 401


def test_returns_the_report_for_a_logged_in_user(client, normal_user, track_conn):
    _seed(track_conn)
    login(client, normal_user["username"], normal_user["password"])

    resp = client.get(f"{URL}?team=US&session_id={SESSION}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["matched_team"] == "US"
    assert body["current"]["residual"] < 0          # faster than the field
    assert body["verdict"]["verdict"] in {"keep", "watch", "consider_switch", "switch", "insufficient"}
    assert len(body["stints"]) == 1


def test_team_is_required(client, normal_user):
    login(client, normal_user["username"], normal_user["password"])
    resp = client.get(f"{URL}?session_id={SESSION}")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "team_required"


def test_an_overlong_team_name_is_rejected(client, normal_user):
    login(client, normal_user["username"], normal_user["password"])
    resp = client.get(f"{URL}?team={'x' * 200}&session_id={SESSION}")
    assert resp.status_code == 400


def test_a_bad_session_id_is_rejected(client, normal_user):
    login(client, normal_user["username"], normal_user["password"])
    resp = client.get(f"{URL}?team=US&session_id=abc")
    assert resp.status_code == 400


def test_unknown_track_404s(client, normal_user):
    login(client, normal_user["username"], normal_user["password"])
    resp = client.get(f"/api/track/99999/pace/team?team=US&session_id={SESSION}")
    assert resp.status_code == 404


def test_no_session_available_404s(client, normal_user):
    login(client, normal_user["username"], normal_user["password"])
    resp = client.get(f"{URL}?team=US")  # no live parser in tests
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "no_active_session"
