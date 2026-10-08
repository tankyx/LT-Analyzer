"""Reuse the fleet suite's app/track fixtures.

The session-gaps endpoint reads the per-track `lap_history` (and validates
track_id against tracks.db), so the fleet harness — temp auth.db + tracks.db +
race_data_track_1.db — is exactly the environment it needs.
"""

from tests.test_fleet.conftest import (  # noqa: F401 — re-exported fixtures
    fleet_app,
    reset_fleet,
    track_conn,
    client,
    admin_user,
    normal_user,
    login,
    TRACK_ID,
)
