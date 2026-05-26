"""Phase 2: the legacy global-state endpoints must no longer exist."""

import pytest

from tests.test_auth.conftest import csrf_token, login_as


pytestmark = pytest.mark.integration


def test_update_monitoring_404(client, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    token = csrf_token(client)
    resp = client.post(
        "/api/update-monitoring",
        json={"myTeam": "X", "monitoredTeams": []},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 404


def test_update_pit_config_404(client, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    token = csrf_token(client)
    resp = client.post(
        "/api/update-pit-config",
        json={"pitStopTime": 200, "requiredPitStops": 8},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 404
