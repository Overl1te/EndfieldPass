from .localization import get_language_options, get_request_language


def localization(request):
    """Expose current language and switcher options to templates."""
    return {
        "current_lang": get_request_language(request),
        "language_options": get_language_options(),
    }
