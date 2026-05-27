"""Registry CRUD, assignment append-only + correction semantics, stint-index
inference, and audit logging — exercised through the Flask client."""

import sqlite3
from datetime import datetime

from .conftest import login, TRACK_ID

BASE = f"/api/track/{TRACK_ID}/fleet"


def _hdr(token):
    return {"X-CSRF-Token": token}


def _track_db():
    return sqlite3.connect(f"race_data_track_{TRACK_ID}.db")


def test_create_and_list_kart(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    r = client.post(f"{BASE}/karts", json={"label": "K1", "notes": "blue seat"}, headers=_hdr(token))
    assert r.status_code == 201
    kart = r.get_json()["kart"]
    assert kart["label"] == "K1"

    r = client.get(f"{BASE}/karts")
    labels = [k["label"] for k in r.get_json()["karts"]]
    assert "K1" in labels


def test_duplicate_active_label_conflicts(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    client.post(f"{BASE}/karts", json={"label": "Dup"}, headers=_hdr(token))
    r = client.post(f"{BASE}/karts", json={"label": "Dup"}, headers=_hdr(token))
    assert r.status_code == 409


def test_soft_delete_preserves_history(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    kid = client.post(f"{BASE}/karts", json={"label": "Gone"}, headers=_hdr(token)).get_json()["kart"]["id"]
    r = client.delete(f"{BASE}/karts/{kid}", headers=_hdr(token))
    assert r.status_code == 200
    # Not in the active list...
    assert "Gone" not in [k["label"] for k in client.get(f"{BASE}/karts").get_json()["karts"]]
    # ...but still present when including inactive.
    all_karts = client.get(f"{BASE}/karts?active=0").get_json()["karts"]
    gone = next(k for k in all_karts if k["label"] == "Gone")
    assert gone["is_active"] is False


def test_update_kart_label(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    kid = client.post(f"{BASE}/karts", json={"label": "Old"}, headers=_hdr(token)).get_json()["kart"]["id"]
    r = client.put(f"{BASE}/karts/{kid}", json={"label": "New"}, headers=_hdr(token))
    assert r.status_code == 200
    assert "New" in [k["label"] for k in client.get(f"{BASE}/karts").get_json()["karts"]]


def test_assignment_append_only_and_correction(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    k1 = client.post(f"{BASE}/karts", json={"label": "A"}, headers=_hdr(token)).get_json()["kart"]["id"]
    k2 = client.post(f"{BASE}/karts", json={"label": "B"}, headers=_hdr(token)).get_json()["kart"]["id"]

    r = client.post(f"{BASE}/assignments",
                    json={"session_id": 500, "team_name": "TeamX", "fleet_kart_id": k1},
                    headers=_hdr(token))
    assert r.status_code == 201
    aid = r.get_json()["assignment"]["id"]

    # Correct it to kart B.
    r = client.post(f"{BASE}/assignments/correct",
                    json={"assignment_id": aid, "fleet_kart_id": k2}, headers=_hdr(token))
    assert r.status_code == 201

    rows = client.get(f"{BASE}/assignments?session_id=500").get_json()["assignments"]
    assert len(rows) == 2  # append-only: original (superseded) + correction
    by_id = {row["id"]: row for row in rows}
    assert by_id[aid]["superseded"] is True
    correction = next(row for row in rows if row["source"] == "correction")
    assert correction["superseded"] is False
    assert correction["fleet_kart_id"] == k2


def test_assignment_rejects_inactive_kart(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    kid = client.post(f"{BASE}/karts", json={"label": "Dead"}, headers=_hdr(token)).get_json()["kart"]["id"]
    client.delete(f"{BASE}/karts/{kid}", headers=_hdr(token))
    r = client.post(f"{BASE}/assignments",
                    json={"session_id": 1, "team_name": "T", "fleet_kart_id": kid}, headers=_hdr(token))
    assert r.status_code == 400


def test_stint_index_inferred_from_pit_count(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    kid = client.post(f"{BASE}/karts", json={"label": "S"}, headers=_hdr(token)).get_json()["kart"]["id"]
    # Seed lap_history with cumulative pit count peaking at 2.
    with _track_db() as conn:
        conn.execute("INSERT INTO race_sessions (session_id, start_time) VALUES (600, ?)",
                     (datetime.now().isoformat(),))
        for i, pit in enumerate([0, 1, 2]):
            conn.execute(
                "INSERT INTO lap_history (session_id, timestamp, team_name, lap_number, "
                "lap_time, pit_this_lap) VALUES (600, ?, 'Pitter', ?, '60.0', ?)",
                (datetime.now().isoformat(), i, pit))
        conn.commit()
    r = client.post(f"{BASE}/assignments",
                    json={"session_id": 600, "team_name": "Pitter", "fleet_kart_id": kid},
                    headers=_hdr(token))
    assert r.get_json()["assignment"]["stint_index"] == 2


def _seed_two_team_session(session_id=700):
    with _track_db() as conn:
        conn.execute("INSERT INTO race_sessions (session_id, start_time) VALUES (?, ?)",
                     (session_id, datetime.now().isoformat()))
        for team, kart in [("Alpha", 7), ("Bravo", 12)]:
            conn.execute(
                "INSERT INTO lap_times (session_id, timestamp, position, kart_number, team_name, "
                "last_lap, best_lap, pit_stops) VALUES (?, ?, 1, ?, ?, '60.0', '60.0', 0)",
                (session_id, datetime.now().isoformat(), kart, team))
        conn.commit()
    return session_id


def test_auto_populate_creates_karts_and_stint0_assignments(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    sid = _seed_two_team_session()
    r = client.post(f"{BASE}/auto-populate", json={"session_id": sid}, headers=_hdr(token))
    assert r.status_code == 201
    body = r.get_json()
    assert len(body["created_karts"]) == 2
    assert body["created_assignments"] == 2
    # Karts labelled K-<number> from the competition numbers.
    labels = sorted(k["label"] for k in client.get(f"{BASE}/karts").get_json()["karts"])
    assert labels == ["K-12", "K-7"]
    # Each team got a stint-0 assignment.
    rows = client.get(f"{BASE}/assignments?session_id={sid}").get_json()["assignments"]
    assert {row["team_name"] for row in rows} == {"Alpha", "Bravo"}
    assert all(row["stint_index"] == 0 and row["source"] == "auto" for row in rows)


def test_auto_populate_is_idempotent(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    sid = _seed_two_team_session(701)
    client.post(f"{BASE}/auto-populate", json={"session_id": sid}, headers=_hdr(token))
    r = client.post(f"{BASE}/auto-populate", json={"session_id": sid}, headers=_hdr(token))
    body = r.get_json()
    assert body["created_karts"] == []        # labels already exist
    assert body["created_assignments"] == 0   # teams already assigned
    assert body["skipped_teams"] == 2


def test_fleet_karts_are_per_user(client, admin_user, normal_user):
    """A kart created by one user is not visible to another."""
    atok = login(client, admin_user["username"], admin_user["password"])
    client.post(f"{BASE}/karts", json={"label": "AdminKart"}, headers=_hdr(atok))
    # Same client, switch session to the other user.
    utok = login(client, normal_user["username"], normal_user["password"])
    labels = [k["label"] for k in client.get(f"{BASE}/karts").get_json()["karts"]]
    assert "AdminKart" not in labels
    # And the other user can reuse the same label without a 409.
    r = client.post(f"{BASE}/karts", json={"label": "AdminKart"}, headers=_hdr(utok))
    assert r.status_code == 201


def test_release_dissociates_and_sets_lane(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    kid = client.post(f"{BASE}/karts", json={"label": "R"}, headers=_hdr(token)).get_json()["kart"]["id"]
    client.post(f"{BASE}/assignments",
                json={"session_id": 800, "team_name": "TeamR", "fleet_kart_id": kid},
                headers=_hdr(token))
    r = client.post(f"{BASE}/release",
                    json={"session_id": 800, "fleet_kart_id": kid, "lane": 3}, headers=_hdr(token))
    assert r.status_code == 200
    # The team's live assignment is now superseded (kart dissociated).
    rows = client.get(f"{BASE}/assignments?session_id=800").get_json()["assignments"]
    assert all(row["superseded"] for row in rows if row["fleet_kart_id"] == kid)
    # And the lane is persisted on the kart.
    with _track_db() as conn:
        lane = conn.execute("SELECT lane FROM fleet_karts WHERE id = ?", (kid,)).fetchone()[0]
    assert lane == 3


def test_set_lane(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    kid = client.post(f"{BASE}/karts", json={"label": "L"}, headers=_hdr(token)).get_json()["kart"]["id"]
    r = client.post(f"{BASE}/lane", json={"fleet_kart_id": kid, "lane": 2}, headers=_hdr(token))
    assert r.status_code == 200
    with _track_db() as conn:
        lane = conn.execute("SELECT lane FROM fleet_karts WHERE id = ?", (kid,)).fetchone()[0]
    assert lane == 2


def test_assigning_new_kart_frees_the_previous_one(client, admin_user):
    """Giving a team its next kart should make the old kart the team's
    non-holder (a later stint), so the old kart frees back to Available."""
    token = login(client, admin_user["username"], admin_user["password"])
    k1 = client.post(f"{BASE}/karts", json={"label": "first"}, headers=_hdr(token)).get_json()["kart"]["id"]
    k2 = client.post(f"{BASE}/karts", json={"label": "second"}, headers=_hdr(token)).get_json()["kart"]["id"]
    a1 = client.post(f"{BASE}/assignments",
                     json={"session_id": 801, "team_name": "Swappy", "fleet_kart_id": k1},
                     headers=_hdr(token)).get_json()["assignment"]
    a2 = client.post(f"{BASE}/assignments",
                     json={"session_id": 801, "team_name": "Swappy", "fleet_kart_id": k2},
                     headers=_hdr(token)).get_json()["assignment"]
    # The second assignment must sit at a higher stint so k2 is the holder.
    assert a2["stint_index"] > a1["stint_index"]


def test_audit_logged_on_create(client, admin_user):
    token = login(client, admin_user["username"], admin_user["password"])
    client.post(f"{BASE}/karts", json={"label": "Audited"}, headers=_hdr(token))
    with sqlite3.connect("auth.db") as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'fleet_kart_create'").fetchone()[0]
    assert n == 1
