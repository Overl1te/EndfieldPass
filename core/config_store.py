"""Lightweight runtime config helpers backed by DB tables."""

from __future__ import annotations

from copy import deepcopy
from threading import Lock
from time import monotonic

from django.apps import apps


GAME_DATA_KEYS = (
    "CHARACTER_OFFICIAL_NAMES",
    "WEAPON_OFFICIAL_NAMES",
    "CHARACTERS",
    "RARITY_ICONS",
    "CHARACTER_ROLES",
    "CHARACTER_WEAPONS",
    "CHARACTER_ELEMENTS",
)

_JSON_CACHE = {}
_JSON_CACHE_LOADED_AT = {}
_JSON_CACHE_TTL_SECONDS = 30.0
_JSON_CACHE_LOCK = Lock()


def reset_app_json_cache():
    """Clear runtime JSON cache (used after import/update operations)."""
    with _JSON_CACHE_LOCK:
        _JSON_CACHE.clear()
        _JSON_CACHE_LOADED_AT.clear()


def get_app_address(key: str, default: str = "") -> str:
    """Read address value by key from DB with graceful fallback."""
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return str(default or "")
    try:
        if not apps.ready:
            return str(default or "")
        app_address_model = apps.get_model("core", "AppAddress")
        row = app_address_model.objects.filter(key=normalized_key).values_list("value", flat=True).first()
        value = str(row or "").strip()
        return value or str(default or "")
    except Exception:
        return str(default or "")


def get_app_json(key: str, default=None, use_cache: bool = True):
    """Read JSON config payload by key from DB with TTL cache and fallback."""
    normalized_key = str(key or "").strip()
    fallback = deepcopy(default)
    if not normalized_key:
        return fallback

    try:
        if not apps.ready:
            return fallback

        now = monotonic()
        if use_cache:
            with _JSON_CACHE_LOCK:
                loaded_at = _JSON_CACHE_LOADED_AT.get(normalized_key, 0.0)
                cached = _JSON_CACHE.get(normalized_key, None)
                if (now - loaded_at) <= _JSON_CACHE_TTL_SECONDS and cached is not None:
                    return deepcopy(cached)

        model = apps.get_model("core", "AppJsonConfig")
        row = model.objects.filter(key=normalized_key).values_list("payload", flat=True).first()
        value = deepcopy(row)
        with _JSON_CACHE_LOCK:
            _JSON_CACHE[normalized_key] = value
            _JSON_CACHE_LOADED_AT[normalized_key] = now
        if value is None:
            return fallback
        return value
    except Exception:
        return fallback
