"""wsgi.py must serve a LIVE app: importing it starts multi-track monitoring
exactly once (gunicorn -w 1 imports the module a single time, but the guard
must hold even if something re-triggers the call)."""

import sys
from unittest.mock import patch

import pytest


pytestmark = pytest.mark.integration


def test_wsgi_starts_monitoring_once(auth_app):
    sys.modules.pop('wsgi', None)
    with patch.object(auth_app, 'start_multi_track_monitoring') as start:
        import wsgi
        assert wsgi.app is auth_app.app
        assert start.call_count == 1
        # Idempotent: a second call must not start a second parser loop.
        wsgi._ensure_monitoring_started()
        assert start.call_count == 1
    sys.modules.pop('wsgi', None)
