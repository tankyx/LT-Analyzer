"""Fixtures for the core API endpoint test suite.

Re-exports the auth_app, client, and helper fixtures from the
test_auth package so they are available to tests in test_api.
"""

from tests.test_auth.conftest import (  # noqa: F401
    auth_app,
    authenticated_user,
    client,
    csrf_token,
    login_as,
    mock_email,
    reset_db,
)
