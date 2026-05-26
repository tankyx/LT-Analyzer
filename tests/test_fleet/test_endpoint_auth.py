"""Auth gating: reads + writes all require login (per-user data); any logged-in
user can manage their own fleet; 404 for unknown tracks once authenticated."""

from .conftest import login, TRACK_ID

BASE = f"/api/track/{TRACK_ID}/fleet"


def _hdr(token):
    return {"X-CSRF-Token": token}


def test_reads_require_login(client):
    # Per-user data: an anonymous caller can't read anyone's board.
    assert client.get(f"{BASE}/karts").status_code == 401
    assert client.get(f"{BASE}/state").status_code == 401
    assert client.get(f"{BASE}/assignments").status_code == 401


def test_any_logged_in_user_can_create_kart(client, normal_user):
    token = login(client, normal_user["username"], normal_user["password"])
    r = client.post(f"{BASE}/karts", json={"label": "X"}, headers=_hdr(token))
    assert r.status_code == 201


def test_any_logged_in_user_can_auto_populate(client, normal_user):
    token = login(client, normal_user["username"], normal_user["password"])
    # No session seeded -> 400 (not 403); proves it's not admin-gated.
    r = client.post(f"{BASE}/auto-populate", json={}, headers=_hdr(token))
    assert r.status_code == 400


def test_create_unauthenticated_rejected(client):
    r = client.post(f"{BASE}/karts", json={"label": "X"})
    assert r.status_code in (401, 403)


def test_assignment_requires_login(client):
    r = client.post(f"{BASE}/assignments",
                    json={"session_id": 1, "team_name": "T", "fleet_kart_id": 1})
    assert r.status_code in (401, 403)


def test_unknown_track_404_when_authenticated(client, normal_user):
    login(client, normal_user["username"], normal_user["password"])
    assert client.get("/api/track/9999/fleet/karts").status_code == 404
    assert client.get("/api/track/9999/fleet/state").status_code == 404
