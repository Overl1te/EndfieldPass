from urllib.parse import urlencode

from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import get_script_prefix, reverse, set_script_prefix
from django.utils.http import url_has_allowed_host_and_scheme

from .config_store import get_app_json
from .localization import (
    SUPPORTED_LANGUAGES,
    get_request_language,
    language_from_path_segment,
    normalize_language_code,
)
from .maintenance import (
    MAINTENANCE_CONFIG_KEY,
    MAINTENANCE_BYPASS_SESSION_KEY,
    build_hard_maintenance_html,
    disable_maintenance_mode_in_db,
    has_admin_bypass_session,
    is_maintenance_expired,
    normalize_maintenance_payload,
)


class SiteLanguageMiddleware:
    """Resolve language from URL prefix and enforce /<lang>/... paths."""

    EXCLUDED_PREFIXES = ("/admin/", "/static/", "/favicon.ico", "/api/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = str(getattr(request, "path_info", "") or getattr(request, "path", "") or "/")
        if self._is_excluded(path):
            request.site_language = get_request_language(request)
            return self.get_response(request)

        matched_lang, stripped_path = self._extract_language_prefix(path)
        if not matched_lang:
            language = get_request_language(request)
            redirect_path = self._with_language_prefix(path, language)
            query = str(request.META.get("QUERY_STRING") or "").strip()
            if query:
                redirect_path = f"{redirect_path}?{query}"
            return redirect(redirect_path)

        language = normalize_language_code(matched_lang)
        request.site_language = language
        request.path_info = stripped_path
        request.path = stripped_path
        request.META["PATH_INFO"] = stripped_path

        previous_prefix = get_script_prefix()
        set_script_prefix(f"/{language}/")
        try:
            return self.get_response(request)
        finally:
            set_script_prefix(previous_prefix)

    def _is_excluded(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.EXCLUDED_PREFIXES)

    def _extract_language_prefix(self, path: str):
        """Return (lang, stripped_path) if URL starts with supported language."""
        raw = str(path or "/")
        normalized = raw if raw.startswith("/") else f"/{raw}"
        parts = [part for part in normalized.split("/") if part]
        if not parts:
            return "", normalized

        first = language_from_path_segment(parts[0])
        if first not in SUPPORTED_LANGUAGES:
            return "", normalized

        remainder_parts = parts[1:]
        if not remainder_parts:
            return first, "/"
        stripped = "/" + "/".join(remainder_parts)
        if raw.endswith("/") and not stripped.endswith("/"):
            stripped += "/"
        return first, stripped

    def _with_language_prefix(self, path: str, language: str):
        normalized_language = normalize_language_code(language)
        raw = str(path or "/")
        normalized_path = raw if raw.startswith("/") else f"/{raw}"
        if normalized_path == "/":
            return f"/{normalized_language}/"
        return f"/{normalized_language}{normalized_path}"


class SecurityHeadersMiddleware:
    """Attach conservative security headers for XSS/clickjacking hardening."""

    CONTENT_SECURITY_POLICY = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "frame-src 'self' https://challenges.cloudflare.com; "
        "form-action 'self'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https:; "
        "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
        "style-src 'self' 'unsafe-inline'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("X-Frame-Options", "DENY")
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.setdefault("Content-Security-Policy", self.CONTENT_SECURITY_POLICY)
        return response


class MaintenanceModeMiddleware:
    """Redirect requests to maintenance page when DB flag is enabled."""

    EXCLUDED_PREFIXES = ("/static/",)
    EXCLUDED_EXACT = {"/favicon.ico"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = str(getattr(request, "path", "") or "")
        if self._is_excluded_path(path):
            return self.get_response(request)

        maintenance = normalize_maintenance_payload(
            get_app_json(MAINTENANCE_CONFIG_KEY, default={}, use_cache=False)
        )
        if is_maintenance_expired(maintenance):
            disable_maintenance_mode_in_db()
            maintenance["enabled"] = False
        request.maintenance_payload = maintenance
        if self._is_bypass_path(path):
            return self._handle_bypass_request(request, maintenance)

        maintenance_enabled = bool(maintenance.get("enabled"))
        if self._is_maintenance_path(path):
            if maintenance_enabled:
                return self._hard_maintenance_response(request, maintenance)
            return self.get_response(request)

        if not maintenance_enabled:
            return self.get_response(request)

        if has_admin_bypass_session(request):
            return self.get_response(request)

        next_path = request.get_full_path() or "/"
        query = urlencode({"next": next_path})
        return redirect(f"{self._maintenance_path(request)}?{query}")

    def _is_excluded_path(self, path: str) -> bool:
        if path in self.EXCLUDED_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in self.EXCLUDED_PREFIXES)

    def _maintenance_path(self, request=None) -> str:
        try:
            path = reverse("maintenance_page")
        except Exception:
            path = "/maintenance/"
        return self._localized_path(path, request)

    def _bypass_path(self, request=None) -> str:
        try:
            path = reverse("maintenance_bypass")
        except Exception:
            path = "/maintenance/bypass"
        return self._localized_path(path, request)

    def _localized_path(self, path: str, request=None) -> str:
        raw_path = str(path or "/")
        normalized_path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
        parts = [part for part in normalized_path.split("/") if part]
        first = language_from_path_segment(parts[0]) if parts else ""
        if first in SUPPORTED_LANGUAGES:
            return normalized_path

        language = normalize_language_code(getattr(request, "site_language", "") if request is not None else "")
        if request is not None and not str(getattr(request, "site_language", "") or "").strip():
            language = get_request_language(request)

        if normalized_path == "/":
            return f"/{language}/"
        return f"/{language}{normalized_path}"

    def _is_maintenance_path(self, path: str) -> bool:
        normalized = str(path or "")
        return (
            normalized in {"/maintenance", "/maintenance/"}
            or normalized.startswith("/maintenance/")
        )

    def _is_bypass_path(self, path: str) -> bool:
        normalized = str(path or "")
        return (
            normalized in {"/maintenance/bypass", "/maintenance/bypass/"}
            or normalized.startswith("/maintenance/bypass/")
        )

    def _to_bool(self, value) -> bool:
        normalized = str(value or "").strip().lower()
        return normalized in {"1", "true", "yes", "on"}

    def _safe_next_url(self, request, raw_value: str | None, default: str) -> str:
        value = (raw_value or "").strip() or default
        if not url_has_allowed_host_and_scheme(
            value,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return default
        return value

    def _handle_bypass_request(self, request, maintenance: dict):
        enable_raw = (request.GET.get("enable") or request.POST.get("enable") or "1").strip().lower()
        enable = self._to_bool(enable_raw)
        wants_json = self._to_bool(request.GET.get("json") or request.POST.get("json")) or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        next_url = self._safe_next_url(request, request.GET.get("next") or request.POST.get("next"), default="/")

        if enable:
            request.session[MAINTENANCE_BYPASS_SESSION_KEY] = True
        else:
            request.session.pop(MAINTENANCE_BYPASS_SESSION_KEY, None)

        if wants_json:
            return JsonResponse(
                {
                    "ok": True,
                    "bypass_enabled": bool(request.session.get(MAINTENANCE_BYPASS_SESSION_KEY)),
                    "maintenance_enabled": bool((maintenance or {}).get("enabled")),
                    "maintenance_url": self._maintenance_path(request),
                    "next": next_url,
                }
            )
        return redirect(next_url)

    def _hard_maintenance_response(self, request, maintenance: dict):
        next_url = self._safe_next_url(request, request.GET.get("next"), default="/")
        html = build_hard_maintenance_html(
            language=getattr(request, "site_language", "ru"),
            launch_at_ms=(maintenance or {}).get("launch_at_ms"),
            message=str((maintenance or {}).get("message") or ""),
            next_url=next_url,
            bypass_url=self._bypass_path(request),
        )
        return self._html_response(html)

    def _html_response(self, html: str):
        from django.http import HttpResponse

        return HttpResponse(html, content_type="text/html; charset=utf-8")
