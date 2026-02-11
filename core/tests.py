import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse as django_reverse

from .cloud import CloudIntegrationError, build_oauth_authorization_url
from .bootstrap import BOOTSTRAP_STATE_KEY, run_data_bootstrap
from .config_store import reset_app_json_cache
from .localization import reset_translation_cache, translate
from .models import (
    AppAddress,
    AppJsonConfig,
    Banner,
    ImportSession,
    LocalizationEntry,
    Pull,
    StaticCharacter,
    VersionTopStatsSnapshot,
    WeaponCatalog,
)
from .views import _compute_version_top_stats_from_pulls


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
        self.assertEqual(response["Location"], reverse("dashboard", lang="en"))

        dashboard = self.client.get(reverse("dashboard", lang="en"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Wish Counter")


class FooterAndLegalPagesTests(TestCase):
    def test_footer_contains_legal_links(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("privacy_policy"))
        self.assertContains(response, reverse("cookies_policy"))
        self.assertContains(response, "https://github.com/Overl1te/EndfieldPass")


class LocalizationDbTests(TestCase):
    def tearDown(self):
        reset_translation_cache()
        super().tearDown()

    def test_translate_prefers_db_value(self):
        LocalizationEntry.objects.create(
            key="tests.sample",
            translations={"ru": "Из БД", "en": "From DB"},
        )
        reset_translation_cache()
        self.assertEqual(translate("ru", "tests.sample"), "Из БД")
        self.assertEqual(translate("en", "tests.sample"), "From DB")

    def test_settings_page_prefers_repository_url_from_env_over_db(self):
        AppAddress.objects.create(
            key="repository_url",
            value="https://example.com/custom-repo",
        )
        response = self.client.get(reverse("settings_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://github.com/Overl1te/EndfieldPass")
        self.assertNotContains(response, "https://example.com/custom-repo")

    @override_settings(OFFICIAL_REPOSITORY_URL="")
    def test_settings_page_falls_back_to_db_repository_url_when_env_is_empty(self):
        AppAddress.objects.create(
            key="repository_url",
            value="https://example.com/custom-repo",
        )
        response = self.client.get(reverse("settings_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://example.com/custom-repo")

    def test_legal_pages_open(self):
        privacy = self.client.get(reverse("privacy_policy"))
        cookies = self.client.get(reverse("cookies_policy"))
        self.assertEqual(privacy.status_code, 200)
        self.assertEqual(cookies.status_code, 200)


class MaintenanceModeTests(TestCase):
    def tearDown(self):
        reset_app_json_cache()
        super().tearDown()

    def _set_maintenance(self, *, enabled=True, launch_at="2026-02-12T18:00:00+03:00"):
        AppJsonConfig.objects.update_or_create(
            key="MAINTENANCE_MODE",
            defaults={
                "payload": {
                    "enabled": bool(enabled),
                    "launch_at": launch_at,
                }
            },
        )
        reset_app_json_cache()

    def test_redirects_to_maintenance_when_enabled(self):
        self._set_maintenance(enabled=True)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("maintenance_page")))
        self.assertIn("next=%2F", response["Location"])

    def test_admin_path_redirects_to_maintenance_without_bypass(self):
        self._set_maintenance(enabled=True)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("maintenance_page")))

    def test_bypass_endpoint_enables_session_bypass(self):
        self._set_maintenance(enabled=True)
        response = self.client.get(
            reverse("maintenance_bypass"),
            {"enable": "1", "next": reverse("dashboard")},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_bypass_endpoint_disable_removes_session_bypass(self):
        self._set_maintenance(enabled=True)
        self.client.get(reverse("maintenance_bypass"), {"enable": "1", "next": reverse("dashboard")})
        self.client.get(reverse("maintenance_bypass"), {"enable": "0", "next": reverse("dashboard")})
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("maintenance_page")))

    def test_bypass_endpoint_json_mode_updates_session(self):
        self._set_maintenance(enabled=True)
        response = self.client.get(
            reverse("maintenance_bypass"),
            {"json": "1", "enable": "1", "next": reverse("dashboard")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("bypass_enabled"))
        self.assertTrue(payload.get("maintenance_enabled"))

        response = self.client.get(reverse("maintenance_bypass"), {"json": "1", "enable": "0"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertFalse(payload.get("bypass_enabled"))

    def test_maintenance_page_is_open_and_has_countdown_payload(self):
        self._set_maintenance(enabled=True, launch_at="2026-02-12T18:00:00+03:00")
        response = self.client.get(reverse("maintenance_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "maintenanceTimerBox")
        self.assertContains(response, "data-launch-ms")

    def test_maintenance_auto_disables_after_launch_time(self):
        self._set_maintenance(enabled=True, launch_at="2020-01-01T00:00:00+00:00")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

        row = AppJsonConfig.objects.filter(key="MAINTENANCE_MODE").values_list("payload", flat=True).first() or {}
        self.assertFalse(bool((row or {}).get("enabled")))

    def test_maintenance_flag_changes_apply_without_server_restart(self):
        AppJsonConfig.objects.update_or_create(
            key="MAINTENANCE_MODE",
            defaults={"payload": {"enabled": True, "launch_at": "2099-01-01T00:00:00+00:00"}},
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("maintenance_page")))

        # Update DB flag without explicit cache reset: middleware must read latest value.
        AppJsonConfig.objects.update_or_create(
            key="MAINTENANCE_MODE",
            defaults={"payload": {"enabled": False, "launch_at": "2099-01-01T00:00:00+00:00"}},
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)


class GameDataDbTests(TestCase):
    def test_characters_page_uses_db_character_official_name(self):
        AppJsonConfig.objects.create(
            key="CHARACTER_OFFICIAL_NAMES",
            payload={
                "laevatain.png": {
                    "ru": "Лэватейн DB",
                    "en": "Laevatain DB",
                }
            },
        )
        response = self.client.get(reverse("characters_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Лэватейн DB")


class WeaponCatalogJsonCommandTests(TestCase):
    def test_import_localization_json_imports_weapon_catalog(self):
        payload = {
            "weapons_catalog": [
                {
                    "key": "Test Weapon",
                    "rarity": 6,
                    "weapon_type": WeaponCatalog.TYPE_SHORT,
                    "icon_name": "test-weapon.webp",
                    "name_i18n": {"ru": "Тестовое оружие", "en": "Test Weapon"},
                    "description_i18n": {"ru": "Описание", "en": "Description"},
                    "atk_min": 52,
                    "atk_max": 510,
                    "skills_min_i18n": {"ru": ["Навык 1", "Навык 2", "Навык 3"]},
                    "skills_max_i18n": {"ru": ["Макс 1", "Макс 2", "Макс 3"]},
                    "skills_full_i18n": {"ru": ["Эсс 1", "Эсс 2", "Эсс 3"]},
                    "operators_i18n": {"ru": ["Лэватейн"], "en": ["Laevatain"]},
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "weapons.json"
            json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            call_command("import_localization_json", str(json_path), "--replace-weapons")

        row = WeaponCatalog.objects.get(key="Test Weapon")
        self.assertEqual(row.rarity, 6)
        self.assertEqual(row.weapon_type, WeaponCatalog.TYPE_SHORT)
        self.assertEqual(row.atk_min, 52)
        self.assertEqual(row.atk_max, 510)
        self.assertEqual((row.name_i18n or {}).get("ru"), "Тестовое оружие")
        self.assertEqual((row.operators_i18n or {}).get("en"), ["Laevatain"])

    def test_export_localization_json_includes_weapon_catalog(self):
        WeaponCatalog.objects.create(
            key="Exported Weapon",
            rarity=5,
            weapon_type=WeaponCatalog.TYPE_GUNS,
            icon_name="exported-weapon.webp",
            name_i18n={"ru": "Экспорт", "en": "Export"},
            description_i18n={"ru": "Описание"},
            atk_min=33,
            atk_max=333,
            skills_min_i18n={"ru": ["A", "B", "C"]},
            skills_max_i18n={"ru": ["D", "E", "F"]},
            skills_full_i18n={"ru": ["G", "H", "I"]},
            operators_i18n={"ru": ["Эмбер"]},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "export.json"
            call_command("export_localization_json", str(json_path))
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        rows = payload.get("weapons_catalog") or []
        self.assertTrue(any(str(item.get("key") or "") == "Exported Weapon" for item in rows))


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

    def test_characters_page_contains_filter_controls(self):
        response = self.client.get(reverse("characters_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-character-filter-group="element"')
        self.assertContains(response, 'data-character-filter-group="weapon"')
        self.assertContains(response, 'data-character-filter-group="role"')
        self.assertContains(response, 'data-character-filter-group="rarity"')

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


    @patch("core.views._latest_import_session")
    def test_characters_page_supports_in_memory_session_payload(self, latest_session_mock):
        latest_session_mock.return_value = {
            "id": 1,
            "status": "done",
            "pulls": [
                {
                    "char_name": "Akekuri",
                    "rarity": 4,
                    "gacha_ts": 1700000000000,
                    "seq_id": 1,
                    "item_type": "character",
                }
            ],
        }

        response = self.client.get(reverse("characters_page"))
        self.assertEqual(response.status_code, 200)
        characters = list(response.context.get("characters") or [])
        akekuri = next((item for item in characters if str(item.get("icon") or "") == "akekuri.png"), {})
        self.assertTrue(akekuri.get("is_obtained"))
        self.assertTrue(str(akekuri.get("obtained_date") or "").strip())


class WeaponsPageTests(TestCase):
    def test_weapons_page_opens(self):
        response = self.client.get(reverse("weapons_page"))
        self.assertEqual(response.status_code, 200)

    def test_weapons_page_contains_weapon_cards(self):
        response = self.client.get(reverse("weapons_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-weapon-card')

    def test_weapons_page_contains_modal_markup(self):
        response = self.client.get(reverse("weapons_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="weaponModal"')
        self.assertContains(response, 'id="weaponsCatalogPayload"')

    def test_weapons_page_contains_filter_controls(self):
        response = self.client.get(reverse("weapons_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-weapon-filter-group="type"')
        self.assertContains(response, 'data-weapon-filter-group="rarity"')


class DashboardBannerStatsTests(TestCase):
    def test_dashboard_uses_banner_fallback_rows_when_snapshot_absent(self):
        yvonne = StaticCharacter.objects.create(
            code="yvonne",
            name="Yvonne",
            aliases="Yvonne, Ивонна",
            static_icon_path="img/characters/yvonne.png",
        )
        laevatain = StaticCharacter.objects.create(
            code="laevatain",
            name="Laevatain",
            aliases="Laevatain, Лэватейн",
            static_icon_path="img/characters/laevatain.png",
        )
        Banner.objects.create(
            name="Version 1.0 / Banner 2",
            pool_id="special_1_0_2",
            top_character=yvonne,
            start_date="2026-01-01",
            end_date="2026-01-15",
        )
        Banner.objects.create(
            name="Version 1.0 / Banner 3",
            pool_id="special_1_0_3",
            top_character=laevatain,
            start_date="2026-01-16",
            end_date="2026-01-31",
        )

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        payload = response.context["version_top_stats"]
        self.assertEqual(payload["version_label"], "1.0")
        self.assertEqual(payload["total_top_drops"], 0)
        self.assertEqual(len(payload["stats"]), 2)
        rows = {row["character_code"]: row for row in payload["stats"]}
        self.assertIn("yvonne", rows)
        self.assertIn("laevatain", rows)
        self.assertEqual(rows["yvonne"]["drop_count"], 0)

    def test_dashboard_contains_latest_version_top_stats_from_db(self):
        top_character = StaticCharacter.objects.create(
            code="ember",
            name="Ember",
            aliases="Ember",
            static_icon_path="img/characters/ember.png",
        )
        six_star_character = StaticCharacter.objects.create(
            code="gilberta",
            name="Gilberta",
            aliases="Gilberta",
            static_icon_path="img/characters/gilberta.png",
        )
        banner = Banner.objects.create(
            name="Burning Route",
            pool_id="special_1_0_3",
            top_character=top_character,
            start_date="2026-01-01",
            end_date="2026-01-20",
        )
        banner.six_star_characters.set([top_character, six_star_character])
        VersionTopStatsSnapshot.objects.create(
            source_session_id=99,
            version_major=1,
            version_minor=0,
            version_label="1_0",
            tracked_characters_count=2,
            total_top_drops=3,
            stats=[
                {
                    "character_code": "ember",
                    "character_name": "Ember",
                    "icon_url": "/static/img/characters/ember.png",
                    "drop_count": 3,
                    "share_percent": 100,
                }
            ],
        )

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dashboard-version-top-stats")
        payload = response.context["version_top_stats"]
        self.assertEqual(payload["version_label"], "1.0")
        self.assertEqual(payload["total_top_drops"], 3)
        self.assertEqual(payload["stats"][0]["character_code"], "ember")

    def test_version_stats_count_top_character_across_all_banners_of_same_version(self):
        yvonne = StaticCharacter.objects.create(
            code="yvonne",
            name="Yvonne",
            aliases="Yvonne, Ивонна",
            static_icon_path="img/characters/yvonne.png",
        )
        laevatain = StaticCharacter.objects.create(
            code="laevatain",
            name="Laevatain",
            aliases="Laevatain, Лэватейн",
            static_icon_path="img/characters/laevatain.png",
        )
        Banner.objects.create(
            name="Version 1.0 / Banner 2",
            pool_id="special_1_0_2",
            is_active=True,
            top_character=yvonne,
            start_date="2026-01-01",
            end_date="2026-01-15",
        )
        Banner.objects.create(
            name="Version 1.0 / Banner 3",
            pool_id="special_1_0_3",
            top_character=laevatain,
            start_date="2026-01-16",
            end_date="2026-01-31",
        )

        pulls = [
            {
                "pool_id": "special_1_0_3",
                "char_name": "Yvonne",
                "char_id": "",
                "item_type": "character",
            },
            {
                "pool_id": "special_1_0_3",
                "char_name": "Yvonne",
                "char_id": "",
                "item_type": "character",
            },
            {
                "pool_id": "special_1_0_2",
                "char_name": "Yvonne",
                "char_id": "",
                "item_type": "character",
            },
        ]
        payload = _compute_version_top_stats_from_pulls(pulls=pulls, tracked_characters_count=5)
        self.assertIsNotNone(payload)
        rows = {row["character_code"]: row for row in payload["stats"]}
        self.assertEqual(payload["version_label"], "1.0")
        self.assertEqual(rows["yvonne"]["drop_count"], 3)
        self.assertEqual(rows["yvonne"]["current_banner_drop_count"], 1)

    def test_version_stats_ignore_old_versions_and_use_latest_only(self):
        yvonne = StaticCharacter.objects.create(
            code="yvonne",
            name="Yvonne",
            aliases="Yvonne, Ивонна",
            static_icon_path="img/characters/yvonne.png",
        )
        ember = StaticCharacter.objects.create(
            code="ember",
            name="Ember",
            aliases="Ember",
            static_icon_path="img/characters/ember.png",
        )
        Banner.objects.create(
            name="Version 1.0 / Banner 2",
            pool_id="special_1_0_2",
            top_character=yvonne,
            start_date="2026-01-01",
            end_date="2026-01-15",
        )
        Banner.objects.create(
            name="Version 1.1 / Banner 1",
            pool_id="special_1_1_1",
            top_character=ember,
            start_date="2026-02-01",
            end_date="2026-02-15",
        )

        pulls = [
            {
                "pool_id": "special_1_0_3",
                "char_name": "Yvonne",
                "char_id": "",
                "item_type": "character",
            },
            {
                "pool_id": "special_1_1_1",
                "char_name": "Ember",
                "char_id": "",
                "item_type": "character",
            },
        ]
        payload = _compute_version_top_stats_from_pulls(pulls=pulls, tracked_characters_count=5)
        self.assertIsNotNone(payload)
        rows = {row["character_code"]: row for row in payload["stats"]}
        self.assertEqual(payload["version_label"], "1.1")
        self.assertEqual(rows["ember"]["drop_count"], 1)
        self.assertNotIn("yvonne", rows)

    def test_version_stats_track_only_first_three_top_characters(self):
        alpha = StaticCharacter.objects.create(
            code="alpha",
            name="Alpha",
            aliases="Alpha",
            static_icon_path="img/characters/alpha.png",
        )
        bravo = StaticCharacter.objects.create(
            code="bravo",
            name="Bravo",
            aliases="Bravo",
            static_icon_path="img/characters/bravo.png",
        )
        charlie = StaticCharacter.objects.create(
            code="charlie",
            name="Charlie",
            aliases="Charlie",
            static_icon_path="img/characters/charlie.png",
        )
        delta = StaticCharacter.objects.create(
            code="delta",
            name="Delta",
            aliases="Delta",
            static_icon_path="img/characters/delta.png",
        )
        Banner.objects.create(
            name="Version 1.2 / Banner 1",
            pool_id="special_1_2_1",
            top_character=alpha,
            start_date="2026-03-01",
            end_date="2026-03-07",
        )
        Banner.objects.create(
            name="Version 1.2 / Banner 2",
            pool_id="special_1_2_2",
            top_character=bravo,
            start_date="2026-03-08",
            end_date="2026-03-14",
        )
        Banner.objects.create(
            name="Version 1.2 / Banner 3",
            pool_id="special_1_2_3",
            top_character=charlie,
            start_date="2026-03-15",
            end_date="2026-03-21",
        )
        Banner.objects.create(
            name="Version 1.2 / Banner 4",
            pool_id="special_1_2_4",
            top_character=delta,
            start_date="2026-03-22",
            end_date="2026-03-28",
        )

        pulls = [
            {"pool_id": "special_1_2_1", "char_name": "Alpha", "char_id": "", "item_type": "character"},
            {"pool_id": "special_1_2_2", "char_name": "Bravo", "char_id": "", "item_type": "character"},
            {"pool_id": "special_1_2_3", "char_name": "Charlie", "char_id": "", "item_type": "character"},
            {"pool_id": "special_1_2_4", "char_name": "Delta", "char_id": "", "item_type": "character"},
        ]
        payload = _compute_version_top_stats_from_pulls(pulls=pulls, tracked_characters_count=10)
        self.assertIsNotNone(payload)
        rows = {row["character_code"]: row for row in payload["stats"]}
        self.assertEqual(payload["version_label"], "1.2")
        self.assertEqual(len(rows), 3)
        self.assertIn("alpha", rows)
        self.assertIn("bravo", rows)
        self.assertIn("charlie", rows)
        self.assertNotIn("delta", rows)


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
        self.assertEqual(kwargs["redirect_uri"], "https://endfieldpass.com/ru/settings/cloud/google_drive/callback")
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


class DataBootstrapTests(TestCase):
    def test_run_data_bootstrap_skips_in_tests_by_default(self):
        result = run_data_bootstrap()
        self.assertEqual(result.get("status"), "skipped_in_tests")

    def test_run_data_bootstrap_runs_when_enabled_for_tests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "localization.json"
            source.write_text(json.dumps({"translations": {"ru": {"x.y": "z"}}}), encoding="utf-8")

            with patch.dict(os.environ, {"ENDFIELDPASS_AUTO_BOOTSTRAP_IN_TESTS": "1"}, clear=False):
                with patch("core.bootstrap.call_command") as call_command_mock:
                    result = run_data_bootstrap(source_path=source, force=True, verbosity=0)

        self.assertEqual(result.get("status"), "done")
        self.assertEqual(call_command_mock.call_count, 3)
        self.assertEqual(call_command_mock.call_args_list[0].args[0], "import_localization_json")
        self.assertEqual(call_command_mock.call_args_list[1].args[0], "sync_static_characters")
        self.assertEqual(call_command_mock.call_args_list[2].args[0], "sync_weapon_catalog")

        state = AppJsonConfig.objects.filter(key=BOOTSTRAP_STATE_KEY).values_list("payload", flat=True).first() or {}
        self.assertTrue(bool(state.get("ready")))
        self.assertTrue(str(state.get("localization_sha1") or "").strip())

    def test_run_data_bootstrap_recreates_maintenance_config_when_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "localization.json"
            source.write_text(json.dumps({"translations": {"ru": {"x.y": "z"}}}), encoding="utf-8")

            with patch.dict(os.environ, {"ENDFIELDPASS_AUTO_BOOTSTRAP_IN_TESTS": "1"}, clear=False):
                with patch("core.bootstrap.call_command") as call_command_mock:
                    first = run_data_bootstrap(source_path=source, force=True, verbosity=0)
                    self.assertEqual(first.get("status"), "done")
                    AppJsonConfig.objects.filter(key="MAINTENANCE_MODE").delete()
                    second = run_data_bootstrap(source_path=source, verbosity=0)

        self.assertEqual(second.get("status"), "up_to_date")
        self.assertEqual(call_command_mock.call_count, 3)
        maintenance = AppJsonConfig.objects.filter(key="MAINTENANCE_MODE").values_list("payload", flat=True).first()
        self.assertIsInstance(maintenance, dict)
        self.assertFalse(bool((maintenance or {}).get("enabled")))

    @patch("core.management.commands.bootstrap_app_data.run_data_bootstrap")
    def test_bootstrap_app_data_command_calls_service(self, run_bootstrap_mock):
        run_bootstrap_mock.return_value = {"status": "done", "hash": "abc"}
        call_command("bootstrap_app_data", "--force", "--source=custom.json", "--database=default")
        kwargs = run_bootstrap_mock.call_args.kwargs
        self.assertEqual(kwargs["using"], "default")
        self.assertTrue(kwargs["force"])
        self.assertEqual(Path(kwargs["source_path"]).name, "custom.json")

