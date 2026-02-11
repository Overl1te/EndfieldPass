from django.conf import settings

from .config_store import get_app_address
from .localization import get_language_options, get_request_language
from .turnstile import get_turnstile_site_key, is_turnstile_enabled


def localization(request):
    """Expose current language and switcher options to templates."""
    repository_default = getattr(settings, "OFFICIAL_REPOSITORY_URL", "https://github.com/Overl1te/EndfieldPass")
    donate_default = getattr(settings, "DONATE_URL", "https://github.com/sponsors/Overl1te")
    repository_from_env = str(repository_default or "").strip()
    donate_from_env = str(donate_default or "").strip()
    return {
        "current_lang": get_request_language(request),
        "language_options": get_language_options(),
        "repository_url": repository_from_env or get_app_address("repository_url", repository_default),
        "donate_url": donate_from_env or get_app_address("donate_url", donate_default),
        "turnstile_enabled": is_turnstile_enabled(),
        "turnstile_site_key": get_turnstile_site_key(),
    }
