"""Main application views and import/sync orchestration.

This module contains:
- dashboard/characters rendering logic
- history import/export flows
- OAuth cloud connection and cloud sync endpoints
- asynchronous import progress tracking
"""

import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from .cloud import (
    CLOUD_PROVIDER_CHOICES,
    SYNC_FILE_NAME,
    SYNC_FOLDER_NAME,
    SYNC_PROVIDER_CHOICES,
    CloudIntegrationError,
    build_oauth_authorization_url,
    exchange_oauth_code,
    export_payload_to_cloud,
    import_payload_from_cloud,
    refresh_oauth_token,
)
from .models import ImportSession, Pull
from .localization import (
    SITE_LANGUAGE_COOKIE_KEY,
    SITE_LANGUAGE_SESSION_KEY,
    get_request_language,
    normalize_language_code,
    translate,
)
from .services import fetch_all_records


IMPORT_PROGRESS = {}
IMPORT_PROGRESS_LOCK = threading.Lock()

POOL_LABELS = {
    "E_CharacterGachaPoolType_Standard": "dashboard.pool.standard",
    "E_CharacterGachaPoolType_Special": "dashboard.pool.character",
    "E_CharacterGachaPoolType_Beginner": "dashboard.pool.beginner",
}

DASHBOARD_POOLS = [
    {
        "title_key": "dashboard.pool.character",
        "source_pool_type": "E_CharacterGachaPoolType_Special",
        "pool_id_fallback": "special",
        "six_star_limit": 80,
        "five_star_limit": 10,
    },
    {
        "title_key": "dashboard.pool.standard",
        "source_pool_type": "E_CharacterGachaPoolType_Standard",
        "pool_id_fallback": "standard",
        "six_star_limit": 80,
        "five_star_limit": 10,
    },
    {
        "title_key": "dashboard.pool.beginner",
        "source_pool_type": "E_CharacterGachaPoolType_Beginner",
        "pool_id_fallback": "beginner",
        "six_star_limit": 80,
        "five_star_limit": 10,
    },
]

OFFICIAL_REPOSITORY_URL = "https://github.com/Overl1te/EndfieldPass"
DEFAULT_DONATE_URL = "https://github.com/sponsors/Overl1te"

CLOUD_AUTH_SESSION_KEY = "cloud_auth"
CLOUD_OAUTH_STATE_SESSION_KEY = "cloud_oauth_state"
SETTINGS_FLASH_SESSION_KEY = "settings_flash"


def _tr_lang(language, key, **kwargs):
    """Translate a key for the provided language code."""
    return translate(language, key, **kwargs)


def _tr(request, key, **kwargs):
    """Translate a key based on current request language."""
    return _tr_lang(get_request_language(request), key, **kwargs)


CHARACTER_ELEMENTS = {
    "heat": {"label_key": "character.element.heat", "icon": "Heaticon.webp"},
    "cryo": {"label_key": "character.element.cryo", "icon": "Cryoicon.webp"},
    "electric": {"label_key": "character.element.electric", "icon": "Electricicon.webp"},
    "nature": {"label_key": "character.element.nature", "icon": "Natureicon.webp"},
    "physical": {"label_key": "character.element.physical", "icon": "Physicalicon.webp"},
}

CHARACTER_WEAPONS = {
    "short": {"label_key": "character.weapon.short", "icon": "Short-Weapon.webp"},
    "great": {"label_key": "character.weapon.great", "icon": "Great-Weapon.webp"},
    "guns": {"label_key": "character.weapon.guns", "icon": "Guns.webp"},
    "polearms": {"label_key": "character.weapon.polearms", "icon": "Polearms.webp"},
    "orbiters": {"label_key": "character.weapon.orbiters", "icon": "Orbiters.webp"},
}

CHARACTER_ROLES = {
    "caster": {"label_key": "character.role.caster", "icon": "Caster.webp"},
    "defender": {"label_key": "character.role.defender", "icon": "Defender.webp"},
    "guard": {"label_key": "character.role.guard", "icon": "Guard.webp"},
    "striker": {"label_key": "character.role.striker", "icon": "Striker.webp"},
    "support": {"label_key": "character.role.support", "icon": "Support.webp"},
    "vanguard": {"label_key": "character.role.vanguard", "icon": "Vanguard.webp"},
}

RARITY_ICONS = {
    4: "4-Stars.webp",
    5: "5-Stars.webp",
    6: "6-Stars.webp",
}

CHARACTERS = [
    {"name": "Акэкури", "icon": "akekuri.png", "rarity": 4, "element": "heat", "weapon": "short", "role": "striker", "aliases": ["Akekuri"]},
    {"name": "Алеш", "icon": "alesh.png", "rarity": 5, "element": "cryo", "weapon": "short", "role": "vanguard", "aliases": ["Alesh"]},
    {"name": "Антал", "icon": "antal.png", "rarity": 4, "element": "electric", "weapon": "orbiters", "role": "guard", "aliases": ["Antal"]},
    {"name": "Арклайт", "icon": "arclight.png", "rarity": 5, "element": "electric", "weapon": "short", "role": "striker", "aliases": ["Arclight"]},
    {"name": "Арделия", "icon": "Ardelia.png", "rarity": 6, "element": "nature", "weapon": "orbiters", "role": "support", "aliases": ["Ardelia"]},
    {"name": "Авивенна", "icon": "avywenna.png", "rarity": 5, "element": "electric", "weapon": "polearms", "role": "vanguard", "aliases": ["Avywenna"]},
    {"name": "Кэтчер", "icon": "catcher.png", "rarity": 4, "element": "physical", "weapon": "great", "role": "striker", "aliases": ["Catcher"]},
    {"name": "Чэнь Цяньюй", "icon": "Chen-Qianyu.png", "rarity": 5, "element": "physical", "weapon": "short", "role": "support", "aliases": ["Chen Qianyu", "Chen-Qianyu"]},
    {"name": "Да Пан", "icon": "da-pan.png", "rarity": 5, "element": "physical", "weapon": "great", "role": "defender", "aliases": ["Da Pan", "Da-Pan"]},
    {"name": "Эмбер", "icon": "ember.png", "rarity": 6, "element": "heat", "weapon": "great", "role": "guard", "aliases": ["Ember"]},
    {"name": "Эндминистратор", "icon": "Endministrator.png", "rarity": 6, "element": "physical", "weapon": "short", "role": "guard", "aliases": ["Endministrator"]},
    {"name": "Эстелла", "icon": "estella.png", "rarity": 4, "element": "cryo", "weapon": "polearms", "role": "caster", "aliases": ["Estella"]},
    {"name": "Флюорит", "icon": "fluorite.png", "rarity": 4, "element": "nature", "weapon": "guns", "role": "caster", "aliases": ["Fluorite", "Фрюорит"]},
    {"name": "Гилберта", "icon": "gilberta.png", "rarity": 6, "element": "nature", "weapon": "orbiters", "role": "support", "aliases": ["Gilberta"]},
    {"name": "Лэватейн", "icon": "laevatain.png", "rarity": 6, "element": "heat", "weapon": "short", "role": "guard", "aliases": ["Laevatain"]},
    {"name": "Панихида", "icon": "last-rite.png", "rarity": 6, "element": "cryo", "weapon": "great", "role": "caster", "aliases": ["Last Rite", "Last-Rite"]},
    {"name": "Лифэн", "icon": "lifeng.png", "rarity": 6, "element": "physical", "weapon": "polearms", "role": "vanguard", "aliases": ["Lifeng"]},
    {"name": "Перлика", "icon": "perlica.png", "rarity": 5, "element": "electric", "weapon": "orbiters", "role": "support", "aliases": ["Perlica"]},
    {"name": "Пограничник", "icon": "pogranichnik.png", "rarity": 6, "element": "physical", "weapon": "short", "role": "defender", "aliases": ["Pogranichnik"]},
    {"name": "Светоснежка", "icon": "snowshine.png", "rarity": 5, "element": "cryo", "weapon": "great", "role": "support", "aliases": ["Snowshine"]},
    {"name": "Вулфгард", "icon": "wulfgard.png", "rarity": 5, "element": "heat", "weapon": "guns", "role": "striker", "aliases": ["Wulfgard"]},
    {"name": "Сайхи", "icon": "xaihi.png", "rarity": 5, "element": "cryo", "weapon": "orbiters", "role": "support", "aliases": ["Xaihi"]},
    {"name": "Ивонна", "icon": "yvonne.png", "rarity": 6, "element": "cryo", "weapon": "guns", "role": "caster", "aliases": ["Yvonne"]},
]


def _pity_counter_until_any(rarities, reset_values):
    """Count pulls since the latest target rarity in a reverse-sorted list."""
    counter = 0
    for rarity in rarities:
        if rarity in reset_values:
            return counter
        counter += 1
    return counter


def _pity_state_with_resets(rarities, reset_values, hard_limit):
    """Return current pity counter and pulls left to hard limit."""
    current = _pity_counter_until_any(rarities, reset_values)
    to_guarantee = max(hard_limit - current, 0)
    return current, to_guarantee


def _format_ts(gacha_ts):
    """Format epoch milliseconds as local datetime string."""
    if not gacha_ts:
        return "-"
    dt = datetime.fromtimestamp(int(gacha_ts) / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_obtained_date(gacha_ts, language):
    """Format obtain date for character card status."""
    if not gacha_ts:
        return _tr_lang(language, "characters.date_unknown")
    dt = datetime.fromtimestamp(int(gacha_ts) / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%d.%m.%Y")


def _normalize_character_key(value):
    """Normalize character names/aliases for robust matching."""
    cleaned = re.sub(r"[\W_]+", "", str(value or "").strip().lower(), flags=re.UNICODE)
    return cleaned


def _build_character_obtained_map(session):
    """Build first-seen timestamp map for characters from one import session."""
    obtained_map = {}
    if not session:
        return obtained_map

    pulls = session.pulls.order_by("gacha_ts", "seq_id")
    for pull in pulls:
        key = _normalize_character_key(pull.char_name)
        if key and key not in obtained_map:
            obtained_map[key] = pull.gacha_ts
    return obtained_map


def _character_lookup_keys(character):
    """Build all lookup keys for a character definition."""
    keys = {_normalize_character_key(character.get("name"))}
    for alias in character.get("aliases", []):
        keys.add(_normalize_character_key(alias))
    icon_stem = str(character.get("icon", "")).rsplit(".", 1)[0]
    keys.add(_normalize_character_key(icon_stem))
    return {key for key in keys if key}


def _get_first_hero_ts(session):
    """Get earliest available pull timestamp in session."""
    if not session:
        return None

    first_with_ts = (
        session.pulls.exclude(gacha_ts__isnull=True)
        .order_by("gacha_ts", "seq_id")
        .values_list("gacha_ts", flat=True)
        .first()
    )
    if first_with_ts:
        return first_with_ts

    return (
        session.pulls.order_by("seq_id")
        .values_list("gacha_ts", flat=True)
        .first()
    )


def _build_history_rows(pulls, language):
    """Build dashboard table rows with pity index per pull."""
    rows = []
    chronological_pulls = list(reversed(pulls))
    pity6 = 0
    pity5 = 0
    pity4 = 0
    for pull in chronological_pulls:
        pity6 += 1
        pity5 += 1
        pity4 += 1
        guarantee = pity4
        if pull.rarity == 6:
            guarantee = pity6
            pity6 = 0
            pity5 = 0
            pity4 = 0
        elif pull.rarity == 5:
            guarantee = pity5
            pity5 = 0
            pity4 = 0
        elif pull.rarity == 4:
            guarantee = pity4
            pity4 = 0

        rows.append(
            {
                "name": pull.char_name or pull.char_id or _tr_lang(language, "characters.unknown_name"),
                "date": _format_ts(pull.gacha_ts),
                "rarity": pull.rarity,
                "guarantee": guarantee,
            }
        )
    return list(reversed(rows))


def dashboard(request):
    """Render pity dashboard for latest successful import session."""
    language = get_request_language(request)
    latest_session = ImportSession.objects.filter(status="done").order_by("-created_at").first()
    cards = []

    for spec in DASHBOARD_POOLS:
        rarities = []
        pulls = []
        if latest_session:
            queryset = latest_session.pulls.filter(source_pool_type=spec["source_pool_type"]).order_by("-seq_id")
            if not queryset.exists():
                queryset = latest_session.pulls.filter(pool_id__icontains=spec["pool_id_fallback"]).order_by("-seq_id")
            rarities = list(queryset.values_list("rarity", flat=True))
            pulls = list(queryset[:120])

        six_star_pity, six_star_left = _pity_state_with_resets(
            rarities=rarities,
            reset_values={6},
            hard_limit=spec["six_star_limit"],
        )
        five_star_pity, five_star_left = _pity_state_with_resets(
            rarities=rarities,
            reset_values={5, 6},
            hard_limit=spec["five_star_limit"],
        )

        cards.append(
            {
                "title": _tr_lang(language, spec["title_key"]),
                "total": len(rarities),
                "six_star_pity": six_star_pity,
                "six_star_left": six_star_left,
                "six_star_limit": spec["six_star_limit"],
                "five_star_pity": five_star_pity,
                "five_star_left": five_star_left,
                "five_star_limit": spec["five_star_limit"],
                "history_rows": _build_history_rows(pulls, language),
            }
        )

    return render(
        request,
        "core/dashboard.html",
        {
            "cards": cards,
            "latest_session": latest_session,
        },
    )


def characters_page(request):
    """Render character collection page with obtained/missing status."""
    language = get_request_language(request)
    latest_session = ImportSession.objects.filter(status="done").order_by("-created_at").first()
    obtained_map = _build_character_obtained_map(latest_session)
    first_hero_ts = _get_first_hero_ts(latest_session)
    characters = []
    for character in CHARACTERS:
        element_meta = CHARACTER_ELEMENTS.get(character["element"], {})
        weapon_meta = CHARACTER_WEAPONS.get(character["weapon"], {})
        role_meta = CHARACTER_ROLES.get(character["role"], {})
        rarity = int(character.get("rarity") or 0)
        lookup_keys = _character_lookup_keys(character)
        matched_values = [obtained_map[key] for key in lookup_keys if key in obtained_map]
        is_obtained = bool(matched_values)
        matched_ts = min((value for value in matched_values if value), default=matched_values[0] if matched_values else None)

        # Endministrator is granted by default: show obtained status with first hero date.
        if character.get("icon") == "Endministrator.png":
            is_obtained = True
            matched_ts = first_hero_ts

        characters.append(
            {
                **character,
                "rarity_icon": RARITY_ICONS.get(rarity, ""),
                "element_label": _tr_lang(language, element_meta.get("label_key", "")),
                "element_icon": element_meta.get("icon", ""),
                "weapon_label": _tr_lang(language, weapon_meta.get("label_key", "")),
                "weapon_icon": weapon_meta.get("icon", ""),
                "role_label": _tr_lang(language, role_meta.get("label_key", "")),
                "role_icon": role_meta.get("icon", ""),
                "is_obtained": is_obtained,
                "obtained_date": _format_obtained_date(matched_ts, language) if is_obtained else "",
            }
        )

    return render(
        request,
        "core/characters.html",
        {
            "characters": characters,
        },
    )


def _to_int(value, default=0):
    """Convert value to int with safe fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value):
    """Convert mixed value types to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _history_export_payload():
    """Build canonical export payload used for file/cloud sync."""
    sessions = list(ImportSession.objects.order_by("-created_at"))
    return {
        "schema_version": 1,
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "session_count": len(sessions),
        "pull_count": Pull.objects.count(),
        "sessions": [_serialize_session(session) for session in sessions],
    }


def _is_sync_provider(provider):
    """Check whether provider supports OAuth folder sync."""
    normalized = (provider or "").strip().lower()
    return any(value == normalized for value, _label in SYNC_PROVIDER_CHOICES)


def _provider_label(provider):
    """Resolve provider display label by code."""
    normalized = (provider or "").strip().lower()
    for value, label in SYNC_PROVIDER_CHOICES:
        if value == normalized:
            return label
    for value, label in CLOUD_PROVIDER_CHOICES:
        if value == normalized:
            return label
    return normalized or "Cloud"


def _cloud_provider_credentials(provider):
    """Load OAuth client credentials for provider from settings."""
    normalized = (provider or "").strip().lower()
    if normalized == "google_drive":
        return (
            str(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip(),
            str(getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip(),
        )
    if normalized == "yandex_disk":
        return (
            str(getattr(settings, "YANDEX_OAUTH_CLIENT_ID", "") or "").strip(),
            str(getattr(settings, "YANDEX_OAUTH_CLIENT_SECRET", "") or "").strip(),
        )
    return "", ""


def _is_cloud_oauth_configured(provider):
    """Return True when provider has both client id and secret configured."""
    client_id, client_secret = _cloud_provider_credentials(provider)
    return bool(client_id and client_secret)


def _get_cloud_auth_map(request):
    """Read cloud auth mapping from session in normalized format."""
    data = request.session.get(CLOUD_AUTH_SESSION_KEY)
    if isinstance(data, dict):
        return data
    return {}


def _save_cloud_auth_map(request, auth_map):
    """Persist cloud auth mapping to session."""
    request.session[CLOUD_AUTH_SESSION_KEY] = auth_map
    request.session.modified = True


def _set_settings_flash(request, message, message_type="info", message_details=""):
    """Store one-time status message for settings page."""
    request.session[SETTINGS_FLASH_SESSION_KEY] = {
        "message": message,
        "message_type": message_type,
        "message_details": message_details,
    }
    request.session.modified = True


def _pop_settings_flash(request):
    """Pop one-time settings flash payload from session."""
    payload = request.session.pop(SETTINGS_FLASH_SESSION_KEY, None)
    if isinstance(payload, dict):
        return {
            "message": payload.get("message", ""),
            "message_type": payload.get("message_type", ""),
            "message_details": payload.get("message_details", ""),
        }
    return {"message": "", "message_type": "", "message_details": ""}


def _store_provider_tokens(request, provider, token_payload):
    """Persist provider OAuth token payload in session auth map."""
    normalized = (provider or "").strip().lower()
    auth_map = _get_cloud_auth_map(request)
    provider_auth = auth_map.get(normalized) if isinstance(auth_map.get(normalized), dict) else {}

    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise CloudIntegrationError(_tr(request, "view.cloud.no_token"))

    provider_auth["access_token"] = access_token
    provider_auth["token_type"] = str(token_payload.get("token_type") or "").strip()

    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if refresh_token:
        provider_auth["refresh_token"] = refresh_token

    try:
        expires_in = int(token_payload.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0

    if expires_in > 0:
        provider_auth["expires_at"] = int(time.time()) + max(expires_in - 30, 30)
    else:
        provider_auth.pop("expires_at", None)

    auth_map[normalized] = provider_auth
    _save_cloud_auth_map(request, auth_map)


def _build_cloud_cards_context(request):
    """Build UI model for cloud cards shown in settings page."""
    auth_map = _get_cloud_auth_map(request)
    now_ts = int(time.time())
    cards = []
    for provider, label in SYNC_PROVIDER_CHOICES:
        auth = auth_map.get(provider) if isinstance(auth_map.get(provider), dict) else {}
        access_token = str(auth.get("access_token") or "").strip()
        expires_at_raw = auth.get("expires_at")
        try:
            expires_at = int(expires_at_raw or 0)
        except (TypeError, ValueError):
            expires_at = 0

        cards.append(
            {
                "provider": provider,
                "label": label,
                "configured": _is_cloud_oauth_configured(provider),
                "connected": bool(access_token),
                "token_expiring": bool(expires_at and expires_at <= now_ts + 60),
                "setup_hint": (
                    "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET"
                    if provider == "google_drive"
                    else "YANDEX_OAUTH_CLIENT_ID and YANDEX_OAUTH_CLIENT_SECRET"
                ),
            }
        )
    return cards


def _ensure_cloud_access_token(request, provider):
    """Return valid access token, refreshing it if needed."""
    normalized = (provider or "").strip().lower()
    if not _is_sync_provider(normalized):
        raise CloudIntegrationError(_tr(request, "view.cloud.unknown_provider"))

    if not _is_cloud_oauth_configured(normalized):
        label = _provider_label(normalized)
        raise CloudIntegrationError(_tr(request, "view.cloud.server_not_configured", provider=label))

    auth_map = _get_cloud_auth_map(request)
    auth = auth_map.get(normalized) if isinstance(auth_map.get(normalized), dict) else {}
    access_token = str(auth.get("access_token") or "").strip()
    refresh_token = str(auth.get("refresh_token") or "").strip()

    if not access_token:
        raise CloudIntegrationError(_tr(request, "view.cloud.connect_first", provider=_provider_label(normalized)))

    expires_at_raw = auth.get("expires_at")
    try:
        expires_at = int(expires_at_raw or 0)
    except (TypeError, ValueError):
        expires_at = 0

    if expires_at and expires_at <= int(time.time()) + 30:
        client_id, client_secret = _cloud_provider_credentials(normalized)
        refreshed = refresh_oauth_token(
            provider=normalized,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        _store_provider_tokens(request, normalized, refreshed)
        return str(refreshed.get("access_token") or "").strip()

    return access_token


def _settings_context(request, message="", message_type="", message_details=""):
    """Build settings page context with cloud connection status."""
    donate_url = getattr(settings, "DONATE_URL", DEFAULT_DONATE_URL)
    repository_url = getattr(settings, "OFFICIAL_REPOSITORY_URL", OFFICIAL_REPOSITORY_URL)
    return {
        "status_message": message,
        "status_message_type": message_type,
        "status_message_details": message_details,
        "donate_url": donate_url,
        "repository_url": repository_url,
        "cloud_cards": _build_cloud_cards_context(request),
        "cloud_folder_name": SYNC_FOLDER_NAME,
        "cloud_file_name": SYNC_FILE_NAME,
    }


def _render_settings(request, message="", message_type="", message_details=""):
    """Render settings page with optional status alert."""
    return render(
        request,
        "core/settings.html",
        _settings_context(
            request=request,
            message=message,
            message_type=message_type,
            message_details=message_details,
        ),
    )


def settings_page(request):
    """Render settings page with optional flash message."""
    flash = _pop_settings_flash(request)
    return _render_settings(
        request,
        message=flash.get("message", ""),
        message_type=flash.get("message_type", ""),
        message_details=flash.get("message_details", ""),
    )


def set_site_language(request):
    """Update interface language and redirect back to previous page."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    lang = normalize_language_code(request.POST.get("lang"))
    next_url = (request.POST.get("next") or "").strip() or reverse("dashboard")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = reverse("dashboard")

    request.session[SITE_LANGUAGE_SESSION_KEY] = lang
    request.site_language = lang
    response = redirect(next_url)
    response.set_cookie(SITE_LANGUAGE_COOKIE_KEY, lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


def privacy_policy(request):
    """Render privacy policy page."""
    return render(request, "core/privacy_policy.html")


def cookies_policy(request):
    """Render cookie policy page."""
    return render(request, "core/cookies_policy.html")


def _serialize_session(session):
    """Serialize import session with pulls to export JSON."""
    pulls = list(
        session.pulls.order_by("-seq_id").values(
            "pool_id",
            "pool_name",
            "char_id",
            "char_name",
            "rarity",
            "is_free",
            "is_new",
            "gacha_ts",
            "seq_id",
            "source_pool_type",
        )
    )
    return {
        "source_session_id": session.id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "server_id": session.server_id,
        "lang": session.lang,
        "status": session.status,
        "error": session.error,
        "pulls": pulls,
    }


def export_history(request):
    """Download full local history as JSON attachment."""
    payload = _history_export_payload()
    response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    response["Content-Disposition"] = f'attachment; filename="endfieldpass-history-{timestamp}.json"'
    return response


def _build_session_payloads(payload):
    """Support both new schema (sessions) and legacy (items)."""
    sessions = payload.get("sessions")
    if isinstance(sessions, list):
        return sessions

    items = payload.get("items")
    if isinstance(items, list):
        return [
            {
                "server_id": payload.get("server_id") or "3",
                "lang": payload.get("lang") or "ru-ru",
                "status": "done",
                "pulls": items,
            }
        ]
    return None


def _apply_session_created_at(session, created_at_raw):
    """Apply imported created_at timestamp if it is valid."""
    if not created_at_raw:
        return

    parsed = parse_datetime(str(created_at_raw))
    if not parsed:
        return
    if django_timezone.is_naive(parsed):
        parsed = django_timezone.make_aware(parsed, django_timezone.get_current_timezone())
    ImportSession.objects.filter(pk=session.pk).update(created_at=parsed)


def _import_history_payload(payload):
    """Import history payload into DB and return inserted counters."""
    if not isinstance(payload, dict):
        raise ValueError("view.error.bad_payload")

    sessions_payload = _build_session_payloads(payload)
    if sessions_payload is None:
        raise ValueError("view.error.bad_format")

    imported_sessions = 0
    imported_pulls = 0
    with transaction.atomic():
        for session_payload in sessions_payload:
            if not isinstance(session_payload, dict):
                continue

            session = ImportSession.objects.create(
                page_url=str(session_payload.get("page_url") or ""),
                token=str(session_payload.get("token") or ""),
                server_id=str(session_payload.get("server_id") or "3"),
                lang=str(session_payload.get("lang") or "ru-ru"),
                status=str(session_payload.get("status") or "done"),
                error=str(session_payload.get("error") or ""),
            )
            imported_sessions += 1
            _apply_session_created_at(session, session_payload.get("created_at"))

            pulls_payload = session_payload.get("pulls")
            if not isinstance(pulls_payload, list):
                pulls_payload = session_payload.get("items")
            if not isinstance(pulls_payload, list):
                pulls_payload = []

            pulls_to_create = []
            for item in pulls_payload:
                if not isinstance(item, dict):
                    continue
                pulls_to_create.append(
                    Pull(
                        session=session,
                        pool_id=str(item.get("pool_id") or item.get("poolId") or "UNKNOWN"),
                        pool_name=str(item.get("pool_name") or item.get("poolName") or ""),
                        char_id=str(item.get("char_id") or item.get("charId") or ""),
                        char_name=str(item.get("char_name") or item.get("charName") or ""),
                        rarity=_to_int(item.get("rarity"), default=0),
                        is_free=_to_bool(item.get("is_free") if "is_free" in item else item.get("isFree")),
                        is_new=_to_bool(item.get("is_new") if "is_new" in item else item.get("isNew")),
                        gacha_ts=_to_int(item.get("gacha_ts") if "gacha_ts" in item else item.get("gachaTs"), default=0) or None,
                        seq_id=_to_int(item.get("seq_id") if "seq_id" in item else item.get("seqId"), default=0),
                        source_pool_type=str(item.get("source_pool_type") or item.get("_source_pool_type") or ""),
                        raw=item,
                    )
                )

            if pulls_to_create:
                Pull.objects.bulk_create(pulls_to_create, batch_size=1000)
                imported_pulls += len(pulls_to_create)

    return imported_sessions, imported_pulls


def import_history(request):
    """Import local history from uploaded JSON file."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    uploaded_file = request.FILES.get("history_file")
    if not uploaded_file:
        return _render_settings(request, _tr(request, "view.settings.select_json"), "error")

    try:
        raw_payload = uploaded_file.read().decode("utf-8")
        payload = json.loads(raw_payload)
        imported_sessions, imported_pulls = _import_history_payload(payload)
    except UnicodeDecodeError:
        return _render_settings(request, _tr(request, "view.settings.utf8"), "error")
    except json.JSONDecodeError:
        return _render_settings(request, _tr(request, "view.settings.read_json"), "error")
    except ValueError as exc:
        return _render_settings(request, _tr(request, "view.settings.import_failed"), "error", _tr(request, str(exc)))
    except Exception as exc:
        return _render_settings(request, _tr(request, "view.settings.import_error"), "error", str(exc))

    details = _tr(request, "view.settings.counts", sessions=imported_sessions, pulls=imported_pulls)
    return _render_settings(request, _tr(request, "view.settings.import_done"), "success", details)


def cloud_connect(request, provider):
    """Start provider OAuth connection flow."""
    normalized = (provider or "").strip().lower()
    if not _is_sync_provider(normalized):
        return HttpResponseBadRequest("unknown provider")

    if not _is_cloud_oauth_configured(normalized):
        label = _provider_label(normalized)
        return _render_settings(
            request,
            _tr(request, "view.cloud.provider_not_configured", provider=label),
            "error",
            _tr(request, "view.cloud.provider_not_configured_details"),
        )

    client_id, _client_secret = _cloud_provider_credentials(normalized)
    state = secrets.token_urlsafe(24)
    request.session[CLOUD_OAUTH_STATE_SESSION_KEY] = {"provider": normalized, "state": state}
    request.session.modified = True

    redirect_uri = request.build_absolute_uri(reverse("cloud_callback", args=[normalized]))
    try:
        auth_url = build_oauth_authorization_url(
            provider=normalized,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
        )
    except CloudIntegrationError as exc:
        return _render_settings(request, _tr(request, "view.cloud.oauth_start_failed"), "error", str(exc))

    return redirect(auth_url)


def cloud_callback(request, provider):
    """Handle provider OAuth callback and store tokens."""
    normalized = (provider or "").strip().lower()
    if not _is_sync_provider(normalized):
        return HttpResponseBadRequest("unknown provider")

    oauth_state = request.session.pop(CLOUD_OAUTH_STATE_SESSION_KEY, None)
    expected_provider = oauth_state.get("provider") if isinstance(oauth_state, dict) else ""
    expected_state = oauth_state.get("state") if isinstance(oauth_state, dict) else ""
    received_state = (request.GET.get("state") or "").strip()
    code = (request.GET.get("code") or "").strip()
    provider_error = (request.GET.get("error_description") or request.GET.get("error") or "").strip()

    if provider_error:
        _set_settings_flash(
            request,
            _tr(request, "view.cloud.oauth_denied", provider=_provider_label(normalized)),
            "error",
            provider_error,
        )
        return redirect("settings_page")

    if not expected_provider or expected_provider != normalized or not expected_state or expected_state != received_state:
        _set_settings_flash(
            request,
            _tr(request, "view.cloud.oauth_state_failed"),
            "error",
            _tr(request, "view.cloud.oauth_state_details"),
        )
        return redirect("settings_page")

    if not code:
        _set_settings_flash(
            request,
            _tr(request, "view.cloud.oauth_code_missing"),
            "error",
            _tr(request, "view.cloud.oauth_code_missing_details"),
        )
        return redirect("settings_page")

    client_id, client_secret = _cloud_provider_credentials(normalized)
    redirect_uri = request.build_absolute_uri(reverse("cloud_callback", args=[normalized]))
    try:
        token_payload = exchange_oauth_code(
            provider=normalized,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
        _store_provider_tokens(request, normalized, token_payload)
    except CloudIntegrationError as exc:
        _set_settings_flash(
            request,
            _tr(request, "view.cloud.oauth_connect_failed", provider=_provider_label(normalized)),
            "error",
            str(exc),
        )
        return redirect("settings_page")

    _set_settings_flash(
        request,
        _tr(request, "view.cloud.oauth_connected", provider=_provider_label(normalized)),
        "success",
        _tr(request, "view.cloud.oauth_connected_details"),
    )
    return redirect("settings_page")


def cloud_disconnect(request, provider):
    """Disconnect cloud provider for current user session."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    normalized = (provider or "").strip().lower()
    if not _is_sync_provider(normalized):
        return HttpResponseBadRequest("unknown provider")

    auth_map = _get_cloud_auth_map(request)
    auth_map.pop(normalized, None)
    _save_cloud_auth_map(request, auth_map)
    _set_settings_flash(request, _tr(request, "view.cloud.oauth_disconnected", provider=_provider_label(normalized)), "success")
    return redirect("settings_page")


def cloud_export(request):
    """Sync local history payload to connected cloud provider."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    provider = (request.POST.get("provider") or "").strip().lower()
    if not _is_sync_provider(provider):
        return _render_settings(request, _tr(request, "view.cloud.choose_sync_provider"), "error")

    try:
        access_token = _ensure_cloud_access_token(request, provider)
        payload = _history_export_payload()
        result = export_payload_to_cloud(
            provider=provider,
            token=access_token,
            payload=payload,
        )
    except CloudIntegrationError as exc:
        return _render_settings(request, _tr(request, "view.cloud.sync_failed"), "error", str(exc))
    except Exception as exc:
        return _render_settings(request, _tr(request, "view.cloud.sync_error"), "error", str(exc))

    if provider == "google_drive":
        details = _tr(
            request,
            "view.cloud.sync_done_google",
            folder=result.get("folder_name") or SYNC_FOLDER_NAME,
            file=result.get("file_name") or SYNC_FILE_NAME,
        )
    else:
        details = _tr(request, "view.cloud.sync_done_yandex", path=result.get("path") or f"app:/{SYNC_FOLDER_NAME}/{SYNC_FILE_NAME}")
    return _render_settings(request, _tr(request, "view.cloud.sync_done"), "success", details)


def cloud_import(request):
    """Import history payload from connected cloud provider or URL."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    provider = (request.POST.get("provider") or "").strip().lower()
    remote_ref = (request.POST.get("remote_ref") or "").strip()
    if not provider:
        return _render_settings(request, _tr(request, "view.cloud.choose_import_source"), "error")

    try:
        if provider == "url":
            if not remote_ref:
                return _render_settings(request, _tr(request, "view.cloud.url_required"), "error")
            payload = import_payload_from_cloud(provider="url", token="", remote_ref=remote_ref)
        else:
            access_token = _ensure_cloud_access_token(request, provider)
            payload = import_payload_from_cloud(provider=provider, token=access_token, remote_ref="")

        imported_sessions, imported_pulls = _import_history_payload(payload)
    except CloudIntegrationError as exc:
        return _render_settings(request, _tr(request, "view.cloud.import_failed"), "error", str(exc))
    except ValueError as exc:
        return _render_settings(request, _tr(request, "view.cloud.import_bad_format"), "error", _tr(request, str(exc)))
    except Exception as exc:
        return _render_settings(request, _tr(request, "view.cloud.import_error"), "error", str(exc))

    details = _tr(request, "view.settings.counts", sessions=imported_sessions, pulls=imported_pulls)
    return _render_settings(request, _tr(request, "view.cloud.import_done"), "success", details)


def _default_form_data():
    """Return default import form values."""
    return {
        "page_url": "",
        "token": "",
        "server_id": "3",
        "lang": "ru-ru",
    }


def _set_progress(session_id: int, *, status=None, progress=None, message=None, error=None):
    """Update in-memory progress state for async import session."""
    with IMPORT_PROGRESS_LOCK:
        state = IMPORT_PROGRESS.get(session_id, {})
        if status is not None:
            state["status"] = status
        if progress is not None:
            state["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            state["message"] = message
        if error is not None:
            state["error"] = error
        IMPORT_PROGRESS[session_id] = state


def _get_progress(session_id: int):
    """Read in-memory progress state for async import session."""
    with IMPORT_PROGRESS_LOCK:
        state = IMPORT_PROGRESS.get(session_id, {})
        return {
            "status": state.get("status"),
            "progress": state.get("progress"),
            "message": state.get("message"),
            "error": state.get("error", ""),
        }


def _extract_credentials_from_page_url(page_url: str):
    """Parse token/server/lang query params from game history URL."""
    if not page_url:
        return "", "", "ru-ru"

    parsed = urlparse(page_url)
    query = parse_qs(parsed.query)

    token = (query.get("u8_token") or query.get("token") or [""])[0]
    server_id = (query.get("server") or query.get("server_id") or [""])[0]
    lang = (query.get("lang") or ["ru-ru"])[0]
    return token, server_id, lang


def _run_import_session(session_id: int, ui_language: str):
    """Background job: fetch pulls, store in DB, update progress state."""
    session = ImportSession.objects.get(pk=session_id)
    _set_progress(session.id, status="running", progress=3, message=_tr_lang(ui_language, "import.loading.prepare"))

    def on_pool_progress(index, total, pool_type, stage, **kwargs):
        pool_label_key = POOL_LABELS.get(pool_type)
        pool_label = _tr_lang(ui_language, pool_label_key) if pool_label_key else pool_type
        if stage == "start":
            progress = 5 + int(((index - 1) / total) * 70)
            message = f"{_tr_lang(ui_language, 'import.loading.hint1')} {pool_label}."
        else:
            progress = 5 + int((index / total) * 70)
            message = _tr_lang(ui_language, "import.loading.hint2")
        _set_progress(session.id, status="running", progress=progress, message=message)

    try:
        items = fetch_all_records(
            token=session.token,
            server_id=session.server_id,
            lang=session.lang,
            on_pool_progress=on_pool_progress,
        )

        _set_progress(
            session.id,
            status="running",
            progress=82,
            message=_tr_lang(ui_language, "import.loading.hint3"),
        )

        pulls = []
        for item in items:
            pulls.append(
                Pull(
                    session=session,
                    pool_id=str(item.get("poolId") or "UNKNOWN"),
                    pool_name=str(item.get("poolName") or ""),
                    char_id=str(item.get("charId") or ""),
                    char_name=str(item.get("charName") or ""),
                    rarity=int(item.get("rarity") or 0),
                    is_free=bool(item.get("isFree")),
                    is_new=bool(item.get("isNew")),
                    gacha_ts=int(item.get("gachaTs")) if item.get("gachaTs") else None,
                    seq_id=int(item.get("seqId") or 0),
                    source_pool_type=str(item.get("_source_pool_type") or ""),
                    raw=item,
                )
            )

        if pulls:
            batch_size = 1000
            total = len(pulls)
            saved = 0
            for start in range(0, total, batch_size):
                batch = pulls[start : start + batch_size]
                Pull.objects.bulk_create(batch, batch_size=batch_size)
                saved += len(batch)
                progress = 82 + int((saved / total) * 17)
                _set_progress(
                    session.id,
                    status="running",
                    progress=min(progress, 99),
                    message=f"{_tr_lang(ui_language, 'import.error.processing')} {saved}/{total}.",
                )

        session.status = "done"
        session.save(update_fields=["status"])
        _set_progress(session.id, status="done", progress=100, message=_tr_lang(ui_language, "view.settings.import_done"))
    except Exception as exc:
        session.status = "error"
        session.error = str(exc)
        session.save(update_fields=["status", "error"])
        _set_progress(
            session.id,
            status="error",
            progress=100,
            message=_tr_lang(ui_language, "view.settings.import_error"),
            error=str(exc),
        )


def import_page(request):
    """Render import page with empty/default state."""
    return render(
        request,
        "endfield_tracker/import_view.html",
        {
            "error": "",
            "form": _default_form_data(),
            "session": None,
            "pulls": [],
        },
    )


@csrf_exempt
def create_session(request):
    """Create async import session and start background worker thread."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("bad json")

    token = (payload.get("token") or "").strip()
    server_id = str(payload.get("server_id") or "").strip()
    page_url = (payload.get("page_url") or "").strip()
    lang = (payload.get("lang") or "ru-ru").strip()

    if page_url and (not token or not server_id):
        parsed_token, parsed_server, parsed_lang = _extract_credentials_from_page_url(page_url)
        token = token or parsed_token
        server_id = server_id or parsed_server
        if not payload.get("lang"):
            lang = parsed_lang

    if not token or not server_id:
        return HttpResponseBadRequest("missing token/server_id")

    session = ImportSession.objects.create(
        token=token,
        server_id=server_id,
        lang=lang,
        page_url=page_url,
        status="running",
    )
    ui_language = get_request_language(request)
    _set_progress(session.id, status="running", progress=1, message=_tr_lang(ui_language, "import.loading.prepare"))

    thread = threading.Thread(target=_run_import_session, args=(session.id, ui_language), daemon=True)
    thread.start()

    return JsonResponse({"session_id": session.id, "status": session.status})


def import_status(request, session_id: int):
    """Return current import progress and status as JSON."""
    session = get_object_or_404(ImportSession, pk=session_id)
    progress_state = _get_progress(session_id)

    progress = progress_state.get("progress")
    if progress is None:
        progress = 100 if session.status in {"done", "error"} else 0

    if session.status == "done":
        progress = 100
    message = progress_state.get("message") or _tr(request, "import.error.processing")

    return JsonResponse(
        {
            "session_id": session.id,
            "status": session.status,
            "progress": progress,
            "message": message,
            "error": session.error,
            "pull_count": session.pulls.count(),
        }
    )


def import_view(request, session_id: int):
    """Render import page with a specific session result preview."""
    session = get_object_or_404(ImportSession, pk=session_id)
    pulls = session.pulls.order_by("-seq_id")[:500]
    return render(
        request,
        "endfield_tracker/import_view.html",
        {
            "session": session,
            "pulls": pulls,
            "error": "",
            "form": {
                "page_url": session.page_url,
                "token": session.token,
                "server_id": session.server_id,
                "lang": session.lang,
            },
        },
    )


def pulls_json(request, session_id: int):
    """Return pulls JSON for a single import session."""
    session = get_object_or_404(ImportSession, pk=session_id)
    queryset = session.pulls.order_by("-seq_id").values(
        "pool_id",
        "pool_name",
        "char_id",
        "char_name",
        "rarity",
        "is_free",
        "is_new",
        "gacha_ts",
        "seq_id",
        "source_pool_type",
    )
    return JsonResponse(
        {
            "session_id": session.id,
            "count": queryset.count(),
            "items": list(queryset[:5000]),
        }
    )


def pulls_api(request):
    """Return pulls JSON with optional session/pool filters."""
    session_id = (request.GET.get("session_id") or "").strip()
    pool_id = (request.GET.get("pool_id") or "").strip()
    limit_raw = (request.GET.get("limit") or "5000").strip()

    try:
        limit = int(limit_raw)
    except ValueError:
        limit = 5000
    limit = max(1, min(limit, 5000))

    if session_id:
        session = get_object_or_404(ImportSession, pk=session_id)
    else:
        session = ImportSession.objects.order_by("-created_at").first()
        if not session:
            return JsonResponse({"session_id": None, "count": 0, "items": []})

    queryset = session.pulls.order_by("-seq_id")
    if pool_id:
        queryset = queryset.filter(pool_id=pool_id)

    values = queryset.values(
        "pool_id",
        "pool_name",
        "char_id",
        "char_name",
        "rarity",
        "is_free",
        "is_new",
        "gacha_ts",
        "seq_id",
        "source_pool_type",
    )
    return JsonResponse(
        {
            "session_id": session.id,
            "pool_id": pool_id or None,
            "count": values.count(),
            "items": list(values[:limit]),
        }
    )
