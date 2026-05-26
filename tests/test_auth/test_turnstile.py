"""Unit tests for turnstile.py."""

from unittest.mock import MagicMock, patch

import pytest

import turnstile


pytestmark = pytest.mark.unit


def _resp(status=200, json_body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body or {}
    return r


def test_verify_turnstile_soft_pass_when_no_secret(monkeypatch, caplog):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "")
    ok, err = turnstile.verify_turnstile("anything", "1.2.3.4")
    assert ok is True
    assert err == "disabled"


def test_verify_turnstile_success(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    with patch("turnstile.requests.post", return_value=_resp(json_body={"success": True})) as p:
        ok, err = turnstile.verify_turnstile("tok", "1.2.3.4")
    assert ok is True and err == ""
    args, kwargs = p.call_args
    assert args[0] == turnstile.SITEVERIFY_URL
    assert kwargs["data"]["secret"] == "secret"
    assert kwargs["data"]["response"] == "tok"
    assert kwargs["data"]["remoteip"] == "1.2.3.4"
    assert kwargs["timeout"] == 8


def test_verify_turnstile_fails_on_unsuccessful_response(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    with patch("turnstile.requests.post", return_value=_resp(json_body={"success": False, "error-codes": ["bad-token"]})):
        ok, err = turnstile.verify_turnstile("tok", None)
    assert ok is False
    assert "bad-token" in err


def test_verify_turnstile_missing_token(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    ok, err = turnstile.verify_turnstile("", "1.2.3.4")
    assert ok is False
    assert err == "missing_token"


def test_verify_turnstile_network_error_swallowed(monkeypatch):
    import requests as _r
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    with patch("turnstile.requests.post", side_effect=_r.Timeout("slow")):
        ok, err = turnstile.verify_turnstile("tok", None)
    assert ok is False and "network_error" in err


def test_require_turnstile_decorator(monkeypatch):
    """Spin up a tiny Flask app to exercise the decorator end-to-end."""
    from flask import Flask, jsonify
    app = Flask(__name__)

    @app.route("/x", methods=["POST"])
    @turnstile.require_turnstile()
    def hit():
        return jsonify({"ok": True})

    # No secret → soft-pass.
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "")
    with app.test_client() as c:
        resp = c.post("/x", json={})
        assert resp.status_code == 200

    # Secret set but token missing → 403.
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "s")
    with app.test_client() as c:
        resp = c.post("/x", json={})
        assert resp.status_code == 403
        assert resp.get_json() == {"error": "captcha_failed"}

    # Secret set + good token → 200 (mock siteverify success).
    with patch("turnstile.requests.post", return_value=_resp(json_body={"success": True})):
        with app.test_client() as c:
            resp = c.post("/x", json={"turnstile_token": "t"})
            assert resp.status_code == 200
