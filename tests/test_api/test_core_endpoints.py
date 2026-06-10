"""Core API endpoint integration tests.

Tests the essential REST endpoints of the LT-Analyzer Flask backend:
CSRF token issuance, auth check, track listing, registration validation,
login rejection, and CSRF enforcement on protected POST endpoints.
"""

import pytest

from tests.test_auth.conftest import csrf_token, login_as


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# GET /api/auth/csrf
# ---------------------------------------------------------------------------

def test_csrf_endpoint_returns_token(client):
    """GET /api/auth/csrf returns a valid csrfToken in the JSON payload."""
    resp = client.get("/api/auth/csrf")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "csrfToken" in body
    assert len(body["csrfToken"]) > 20, "csrfToken should be a meaningful token"


# ---------------------------------------------------------------------------
# GET /api/auth/check
# ---------------------------------------------------------------------------

def test_auth_check_returns_false_when_not_logged_in(client):
    """GET /api/auth/check returns {authenticated: false} for anonymous users."""
    resp = client.get("/api/auth/check")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body == {"authenticated": False}


# ---------------------------------------------------------------------------
# GET /api/tracks
# ---------------------------------------------------------------------------

def test_get_tracks_returns_list(client):
    """GET /api/tracks returns a JSON object with a 'tracks' list."""
    resp = client.get("/api/tracks")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "tracks" in body
    assert isinstance(body["tracks"], list)


# ---------------------------------------------------------------------------
# GET /api/tracks/status
# ---------------------------------------------------------------------------

def test_get_tracks_status_returns_list(client):
    """GET /api/tracks/status returns a JSON object with a 'tracks' list.

    When no MultiTrackManager is running the list is empty.
    """
    resp = client.get("/api/tracks/status")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "tracks" in body
    assert isinstance(body["tracks"], list)


# ---------------------------------------------------------------------------
# POST /api/auth/register – input validation
# ---------------------------------------------------------------------------

class TestRegisterInputValidation:
    """Registration payload validation happens *before* any database work,
    so these tests do not need an invite code even when REGISTRATION_OPEN is
    false."""

    def test_rejects_weak_password_too_short(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "testuser99",
            "email": "test@example.com",
            "password": "short",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "weak_password"

    def test_rejects_password_missing_uppercase(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "testuser98",
            "email": "test@example.com",
            "password": "alllowercase1!",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "weak_password"

    def test_rejects_password_missing_lowercase(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "testuser97",
            "email": "test@example.com",
            "password": "ALLUPPERCASE1!",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "weak_password"

    def test_rejects_password_missing_digit(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "testuser96",
            "email": "test@example.com",
            "password": "NoDigitsHere!",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "weak_password"

    def test_rejects_password_missing_special_char(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "testuser95",
            "email": "test@example.com",
            "password": "NoSpecial123456",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "weak_password"

    def test_rejects_invalid_username_too_short(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "ab",  # 2 chars, minimum is 3
            "email": "test@example.com",
            "password": "a-strong-pass-12",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_username"

    def test_rejects_invalid_username_with_space(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "user name",  # spaces are not allowed
            "email": "test@example.com",
            "password": "a-strong-pass-12",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_username"

    def test_rejects_invalid_username_with_special_chars(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "user@name!",  # special chars outside [_.-] are not allowed
            "email": "test@example.com",
            "password": "a-strong-pass-12",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_username"

    def test_rejects_reserved_username_admin(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "admin",
            "email": "test@example.com",
            "password": "a-strong-pass-12",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_username"

    def test_rejects_reserved_username_root(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "root",
            "email": "test@example.com",
            "password": "a-strong-pass-12",
            "accept_terms": True,
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_username"


# ---------------------------------------------------------------------------
# POST /api/auth/login – invalid credentials
# ---------------------------------------------------------------------------

class TestLoginRejection:

    def test_rejects_nonexistent_user(self, client):
        resp = login_as(client, "ghostuser", "whatever-password")
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Invalid credentials"

    def test_rejects_wrong_password(self, authenticated_user, client):
        resp = login_as(
            client,
            authenticated_user["username"],
            "wrong-password-12345",
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Invalid credentials"

    def test_rejects_empty_username(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "",
            "password": "somepassword",
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Username and password required"

    def test_rejects_empty_password(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "someone",
            "password": "",
            "turnstile_token": "t",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Username and password required"


# ---------------------------------------------------------------------------
# CSRF enforcement on protected POST endpoints
# ---------------------------------------------------------------------------

class TestCsrfEnforcement:

    def test_post_without_csrf_token_returns_403(
        self, authenticated_user, client
    ):
        """POST to a protected endpoint without X-CSRF-Token must be rejected."""
        login_as(
            client,
            authenticated_user["username"],
            authenticated_user["password"],
        )
        # /api/auth/logout requires both login_required and CSRF
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "csrf_failed"

    def test_post_with_valid_csrf_token_succeeds(
        self, authenticated_user, client
    ):
        """POST to a protected endpoint with a matching X-CSRF-Token succeeds."""
        login_as(
            client,
            authenticated_user["username"],
            authenticated_user["password"],
        )
        token = csrf_token(client)
        resp = client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": token},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("success") is True

    def test_csrf_enforcement_on_other_protected_endpoint(
        self, authenticated_user, client
    ):
        """POST to /api/start-simulation (admin-only) without CSRF also fails.

        The CSRF guard runs before the admin_required decorator, so we
        get 403 even without admin privileges.
        """
        login_as(
            client,
            authenticated_user["username"],
            authenticated_user["password"],
        )
        resp = client.post("/api/start-simulation")
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "csrf_failed"
