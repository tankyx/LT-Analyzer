"""Unit tests for email_service.py."""

import os
from unittest.mock import MagicMock, patch

import pytest

import email_service


pytestmark = pytest.mark.unit


def _ok_response(status=201, body="{}"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    return resp


def test_brevo_send_posts_expected_payload():
    sender = email_service.BrevoEmailSender(api_key="secret", sender_email="from@a", sender_name="Bot")
    with patch("email_service.requests.post", return_value=_ok_response()) as p:
        ok, err = sender.send("to@b", "Bob", "Hi", "<p>hi</p>", "hi", tags=["welcome"])
    assert ok is True and err == ""
    assert p.call_count == 1
    args, kwargs = p.call_args
    assert args[0] == email_service.BREVO_ENDPOINT
    assert kwargs["headers"]["api-key"] == "secret"
    assert kwargs["headers"]["content-type"] == "application/json"
    assert kwargs["timeout"] == 10
    import json
    body = json.loads(kwargs["data"])
    assert body["sender"] == {"name": "Bot", "email": "from@a"}
    assert body["to"] == [{"email": "to@b", "name": "Bob"}]
    assert body["subject"] == "Hi"
    assert body["htmlContent"] == "<p>hi</p>"
    assert body["textContent"] == "hi"
    assert body["tags"] == ["welcome"]


def test_brevo_send_returns_false_on_http_error():
    sender = email_service.BrevoEmailSender("k", "from@a", "Bot")
    with patch("email_service.requests.post", return_value=_ok_response(status=400, body="bad")):
        ok, err = sender.send("to@b", "B", "s", "h", "t")
    assert ok is False
    assert "http_400" in err


def test_brevo_send_returns_false_on_network_error():
    import requests as _r
    sender = email_service.BrevoEmailSender("k", "from@a", "Bot")
    with patch("email_service.requests.post", side_effect=_r.ConnectionError("boom")):
        ok, err = sender.send("to@b", "B", "s", "h", "t")
    assert ok is False
    assert "network_error" in err


def test_get_email_sender_returns_null_when_no_api_key(monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    s = email_service.get_email_sender()
    assert isinstance(s, email_service.NullEmailSender)


def test_get_email_sender_returns_brevo_when_api_key_present(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "abc")
    s = email_service.get_email_sender()
    assert isinstance(s, email_service.BrevoEmailSender)
    assert s.api_key == "abc"


def test_null_sender_spools_and_returns_ok(tmp_path):
    s = email_service.NullEmailSender(spool_dir=str(tmp_path))
    ok, err = s.send("a@b", "A", "subj", "<i>h</i>", "h", tags=["x"])
    assert ok is True and err == ""
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    import json
    payload = json.loads(files[0].read_text())
    assert payload["to"] == "a@b" and payload["subject"] == "subj" and payload["tags"] == ["x"]


def test_template_helper_builds_verify_link(monkeypatch):
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://example.test")
    sender = MagicMock()
    sender.send.return_value = (True, "")
    email_service.send_verification_email(sender, {"email": "x@y", "username": "u"}, "tok123")
    args, kwargs = sender.send.call_args
    _, _, _, html, text = args[:5]
    assert "https://example.test/verify-email?token=tok123" in html
    assert "https://example.test/verify-email?token=tok123" in text


def test_template_helper_reset_link(monkeypatch):
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://example.test")
    sender = MagicMock()
    sender.send.return_value = (True, "")
    email_service.send_password_reset_email(sender, {"email": "x@y", "username": "u"}, "rst")
    args, _ = sender.send.call_args
    assert "https://example.test/reset-password?token=rst" in args[3]
