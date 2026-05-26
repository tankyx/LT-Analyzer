"""Anonymous access to expensive team-data endpoints must be blocked."""

from unittest.mock import MagicMock

import pytest

from tests.test_auth.conftest import login_as


pytestmark = pytest.mark.integration

GATED_GETS = [
    "/api/team-data/top-teams?track_id=1&limit=10",
    "/api/team-data/search?q=foo&track_id=1",
    "/api/team-data/search-all?q=foo",
    "/api/team-data/cross-track-sessions?team=foo",
    "/api/team-data/sessions?track_id=1",
    "/api/team-data/stats?team=foo&track_id=1",
    "/api/team-data/all-laps?team=foo&track_id=1",
    "/api/team-data/session-laps?team=foo&track_id=1&session_id=1",
]


@pytest.mark.parametrize("path", GATED_GETS)
def test_anonymous_get_blocked_with_401(client, path):
    resp = client.get(path)
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Authentication required"


def test_test_endpoints_disabled_by_default(client, authenticated_admin):
    """ENABLE_TEST_ENDPOINTS=false means the routes never get registered → 404.

    We send a valid CSRF token so the request makes it past the CSRF guard;
    Flask's router is what returns 404 because no rule matches the path.
    """
    from tests.test_auth.conftest import csrf_token
    login_as(client, authenticated_admin["username"], authenticated_admin["password"])
    token = csrf_token(client)
    resp = client.post("/api/test/simulate-session/1", headers={"X-CSRF-Token": token})
    assert resp.status_code == 404
