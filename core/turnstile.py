"""Cloudflare Turnstile helpers."""

from __future__ import annotations

from typing import Optional

import requests
from django.conf import settings

DEFAULT_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
DEFAULT_TIMEOUT_SECONDS = 5.0


def get_turnstile_site_key() -> str:
    """Return configured public Turnstile site key."""
    return str(getattr(settings, "TURNSTILE_SITE_KEY", "") or "").strip()


def get_turnstile_secret_key() -> str:
    """Return configured private Turnstile secret key."""
    return str(getattr(settings, "TURNSTILE_SECRET_KEY", "") or "").strip()


def is_turnstile_enabled() -> bool:
    """Turnstile is active only when enabled and both keys are present."""
    enabled = bool(getattr(settings, "TURNSTILE_ENABLED", False))
    return enabled and bool(get_turnstile_site_key()) and bool(get_turnstile_secret_key())


def verify_turnstile_token(token: str, remote_ip: Optional[str] = None) -> bool:
    """Verify Turnstile response token with Cloudflare."""
    if not is_turnstile_enabled():
        return True

    normalized_token = str(token or "").strip()
    if not normalized_token:
        return False

    payload = {
        "secret": get_turnstile_secret_key(),
        "response": normalized_token,
    }
    remote = str(remote_ip or "").strip()
    if remote:
        payload["remoteip"] = remote

    verify_url = str(getattr(settings, "TURNSTILE_VERIFY_URL", DEFAULT_VERIFY_URL) or DEFAULT_VERIFY_URL).strip()
    timeout = float(getattr(settings, "TURNSTILE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS) or DEFAULT_TIMEOUT_SECONDS)

    try:
        response = requests.post(verify_url, data=payload, timeout=timeout)
    except requests.RequestException:
        return False

    if response.status_code != 200:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return bool(body.get("success"))
