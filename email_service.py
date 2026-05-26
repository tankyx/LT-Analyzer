"""Transactional email for Phase 1.

Provider-abstracted so we can swap later. Today only Brevo is wired up.
Failures NEVER raise into the request handler — callers always get
(ok: bool, error: str). Anti-enumeration discipline is enforced at the
endpoint level, not here.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
DEFAULT_TIMEOUT = 10


class EmailSender:
    def send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html: str,
        text: str,
        tags: Iterable[str] | None = None,
    ) -> tuple[bool, str]:
        raise NotImplementedError


class BrevoEmailSender(EmailSender):
    def __init__(self, api_key: str, sender_email: str, sender_name: str):
        self.api_key = api_key
        self.sender_email = sender_email
        self.sender_name = sender_name

    def send(self, to_email, to_name, subject, html, text, tags=None):
        body = {
            "sender": {"name": self.sender_name, "email": self.sender_email},
            "to": [{"email": to_email, "name": to_name or to_email}],
            "subject": subject,
            "htmlContent": html,
            "textContent": text,
        }
        if tags:
            body["tags"] = list(tags)
        try:
            resp = requests.post(
                BREVO_ENDPOINT,
                headers={
                    "api-key": self.api_key,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data=json.dumps(body),
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning("Brevo send failed (network): %s", exc)
            return False, f"network_error: {exc}"
        if resp.status_code >= 300:
            logger.warning("Brevo send failed (%s): %s", resp.status_code, resp.text[:500])
            return False, f"http_{resp.status_code}: {resp.text[:200]}"
        return True, ""


class NullEmailSender(EmailSender):
    """Used when BREVO_API_KEY is empty. Drops payloads to /tmp/lt-mail/ + logs."""

    def __init__(self, spool_dir: str = "/tmp/lt-mail"):
        self.spool_dir = spool_dir

    def send(self, to_email, to_name, subject, html, text, tags=None):
        logger.info("NullEmailSender: to=%s subject=%r tags=%s", to_email, subject, list(tags or []))
        try:
            Path(self.spool_dir).mkdir(parents=True, exist_ok=True)
            stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
            safe_to = to_email.replace("/", "_").replace("\\", "_")
            path = Path(self.spool_dir) / f"{stamp}_{safe_to}.json"
            payload = {
                "to": to_email,
                "to_name": to_name,
                "subject": subject,
                "html": html,
                "text": text,
                "tags": list(tags or []),
            }
            path.write_text(json.dumps(payload, indent=2))
        except OSError as exc:
            logger.warning("NullEmailSender spool failed: %s", exc)
        return True, ""


def get_email_sender() -> EmailSender:
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    if not api_key:
        return NullEmailSender()
    sender_email = os.environ.get("BREVO_SENDER_EMAIL", "noreply@krranalyser.fr").strip()
    sender_name = os.environ.get("BREVO_SENDER_NAME", "LT-Analyzer").strip()
    return BrevoEmailSender(api_key, sender_email, sender_name)


# --- Template helpers --------------------------------------------------------

_BRAND = "LT-Analyzer"


def _frontend_base() -> str:
    return os.environ.get("FRONTEND_BASE_URL", "https://kart.krranalyser.fr").rstrip("/")


def _wrap(title: str, body_html: str) -> str:
    return (
        f"<!doctype html><html><body style=\"font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
        f"max-width:560px;margin:24px auto;color:#222;line-height:1.5;\">"
        f"<h2 style=\"margin:0 0 16px;\">{title}</h2>"
        f"{body_html}"
        f"<p style=\"margin-top:32px;color:#666;font-size:12px;\">— {_BRAND}</p>"
        f"</body></html>"
    )


def _button(href: str, label: str) -> str:
    return (
        f"<p style=\"margin:24px 0;\">"
        f"<a href=\"{href}\" "
        f"style=\"background:#1f6feb;color:#fff;padding:10px 18px;border-radius:6px;"
        f"text-decoration:none;display:inline-block;\">{label}</a>"
        f"</p>"
    )


def send_verification_email(sender: EmailSender, user: dict, token: str) -> tuple[bool, str]:
    link = f"{_frontend_base()}/verify-email?token={token}"
    title = "Confirm your email"
    body = (
        f"<p>Hi {user.get('username') or 'there'},</p>"
        f"<p>Thanks for signing up to {_BRAND}. Confirm your email to activate your account.</p>"
        f"{_button(link, 'Confirm email')}"
        f"<p style=\"font-size:12px;color:#666;\">"
        f"If the button doesn't work, paste this link into your browser:<br>"
        f"<a href=\"{link}\">{link}</a></p>"
        f"<p style=\"font-size:12px;color:#666;\">This link expires in 48 hours.</p>"
    )
    text = (
        f"Hi {user.get('username') or 'there'},\n\n"
        f"Confirm your email for {_BRAND}: {link}\n\n"
        f"This link expires in 48 hours. If you didn't sign up, ignore this email."
    )
    return sender.send(user["email"], user.get("username", ""), title, _wrap(title, body), text, tags=["verification"])


def send_password_reset_email(sender: EmailSender, user: dict, token: str) -> tuple[bool, str]:
    link = f"{_frontend_base()}/reset-password?token={token}"
    title = "Reset your password"
    body = (
        f"<p>Hi {user.get('username') or 'there'},</p>"
        f"<p>We received a request to reset your {_BRAND} password.</p>"
        f"{_button(link, 'Set a new password')}"
        f"<p style=\"font-size:12px;color:#666;\">"
        f"If the button doesn't work, paste this link into your browser:<br>"
        f"<a href=\"{link}\">{link}</a></p>"
        f"<p style=\"font-size:12px;color:#666;\">This link expires in 1 hour. "
        f"If you didn't request a reset, you can ignore this email — your password is unchanged.</p>"
    )
    text = (
        f"Reset your {_BRAND} password: {link}\n\n"
        f"This link expires in 1 hour. If you didn't request this, ignore the email."
    )
    return sender.send(user["email"], user.get("username", ""), title, _wrap(title, body), text, tags=["password-reset"])


def send_welcome_email(sender: EmailSender, user: dict) -> tuple[bool, str]:
    link = f"{_frontend_base()}/dashboard"
    title = f"Welcome to {_BRAND}"
    body = (
        f"<p>Hi {user.get('username') or 'there'},</p>"
        f"<p>Your account is active. You're in the closed beta, so concurrent dashboard use is limited "
        f"while we finish per-user isolation work. Thanks for testing — feedback welcome.</p>"
        f"{_button(link, 'Open the dashboard')}"
    )
    text = f"Welcome to {_BRAND}. Open the dashboard: {link}"
    return sender.send(user["email"], user.get("username", ""), title, _wrap(title, body), text, tags=["welcome"])
