"""Device API fixtures.

Reuses the fleet harness (temp auth.db + tracks.db + race_data_track_1.db,
race_ui imported fresh) and adds a fake live parser so `/api/device/live`
and `/api/device/stream` have standings to serve without a WebSocket feed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.test_fleet.conftest import (  # noqa: F401 — re-exported fixtures
    TRACK_ID,
    fleet_app,
    reset_fleet,
    track_conn,
    client,
    admin_user,
    normal_user,
    login,
)


STANDINGS = [
    {'Status': 'On Track', 'Position': '1', 'Kart': '7', 'Team': '1 - LEADERS',
     'Last Lap': '1:19.100', 'Best Lap': '1:18.900', 'Gap': '', 'RunTime': '0:41:02', 'Pit Stops': '2'},
    {'Status': 'On Track', 'Position': '2', 'Kart': '12', 'Team': '1 - MY TEAM',
     'Last Lap': '1:19.701', 'Best Lap': '1:19.233', 'Gap': '+1.245', 'RunTime': '0:41:03', 'Pit Stops': '2'},
    {'Status': 'Pit-in', 'Position': '3', 'Kart': '3', 'Team': '2 - CHASERS',
     'Last Lap': '1:20.010', 'Best Lap': '1:19.500', 'Gap': '8.032', 'RunTime': '0:41:05', 'Pit Stops': '3'},
]


class FakeParser:
    def __init__(self, session_id=17, teams=None, active=True):
        self.current_session_id = session_id
        self.session_active_status = active
        self.teams = [dict(t) for t in (teams or STANDINGS)]

    def get_current_standings(self):
        return pd.DataFrame(self.teams)


class FakeManager:
    def __init__(self, parser):
        self.parsers = {TRACK_ID: parser}


@pytest.fixture(autouse=True)
def no_rate_limit(fleet_app, monkeypatch):
    """The per-token throttle is real (~1 req / 2 s); tests fire faster than
    a board would. `test_rate_limit_carries_retry_after` restores it."""
    import race_app.blueprints.device_routes as dr
    monkeypatch.setattr(dr, '_rate_limit_hit', lambda *a, **k: False)
    fleet_app._rate_limit_reset()


@pytest.fixture
def hub(fleet_app):
    """The hub singleton the *running* app uses. `fleet_app` re-imports the
    race_app package, so a module-level import in a test file would hold a
    stale instance."""
    from race_app.device_hub import hub as live_hub
    return live_hub


@pytest.fixture
def live_parser(fleet_app, monkeypatch):
    """Install a fake live session on track 1; returns the parser so tests
    can mutate standings and trigger the update listener."""
    parser = FakeParser()
    monkeypatch.setattr(fleet_app, 'multi_track_manager', FakeManager(parser))
    from race_app.device_hub import hub
    hub.reset()
    yield parser
    hub.reset()


@pytest.fixture
def device_token(fleet_app, client, normal_user):
    """Log in as the normal user, mint a token, and return (token, id, csrf)."""
    csrf = login(client, normal_user['username'], normal_user['password'])
    r = client.post('/api/device/tokens', json={'label': 'datalogger-p4'},
                    headers={'X-CSRF-Token': csrf})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    return {'token': body['token'], 'id': body['id'], 'csrf': csrf, 'user': normal_user}


def bearer(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def read_frames(resp, n: int, timeout_frames: int = 3) -> list:
    """Pull `n` SSE frames off a streamed test-client response."""
    frames = []
    it = resp.iter_encoded()
    while len(frames) < n:
        chunk = next(it).decode('utf-8')
        frames.append(chunk)
    return frames
