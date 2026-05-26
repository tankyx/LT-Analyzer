"""Phase 3 tests reuse the test_auth/ session-scoped app + fixtures."""

from tests.test_auth.conftest import (  # noqa: F401
    auth_app,
    reset_db,
    client,
    mock_email,
    authenticated_admin,
    authenticated_user,
    login_as,
    csrf_token,
)
