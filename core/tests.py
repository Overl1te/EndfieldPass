import json
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .cloud import CloudIntegrationError, build_oauth_authorization_url
from .models import ImportSession, Pull


class SettingsPageTests(TestCase):
    def test_settings_page_contains_repository_link(self):
        response = self.client.get(reverse("settings_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://github.com/Overl1te/EndfieldPass")

    def test_can_switch_interface_language(self):
        response = self.client.post(
            reverse("set_site_language"),
            {"lang": "en", "next": reverse("dashboard")},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))

        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Wish Counter")


class FooterAndLegalPagesTests(TestCase):
    def test_footer_contains_legal_links(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("privacy_policy"))
        self.assertContains(response, reverse("cookies_policy"))
        self.assertContains(response, "https://github.com/Overl1te/EndfieldPass")

    def test_legal_pages_open(self):
        privacy = self.client.get(reverse("privacy_policy"))
        cookies = self.client.get(reverse("cookies_policy"))
        self.assertEqual(privacy.status_code, 200)
        self.assertEqual(cookies.status_code, 200)


class CharactersPageTests(TestCase):
    def test_characters_page_contains_expected_names(self):
        response = self.client.get(reverse("characters_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Лэватейн")
        self.assertContains(response, "Чэнь Цяньюй")
        self.assertContains(response, "Флюорит")
        self.assertContains(response, "Авивенна")
        self.assertContains(response, "Гилберта")
        self.assertContains(response, "Ивонн")

    def test_characters_page_contains_23_cards(self):
        response = self.client.get(reverse("characters_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="character-card"', count=23)

    def test_characters_page_shows_missing_status_without_imports(self):
        response = self.client.get(reverse("characters_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Не получено")

    def test_endministrator_is_marked_obtained_by_default(self):
        response = self.client.get(reverse("characters_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Получено · дата неизвестна")

    def test_characters_page_shows_obtained_status_with_date(self):
        session = ImportSession.objects.create(
            page_url="",
            token="token",
            server_id="3",
            lang="ru-ru",
            status="done",
        )
        Pull.objects.create(
            session=session,
            pool_id="special",
            pool_name="Special",
            char_id="1001",
            char_name="Akekuri",
            rarity=4,
            is_free=False,
            is_new=True,
            gacha_ts=1700000000000,
            seq_id=1,
            source_pool_type="E_CharacterGachaPoolType_Special",
            raw={"seqId": 1},
        )

        response = self.client.get(reverse("characters_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Получено ·")


class WeaponsPageTests(TestCase):
    def test_weapons_page_opens(self):
        response = self.client.get(reverse("weapons_page"))
        self.assertEqual(response.status_code, 200)

    def test_weapons_page_contains_weapon_cards(self):
        response = self.client.get(reverse("weapons_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-weapon-card')


class HistoryExportImportTests(TestCase):
    def test_export_history_returns_json_attachment(self):
        session = ImportSession.objects.create(
            page_url="",
            token="token",
            server_id="3",
            lang="ru-ru",
            status="done",
        )
        Pull.objects.create(
            session=session,
            pool_id="special",
            pool_name="Special",
            char_id="1001",
            char_name="Alice",
            rarity=6,
            is_free=False,
            is_new=True,
            gacha_ts=1700000000000,
            seq_id=1,
            source_pool_type="E_CharacterGachaPoolType_Special",
            raw={"seqId": 1},
        )

        response = self.client.get(reverse("export_history"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])

        payload = json.loads(response.content)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["session_count"], 1)
        self.assertEqual(payload["pull_count"], 1)
        self.assertEqual(payload["sessions"][0]["pulls"][0]["char_name"], "Alice")

    def test_import_history_creates_sessions_and_pulls(self):
        payload = {
            "schema_version": 1,
            "sessions": [
                {
                    "created_at": "2026-02-01T12:00:00+03:00",
                    "server_id": "4",
                    "lang": "en-us",
                    "status": "done",
                    "pulls": [
                        {
                            "pool_id": "standard",
                            "pool_name": "Standard",
                            "char_id": "2002",
                            "char_name": "Bob",
                            "rarity": 5,
                            "is_free": False,
                            "is_new": False,
                            "gacha_ts": 1700000100000,
                            "seq_id": 2,
                            "source_pool_type": "E_CharacterGachaPoolType_Standard",
                        }
                    ],
                }
            ],
        }
        upload = SimpleUploadedFile(
            "history.json",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

        response = self.client.post(reverse("import_history"), {"history_file": upload})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Импорт завершён")
        self.assertEqual(ImportSession.objects.count(), 1)
        self.assertEqual(Pull.objects.count(), 1)
        self.assertEqual(ImportSession.objects.first().server_id, "4")


class CloudIntegrationTests(TestCase):
    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="google-client",
        GOOGLE_OAUTH_CLIENT_SECRET="google-secret",
        GOOGLE_OAUTH_SCOPE="https://www.googleapis.com/auth/drive.file",
        DJANGO_EXTERNAL_BASE_URL="https://endfieldpass.com",
    )
    @patch("core.views.build_oauth_authorization_url")
    def test_cloud_connect_redirects_to_provider(self, auth_url_mock):
        auth_url_mock.return_value = "https://example.com/oauth"

        response = self.client.get(reverse("cloud_connect", args=["google_drive"]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/oauth")
        auth_url_mock.assert_called_once()
        kwargs = auth_url_mock.call_args.kwargs
        self.assertEqual(kwargs["redirect_uri"], "https://endfieldpass.com/settings/cloud/google_drive/callback")
        self.assertEqual(kwargs["scope"], "https://www.googleapis.com/auth/drive.file")

        session = self.client.session
        self.assertIn("cloud_oauth_state", session)
        self.assertEqual(session["cloud_oauth_state"]["provider"], "google_drive")

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="google-client",
        GOOGLE_OAUTH_CLIENT_SECRET="google-secret",
    )
    @patch("core.views.exchange_oauth_code")
    def test_cloud_callback_stores_tokens(self, exchange_mock):
        exchange_mock.return_value = {
            "access_token": "acc-token",
            "refresh_token": "ref-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        session = self.client.session
        session["cloud_oauth_state"] = {"provider": "google_drive", "state": "state-123"}
        session.save()

        response = self.client.get(
            reverse("cloud_callback", args=["google_drive"]),
            {"state": "state-123", "code": "code-abc"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("settings_page"))

        saved = self.client.session.get("cloud_auth", {}).get("google_drive", {})
        self.assertEqual(saved.get("access_token"), "acc-token")
        self.assertEqual(saved.get("refresh_token"), "ref-token")

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="google-client",
        GOOGLE_OAUTH_CLIENT_SECRET="google-secret",
    )
    @patch("core.views.export_payload_to_cloud")
    def test_cloud_export_success(self, export_mock):
        export_mock.return_value = {
            "provider": "google_drive",
            "folder_name": "EndfieldPass",
            "file_name": "history-latest.json",
        }

        session = self.client.session
        session["cloud_auth"] = {
            "google_drive": {
                "access_token": "token-123",
            }
        }
        session.save()

        response = self.client.post(reverse("cloud_export"), {"provider": "google_drive"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Синхронизация в облако выполнена")
        export_mock.assert_called_once()
        call_kwargs = export_mock.call_args.kwargs
        self.assertEqual(call_kwargs["provider"], "google_drive")
        self.assertEqual(call_kwargs["token"], "token-123")
        self.assertIn("schema_version", call_kwargs["payload"])

    @patch("core.views.import_payload_from_cloud")
    def test_cloud_import_by_url_success(self, import_mock):
        import_mock.return_value = {
            "schema_version": 1,
            "sessions": [
                {
                    "server_id": "3",
                    "lang": "ru-ru",
                    "status": "done",
                    "pulls": [
                        {
                            "pool_id": "special",
                            "pool_name": "Special",
                            "char_id": "1001",
                            "char_name": "Akekuri",
                            "rarity": 4,
                            "is_free": False,
                            "is_new": True,
                            "gacha_ts": 1700000000000,
                            "seq_id": 1,
                            "source_pool_type": "E_CharacterGachaPoolType_Special",
                        }
                    ],
                }
            ],
        }

        response = self.client.post(
            reverse("cloud_import"),
            {
                "provider": "url",
                "remote_ref": "https://example.com/history.json",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Облачный импорт завершён")
        self.assertEqual(ImportSession.objects.count(), 1)
        self.assertEqual(Pull.objects.count(), 1)
        import_mock.assert_called_once_with(provider="url", token="", remote_ref="https://example.com/history.json")

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="google-client",
        GOOGLE_OAUTH_CLIENT_SECRET="google-secret",
    )
    @patch("core.views.import_payload_from_cloud")
    def test_cloud_import_from_connected_provider(self, import_mock):
        import_mock.return_value = {"schema_version": 1, "sessions": []}

        session = self.client.session
        session["cloud_auth"] = {
            "google_drive": {
                "access_token": "token-123",
            }
        }
        session.save()

        response = self.client.post(reverse("cloud_import"), {"provider": "google_drive"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Облачный импорт завершён")
        import_mock.assert_called_once_with(provider="google_drive", token="token-123", remote_ref="")

    def test_cloud_disconnect_clears_session(self):
        session = self.client.session
        session["cloud_auth"] = {
            "google_drive": {
                "access_token": "token-123",
            }
        }
        session.save()

        response = self.client.post(reverse("cloud_disconnect", args=["google_drive"]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("settings_page"))

        saved = self.client.session.get("cloud_auth", {})
        self.assertNotIn("google_drive", saved)

    def test_cloud_import_requires_url_when_provider_is_url(self):
        response = self.client.post(
            reverse("cloud_import"),
            {
                "provider": "url",
                "remote_ref": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Укажите прямую ссылку на JSON-файл")

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="google-client",
        GOOGLE_OAUTH_CLIENT_SECRET="google-secret",
    )
    @patch("core.views.export_payload_to_cloud")
    def test_cloud_export_handles_provider_error(self, export_mock):
        export_mock.side_effect = CloudIntegrationError("bad token")

        session = self.client.session
        session["cloud_auth"] = {
            "google_drive": {
                "access_token": "wrong",
            }
        }
        session.save()

        response = self.client.post(reverse("cloud_export"), {"provider": "google_drive"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Не удалось выполнить облачную синхронизацию")
        self.assertContains(response, "bad token")


class CloudOAuthUrlTests(TestCase):
    def test_google_scope_normalizes_comma_and_space_list(self):
        url = build_oauth_authorization_url(
            provider="google_drive",
            client_id="google-client",
            redirect_uri="https://example.com/settings/cloud/google_drive/callback",
            state="state-123",
            scope="https://www.googleapis.com/auth/drive.file, https://www.googleapis.com/auth/drive.metadata.readonly",
        )
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(
            query.get("scope", [""])[0],
            "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.metadata.readonly",
        )

    def test_yandex_defaults_to_app_folder_scope(self):
        url = build_oauth_authorization_url(
            provider="yandex_disk",
            client_id="yandex-client",
            redirect_uri="https://example.com/settings/cloud/yandex_disk/callback",
            state="state-123",
            scope="",
        )
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("scope", [""])[0], "cloud_api:disk.app_folder")
