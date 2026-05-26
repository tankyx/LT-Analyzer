"""Phase 2 tests reuse the test_auth/ session-scoped app + reset_db fixtures."""

# Re-export the auth fixtures so test_phase2/ test modules can use them
# without duplicating setup. pytest discovers fixtures in parent conftests
# automatically as long as the test file imports from them or pytest's
# discovery finds them in scope.

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
