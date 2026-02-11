import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse as django_reverse

from core.cloud import CloudIntegrationError, import_payload_from_cloud
from core.views import MAX_HISTORY_FILE_BYTES


def reverse(viewname, urlconf=None, args=None, kwargs=None, current_app=None, lang="ru"):
    """Build canonical language-prefixed app URLs for tests."""
    path = django_reverse(viewname, urlconf=urlconf, args=args, kwargs=kwargs, current_app=current_app)
    normalized = str(path or "/")
    if normalized.startswith(f"/{lang}/"):
        return normalized
    if normalized in {"/admin/", "/favicon.ico"} or normalized.startswith("/static/"):
        return normalized
    if normalized == "/":
        return f"/{lang}/"
    return f"/{lang}{normalized}"


class SecurityHeadersTests(TestCase):
    def test_dashboard_response_contains_security_headers(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.get("X-Frame-Options"), "DENY")
        self.assertTrue(str(response.get("Content-Security-Policy") or "").strip())


class ApiInputValidationTests(TestCase):
    def test_create_session_rejects_invalid_token(self):
        response = self.client.post(
            reverse("create_session"),
            data=json.dumps(
                {
                    "token": "<script>alert(1)</script>",
                    "server_id": "3",
                    "lang": "ru-ru",
                    "import_kind": "character",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_cloud_auto_export_rejects_oversized_payload(self):
        huge = "a" * (MAX_HISTORY_FILE_BYTES + 1024)
        response = self.client.post(
            reverse("cloud_auto_export_api"),
            data=json.dumps(
                {
                    "provider": "google_drive",
                    "payload": {"blob": huge},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json().get("ok", True))

    @override_settings(
        TURNSTILE_ENABLED=True,
        TURNSTILE_SITE_KEY="site-key",
        TURNSTILE_SECRET_KEY="secret-key",
    )
    def test_create_session_requires_turnstile_token_when_enabled(self):
        response = self.client.post(
            reverse("create_session"),
            data=json.dumps(
                {
                    "token": "valid-token-123456",
                    "server_id": "3",
                    "lang": "ru-ru",
                    "import_kind": "character",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("turnstile required", response.content.decode("utf-8").lower())

    @override_settings(
        TURNSTILE_ENABLED=True,
        TURNSTILE_SITE_KEY="site-key",
        TURNSTILE_SECRET_KEY="secret-key",
    )
    @patch("core.views.verify_turnstile_token")
    def test_create_session_rejects_invalid_turnstile_token(self, verify_mock):
        verify_mock.return_value = False
        response = self.client.post(
            reverse("create_session"),
            data=json.dumps(
                {
                    "token": "valid-token-123456",
                    "server_id": "3",
                    "lang": "ru-ru",
                    "import_kind": "character",
                    "turnstile_token": "bad-response",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("turnstile failed", response.content.decode("utf-8").lower())
        verify_mock.assert_called_once()

    @override_settings(
        TURNSTILE_ENABLED=True,
        TURNSTILE_SITE_KEY="site-key",
        TURNSTILE_SECRET_KEY="secret-key",
    )
    @patch("core.views.threading.Thread")
    @patch("core.views.verify_turnstile_token")
    def test_create_session_accepts_valid_turnstile_token(self, verify_mock, thread_mock):
        verify_mock.return_value = True
        response = self.client.post(
            reverse("create_session"),
            data=json.dumps(
                {
                    "token": "valid-token-123456",
                    "server_id": "3",
                    "lang": "ru-ru",
                    "import_kind": "character",
                    "turnstile_token": "turnstile-response",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(bool(response.json().get("session_id")))
        verify_mock.assert_called_once()
        thread_mock.assert_called_once()


class DirectUrlImportSecurityTests(TestCase):
    def test_direct_url_import_blocks_private_host(self):
        with self.assertRaises(CloudIntegrationError):
            import_payload_from_cloud(provider="url", token="", remote_ref="https://127.0.0.1/history.json")

    @patch("core.cloud._request")
    @patch("core.cloud.socket.getaddrinfo")
    def test_direct_url_import_allows_public_host(self, getaddrinfo_mock, request_mock):
        getaddrinfo_mock.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ]

        class _FakeResponse:
            status_code = 200
            history = []
            headers = {"Content-Type": "application/json"}
            url = "https://example.com/history.json"

            @staticmethod
            def iter_content(chunk_size=65536):
                yield b'{"schema_version":1,"sessions":[]}'

        request_mock.return_value = _FakeResponse()
        payload = import_payload_from_cloud(
            provider="url",
            token="",
            remote_ref="https://example.com/history.json",
        )
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("schema_version"), 1)
