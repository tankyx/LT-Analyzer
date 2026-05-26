"""Direct unit tests of _rate_limit_hit and _audit helpers."""

import sqlite3

import pytest


pytestmark = pytest.mark.integration  # they touch the real auth.db


def test_rate_limit_hit_returns_true_after_threshold(auth_app, reset_db):
    # 3 hits/hour bucket; key='ip1'
    for i in range(2):
        assert auth_app._rate_limit_hit("test_bucket", "ip1", max_events=3, window_seconds=3600) is False
    # 3rd insertion lands at count=3 → True
    assert auth_app._rate_limit_hit("test_bucket", "ip1", max_events=3, window_seconds=3600) is True


def test_rate_limit_per_key_isolated(auth_app, reset_db):
    for _ in range(5):
        auth_app._rate_limit_hit("b", "ip-a", max_events=10, window_seconds=3600)
    # different key, fresh count
    assert auth_app._rate_limit_hit("b", "ip-b", max_events=2, window_seconds=3600) is False


def test_rate_limit_zero_max_disabled(auth_app, reset_db):
    assert auth_app._rate_limit_hit("b", "ip", max_events=0, window_seconds=3600) is False


def test_audit_writes_row(auth_app, reset_db):
    with auth_app.app.test_request_context("/anything", headers={"User-Agent": "ua"}):
        auth_app._audit("test_event", actor_user_id=42, target="t1", details={"k": "v"})
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT actor_user_id, action, target, user_agent, details "
            "FROM audit_log WHERE action = 'test_event'"
        ).fetchone()
    assert row is not None
    assert row[0] == 42 and row[1] == "test_event" and row[2] == "t1"
    assert row[3] == "ua"
    assert '"k": "v"' in row[4]


def test_audit_handles_non_serializable_details(auth_app, reset_db):
    class Weird:
        def __repr__(self):
            return "<weird>"

    with auth_app.app.test_request_context("/"):
        auth_app._audit("weird_event", details={"obj": Weird()})
    with sqlite3.connect("auth.db") as conn:
        row = conn.execute(
            "SELECT details FROM audit_log WHERE action = 'weird_event'"
        ).fetchone()
    assert row is not None
    # default=str makes it serializable
    assert "weird" in row[0]


def test_audit_swallows_db_errors(auth_app, monkeypatch):
    """Even if the DB is broken, _audit must not raise."""
    def boom(*_a, **_k):
        raise sqlite3.Error("simulated")
    monkeypatch.setattr(sqlite3, "connect", boom)
    # Should not raise
    with auth_app.app.test_request_context("/"):
        auth_app._audit("never_lands")
