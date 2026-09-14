"""Reuse the fleet suite's app/track fixtures.

The pace report reads the same per-track lap_history and fleet tables, so the
fleet harness (temp auth.db + tracks.db + race_data_track_N.db, race_ui
imported fresh against them) is exactly the environment these tests need.
"""

from tests.test_fleet.conftest import (  # noqa: F401 — re-exported fixtures
    fleet_app,
    reset_fleet,
    track_conn,
    client,
    admin_user,
    normal_user,
)
