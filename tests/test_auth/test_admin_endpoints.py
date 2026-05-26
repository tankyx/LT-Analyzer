"""Admin invite-code and audit-log endpoints."""

import sqlite3

import pytest

from tests.test_auth.conftest import csrf_token, login_as


pytestmark = pytest.mark.integration


def _admin_login(client, admin):
    login_as(client, admin["username"], admin["password"])
    return csrf_token(client)


def test_create_invite_code_admin_only(client, authenticated_admin):
    token = _admin_login(client, authenticated_admin)
    resp = client.post(
        "/api/admin/invite-codes",
        json={"max_uses": 5, "note": "spring"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["code"] and len(body["code"]) > 5
    assert body["max_uses"] == 5
    # Audit row written
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT action FROM audit_log WHERE action = 'admin_invite_created'"
        ).fetchone()
    assert row is not None


def test_create_invite_code_rejects_non_admin(client, authenticated_user):
    token = csrf_token(client)
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    token = csrf_token(client)
    resp = client.post(
        "/api/admin/invite-codes",
        json={"max_uses": 1},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 403


def test_list_invites_returns_codes(client, authenticated_admin):
    _admin_login(client, authenticated_admin)
    with sqlite3.connect("auth.db") as conn:
        conn.execute("INSERT INTO invite_codes (code, max_uses) VALUES ('listme', 3)")
    resp = client.get("/api/admin/invite-codes")
    assert resp.status_code == 200
    invites = resp.get_json()["invites"]
    codes = {i["code"] for i in invites}
    assert "listme" in codes


def test_revoke_invite_code(client, authenticated_admin):
    token = _admin_login(client, authenticated_admin)
    with sqlite3.connect("auth.db") as conn:
        cur = conn.execute("INSERT INTO invite_codes (code, max_uses) VALUES ('revoke', 2)")
        invite_id = cur.lastrowid
    resp = client.delete(
        f"/api/admin/invite-codes/{invite_id}",
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT id FROM invite_codes WHERE id = ?", (invite_id,)
        ).fetchone()
    assert row is None


def test_invalid_max_uses_rejected(client, authenticated_admin):
    token = _admin_login(client, authenticated_admin)
    resp = client.post(
        "/api/admin/invite-codes",
        json={"max_uses": 0},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 400
    resp = client.post(
        "/api/admin/invite-codes",
        json={"max_uses": "potato"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 400


def test_audit_log_filterable(client, authenticated_admin, auth_app):
    _admin_login(client, authenticated_admin)
    # Seed
    auth_app._audit("test_action_a", actor_user_id=authenticated_admin["id"], target="x")
    auth_app._audit("test_action_b", actor_user_id=authenticated_admin["id"], target="y")
    resp = client.get(f"/api/admin/audit-log?action=test_action_a")
    assert resp.status_code == 200
    rows = resp.get_json()["rows"]
    actions = {r["action"] for r in rows}
    assert actions == {"test_action_a"}


def test_audit_log_admin_only(client, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    resp = client.get("/api/admin/audit-log")
    assert resp.status_code == 403
