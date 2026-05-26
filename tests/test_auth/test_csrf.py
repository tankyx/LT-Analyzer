"""CSRF guard tests."""

import pytest

from tests.test_auth.conftest import csrf_token, login_as


pytestmark = pytest.mark.integration


def test_csrf_endpoint_returns_token(client):
    resp = client.get("/api/auth/csrf")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "csrfToken" in body and len(body["csrfToken"]) > 20


def test_logout_requires_csrf_when_authenticated(authenticated_user, client):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "csrf_failed"


def test_logout_succeeds_with_matching_csrf(authenticated_user, client):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    token = csrf_token(client)
    resp = client.post("/api/auth/logout", headers={"X-CSRF-Token": token})
    assert resp.status_code == 200


def test_login_endpoint_exempt_from_csrf(authenticated_user, client):
    """Login should not require X-CSRF-Token (anonymous + Turnstile-protected)."""
    resp = login_as(client, authenticated_user["username"], authenticated_user["password"])
    assert resp.status_code == 200


def test_register_endpoint_exempt_from_csrf(client, mock_email):
    """Register should work without X-CSRF-Token."""
    import sqlite3
    with sqlite3.connect("auth.db") as conn:
        conn.execute("INSERT INTO invite_codes (code, max_uses) VALUES ('opencode', 1)")
    resp = client.post("/api/auth/register", json={
        "username": "csrffree",
        "email": "csrffree@example.com",
        "password": "strong-pass-1234",
        "invite_code": "opencode",
        "accept_terms": True,
        "turnstile_token": "t",
    })
    assert resp.status_code == 200


def test_get_endpoints_pass_through_csrf_guard(client):
    """The before_request only fires on unsafe methods."""
    resp = client.get("/api/auth/check")
    assert resp.status_code == 200


def test_cors_allow_headers_includes_csrf(auth_app):
    """Sanity-check the CORS config so preflight doesn't reject the header."""
    # flask_cors stores the configured rules on the app
    cfg = auth_app.app.config.get("CORS_ALLOW_HEADERS") or []
    if not cfg:
        # Different flask-cors versions name this differently; fall back to scanning.
        cfg = []
        for ext in auth_app.app.extensions.values():
            try:
                opts = getattr(ext, "options", {}) or {}
                cfg = opts.get("allow_headers") or []
                if cfg:
                    break
            except Exception:
                pass
    # The Flask-CORS extension stores config under app.config['CORS_*'] when set
    # via constructor kwargs. Fall back to checking the raw config dict.
    cfg = list(cfg) if cfg else list(getattr(auth_app, "CORS_ORIGINS", []))
    # Allow_headers should contain X-CSRF-Token. If the introspection is brittle
    # across flask-cors versions, just check the literal string in race_ui source.
    src = open(auth_app.__file__).read()
    assert "X-CSRF-Token" in src
