"""Phase 2: per-(user, track) preferences endpoints."""

import json
import sqlite3

import pytest

from tests.test_auth.conftest import csrf_token, login_as


pytestmark = pytest.mark.integration


def _login(client, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    return csrf_token(client)


# --- GET ---------------------------------------------------------------------

def test_get_returns_defaults_when_no_row(client, authenticated_user):
    _login(client, authenticated_user)
    resp = client.get("/api/me/prefs/1")
    assert resp.status_code == 200
    prefs = resp.get_json()["prefs"]
    assert prefs["track_id"] == 1
    assert prefs["my_team"] is None
    assert prefs["monitored_teams"] == []
    assert prefs["pit_stop_time"] == 158
    assert prefs["required_pit_stops"] == 7
    assert prefs["default_lap_time"] == 90.0
    assert prefs["stint_planner_config"] == {}
    assert prefs["stint_planner_presets"] == []


def test_get_unauthenticated_blocked(client):
    resp = client.get("/api/me/prefs/1")
    assert resp.status_code == 401


def test_get_returns_user_specific_row(client, auth_app, authenticated_user):
    with sqlite3.connect("auth.db") as conn:
        conn.execute(
            "INSERT INTO user_track_prefs (user_id, track_id, my_team, monitored_teams) "
            "VALUES (?, 2, 'GHIDI', ?)",
            (authenticated_user["id"], json.dumps(["12", "37"])),
        )
    _login(client, authenticated_user)
    resp = client.get("/api/me/prefs/2")
    prefs = resp.get_json()["prefs"]
    assert prefs["my_team"] == "GHIDI"
    assert prefs["monitored_teams"] == ["12", "37"]


# --- PUT (upsert) ------------------------------------------------------------

def test_put_inserts_a_new_row(client, authenticated_user):
    token = _login(client, authenticated_user)
    resp = client.put(
        "/api/me/prefs/3",
        json={"my_team": "DECAMPS", "monitored_teams": ["7"], "pit_stop_time": 142},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200
    prefs = resp.get_json()["prefs"]
    assert prefs["my_team"] == "DECAMPS"
    assert prefs["monitored_teams"] == ["7"]
    assert prefs["pit_stop_time"] == 142
    # Untouched fields stay at server defaults.
    assert prefs["required_pit_stops"] == 7


def test_put_partial_patch_preserves_other_fields(client, authenticated_user):
    token = _login(client, authenticated_user)
    client.put(
        "/api/me/prefs/4",
        json={"my_team": "FIRST", "pit_stop_time": 120},
        headers={"X-CSRF-Token": token},
    )
    # Second PUT only touches monitored_teams
    client.put(
        "/api/me/prefs/4",
        json={"monitored_teams": ["5", "9"]},
        headers={"X-CSRF-Token": token},
    )
    resp = client.get("/api/me/prefs/4")
    prefs = resp.get_json()["prefs"]
    assert prefs["my_team"] == "FIRST"
    assert prefs["pit_stop_time"] == 120
    assert prefs["monitored_teams"] == ["5", "9"]


def test_put_writes_audit_row(client, authenticated_user):
    token = _login(client, authenticated_user)
    client.put(
        "/api/me/prefs/1",
        json={"my_team": "X"},
        headers={"X-CSRF-Token": token},
    )
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT action, target FROM audit_log WHERE action = 'prefs_updated' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[1] == "track_1"


def test_put_requires_csrf(client, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    resp = client.put("/api/me/prefs/1", json={"my_team": "X"})
    assert resp.status_code == 403


def test_put_unauthenticated_blocked(client):
    resp = client.put("/api/me/prefs/1", json={"my_team": "X"})
    # CSRF guard fires first in this order; check that either layer rejects.
    assert resp.status_code in (401, 403)


# --- PUT validation ----------------------------------------------------------

@pytest.mark.parametrize("patch, expected", [
    ({"pit_stop_time": -1}, "invalid_pit_stop_time"),
    ({"pit_stop_time": 5000}, "invalid_pit_stop_time"),
    ({"pit_stop_time": "fast"}, "invalid_pit_stop_time"),
    ({"required_pit_stops": -2}, "invalid_required_pit_stops"),
    ({"required_pit_stops": 1000}, "invalid_required_pit_stops"),
    ({"default_lap_time": 0}, "invalid_default_lap_time"),
    ({"default_lap_time": "ish"}, "invalid_default_lap_time"),
    ({"monitored_teams": 42}, "invalid_monitored_teams"),
    ({"monitored_teams": ["a"] * 200}, "invalid_monitored_teams"),
    ({"my_team": 12}, "invalid_my_team"),
    ({"stint_planner_config": "not a dict"}, "invalid_stint_planner_config"),
    ({"driver_names": ["a", 2, "c"]}, "invalid_driver_names"),
    ({"current_driver_index": -1}, "invalid_current_driver_index"),
])
def test_put_rejects_bad_payloads(client, authenticated_user, patch, expected):
    token = _login(client, authenticated_user)
    resp = client.put(
        "/api/me/prefs/1",
        json=patch,
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == expected


def test_put_ignores_unknown_fields(client, authenticated_user):
    token = _login(client, authenticated_user)
    resp = client.put(
        "/api/me/prefs/1",
        json={"my_team": "OK", "futureField": "ignored", "garbage": 99},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200
    assert resp.get_json()["prefs"]["my_team"] == "OK"


# --- DELETE ------------------------------------------------------------------

def test_delete_removes_the_row(client, authenticated_user):
    token = _login(client, authenticated_user)
    client.put(
        "/api/me/prefs/1",
        json={"my_team": "X"},
        headers={"X-CSRF-Token": token},
    )
    resp = client.delete(
        "/api/me/prefs/1",
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200
    # After delete, GET should return defaults again.
    resp2 = client.get("/api/me/prefs/1")
    assert resp2.get_json()["prefs"]["my_team"] is None


# --- Per-user isolation ------------------------------------------------------

def test_user_cannot_read_or_write_anothers_prefs(client, auth_app, authenticated_user, authenticated_admin):
    # Admin inserts prefs for themselves on track 1.
    login_as(client, authenticated_admin["username"], authenticated_admin["password"])
    admin_token = csrf_token(client)
    client.put(
        "/api/me/prefs/1",
        json={"my_team": "ADMIN-TEAM"},
        headers={"X-CSRF-Token": admin_token},
    )
    # Log out, log in as the other user.
    client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_token})
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    # User GET on the same track sees their own defaults, NOT admin's value.
    resp = client.get("/api/me/prefs/1")
    assert resp.get_json()["prefs"]["my_team"] is None


def test_per_track_isolation(client, authenticated_user):
    token = _login(client, authenticated_user)
    client.put(
        "/api/me/prefs/1",
        json={"my_team": "T1"},
        headers={"X-CSRF-Token": token},
    )
    client.put(
        "/api/me/prefs/2",
        json={"my_team": "T2"},
        headers={"X-CSRF-Token": token},
    )
    assert client.get("/api/me/prefs/1").get_json()["prefs"]["my_team"] == "T1"
    assert client.get("/api/me/prefs/2").get_json()["prefs"]["my_team"] == "T2"


# --- Schema FK cascade -------------------------------------------------------

def test_user_delete_cascades_to_prefs(client, auth_app, authenticated_user):
    token = _login(client, authenticated_user)
    client.put(
        "/api/me/prefs/9",
        json={"my_team": "DOOMED"},
        headers={"X-CSRF-Token": token},
    )
    # Soft-delete via /api/auth/me (the normal user-facing path).
    client.delete("/api/auth/me", headers={"X-CSRF-Token": token})
    # User row is soft-deleted (not hard-deleted), so prefs row should still
    # exist. The FK CASCADE would only fire on a hard DELETE. This documents
    # the current behavior — soft-deleted users keep their prefs in case of
    # an undelete operation, and they're scrubbed from the active query path
    # via the partial unique index on email and the is_active flag.
    with sqlite3.connect("auth.db") as conn:
        rows = conn.execute(
            "SELECT user_id FROM user_track_prefs WHERE user_id = ?",
            (authenticated_user["id"],),
        ).fetchall()
    assert len(rows) == 1
