"""Cloudflare Turnstile server-side verification.

Empty TURNSTILE_SECRET_KEY → soft-pass with a warning. Lets dev work without
a Cloudflare account and gives the operator an escape hatch if Cloudflare
is globally down.
"""

import logging
import os
from functools import wraps

import requests
from flask import jsonify, request

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
DEFAULT_TIMEOUT = 8


def verify_turnstile(token: str, remote_ip: str | None = None) -> tuple[bool, str]:
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        if os.environ.get('FLASK_ENV') == 'production':
            logger.error("Turnstile disabled in production (TURNSTILE_SECRET_KEY is empty) — bot protection is OFF.")
        else:
            logger.warning("Turnstile disabled (TURNSTILE_SECRET_KEY is empty) — passing through.")
        return True, "disabled"
    if not token:
        return False, "missing_token"
    payload = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        resp = requests.post(SITEVERIFY_URL, data=payload, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Turnstile network error: %s", exc)
        return False, f"network_error: {exc}"
    if resp.status_code >= 300:
        return False, f"http_{resp.status_code}"
    try:
        data = resp.json()
    except ValueError:
        return False, "invalid_response"
    if not data.get("success"):
        codes = data.get("error-codes", [])
        return False, f"failed: {','.join(codes)}"
    return True, ""


def require_turnstile(field: str = "turnstile_token"):
    """Decorator. Reads the token from JSON body, 403s on failure."""

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            data = request.get_json(silent=True) or {}
            token = (data.get(field) or "").strip()
            ok, err = verify_turnstile(token, request.remote_addr)
            if not ok:
                logger.info("Turnstile rejected request: %s", err)
                return jsonify({"error": "captcha_failed"}), 403
            return fn(*args, **kwargs)

        return wrapped

    return decorator
