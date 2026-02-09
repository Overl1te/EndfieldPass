from .localization import get_request_language


class SiteLanguageMiddleware:
    """Attach resolved interface language to request object."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.site_language = get_request_language(request)
        return self.get_response(request)
