"""Phase 3: rate limits on top-teams / search-all / cross-track-sessions."""

import pytest

from tests.test_auth.conftest import login_as


pytestmark = pytest.mark.integration


def test_top_teams_rate_limit(monkeypatch, auth_app, client, authenticated_user):
    # Reduce the threshold so this test runs fast.
    monkeypatch.setitem(auth_app.RATE_LIMITS, 'heavy_read_ip', (3, 3600))
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    # The underlying query against a non-existent track DB will 500, but the
    # rate-limit check fires BEFORE the DB hit. We're checking that the 429
    # appears after the 4th call.
    for i in range(3):
        client.get('/api/team-data/top-teams?track_id=99999&limit=10')
    resp = client.get('/api/team-data/top-teams?track_id=99999&limit=10')
    assert resp.status_code == 429
    assert resp.get_json()['error'] == 'rate_limited'


def test_search_all_rate_limit(monkeypatch, auth_app, client, authenticated_user):
    monkeypatch.setitem(auth_app.RATE_LIMITS, 'heavy_read_ip', (2, 3600))
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    client.get('/api/team-data/search-all?q=foo')
    client.get('/api/team-data/search-all?q=foo')
    resp = client.get('/api/team-data/search-all?q=foo')
    assert resp.status_code == 429


def test_cross_track_sessions_rate_limit(monkeypatch, auth_app, client, authenticated_user):
    monkeypatch.setitem(auth_app.RATE_LIMITS, 'heavy_read_ip', (1, 3600))
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    client.get('/api/team-data/cross-track-sessions?team=GHIDI')
    resp = client.get('/api/team-data/cross-track-sessions?team=GHIDI')
    assert resp.status_code == 429
