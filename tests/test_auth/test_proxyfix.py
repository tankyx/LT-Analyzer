"""ProxyFix wiring: X-Forwarded-For should become request.remote_addr."""

import pytest

from werkzeug.middleware.proxy_fix import ProxyFix


pytestmark = pytest.mark.integration


def test_proxyfix_is_in_wsgi_stack(auth_app):
    """The wsgi_app should be wrapped in ProxyFix so nginx's X-Forwarded-For is honoured."""
    wsgi = auth_app.app.wsgi_app
    # ProxyFix wraps the original app. Walk through any nested wrappers.
    seen = []
    cur = wsgi
    for _ in range(10):
        seen.append(type(cur).__name__)
        if isinstance(cur, ProxyFix):
            break
        cur = getattr(cur, "app", None) or getattr(cur, "wsgi_app", None)
        if cur is None:
            break
    assert any(t == "ProxyFix" for t in seen), (
        f"ProxyFix not found in wsgi stack: {seen}"
    )


def test_forwarded_for_lands_in_remote_addr(auth_app, client):
    """End-to-end: hit /api/auth/check with X-Forwarded-For and confirm the audit
    log captures it (login_failed audit records request.remote_addr)."""
    import sqlite3

    # Force a login_failed to record an audit row.
    client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "wrong-pass-12", "turnstile_token": "t"},
        headers={"X-Forwarded-For": "203.0.113.7"},
    )
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT ip_address FROM audit_log WHERE action = 'login_failed' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[0] == "203.0.113.7"
