import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.config_store import GAME_DATA_KEYS
from core.localization import TRANSLATIONS, normalize_language_code
from core.models import AppAddress, AppJsonConfig, LocalizationEntry, WeaponCatalog


class Command(BaseCommand):
    help = "Export localization keys, addresses, game data and weapon catalog to JSON for server transfer."

    def add_arguments(self, parser):
        parser.add_argument("json_path", help="Output JSON file path.")
        parser.add_argument(
            "--include-fallback",
            action="store_true",
            help="Include in-code fallback translations when DB is empty.",
        )

    def handle(self, *args, **options):
        output = Path(str(options.get("json_path") or "").strip())
        if not output:
            raise CommandError("Output path is required.")

        translations_payload = {}
        rows = list(LocalizationEntry.objects.all().only("key", "translations"))
        if rows:
            for row in rows:
                key = str(row.key or "").strip()
                values = row.translations if isinstance(row.translations, dict) else {}
                if not key:
                    continue
                for raw_lang, raw_value in values.items():
                    lang = normalize_language_code(str(raw_lang or ""))
                    text = str(raw_value or "")
                    if not text:
                        continue
                    translations_payload.setdefault(lang, {})[key] = text
        elif bool(options.get("include_fallback")):
            translations_payload = {lang: dict(mapping or {}) for lang, mapping in TRANSLATIONS.items()}

        addresses_payload = {
            str(row.key or "").strip(): str(row.value or "").strip()
            for row in AppAddress.objects.all().only("key", "value")
            if str(row.key or "").strip() and str(row.value or "").strip()
        }
        if not addresses_payload:
            addresses_payload = {
                "repository_url": str(getattr(settings, "OFFICIAL_REPOSITORY_URL", "") or "").strip(),
                "donate_url": str(getattr(settings, "DONATE_URL", "") or "").strip(),
            }
            addresses_payload = {key: value for key, value in addresses_payload.items() if value}

        payload = {
            "translations": translations_payload,
            "addresses": addresses_payload,
            "game_data": {},
            "weapons_catalog": [],
        }

        game_data_payload = {}
        for row in AppJsonConfig.objects.filter(key__in=GAME_DATA_KEYS).only("key", "payload"):
            key = str(row.key or "").strip()
            if not key:
                continue
            if isinstance(row.payload, (dict, list)):
                game_data_payload[key] = row.payload

        if not game_data_payload and bool(options.get("include_fallback")):
            from core.views import (  # Imported lazily to avoid heavy module load for regular exports.
                CHARACTERS,
                CHARACTER_ELEMENTS,
                CHARACTER_OFFICIAL_NAMES,
                CHARACTER_ROLES,
                CHARACTER_WEAPONS,
                RARITY_ICONS,
                WEAPON_OFFICIAL_NAMES,
            )

            game_data_payload = {
                "CHARACTER_OFFICIAL_NAMES": CHARACTER_OFFICIAL_NAMES,
                "WEAPON_OFFICIAL_NAMES": WEAPON_OFFICIAL_NAMES,
                "CHARACTERS": CHARACTERS,
                "RARITY_ICONS": RARITY_ICONS,
                "CHARACTER_ROLES": CHARACTER_ROLES,
                "CHARACTER_WEAPONS": CHARACTER_WEAPONS,
                "CHARACTER_ELEMENTS": CHARACTER_ELEMENTS,
            }

        payload["game_data"] = game_data_payload

        weapons_catalog_payload = []
        for row in WeaponCatalog.objects.all():
            weapons_catalog_payload.append(
                {
                    "key": str(row.key or "").strip(),
                    "rarity": int(row.rarity or 0),
                    "weapon_type": str(row.weapon_type or "").strip(),
                    "icon_name": str(row.icon_name or "").strip(),
                    "name_i18n": dict(row.name_i18n or {}),
                    "description_i18n": dict(row.description_i18n or {}),
                    "atk_min": int(row.atk_min or 0),
                    "atk_max": int(row.atk_max or 0),
                    "skills_min_i18n": dict(row.skills_min_i18n or {}),
                    "skills_max_i18n": dict(row.skills_max_i18n or {}),
                    "skills_full_i18n": dict(row.skills_full_i18n or {}),
                    "operators_i18n": dict(row.operators_i18n or {}),
                }
            )
        payload["weapons_catalog"] = weapons_catalog_payload

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"Localization exported to {output}. "
                f"Languages: {len(translations_payload)}. "
                f"Addresses: {len(addresses_payload)}. "
                f"Game data blobs: {len(game_data_payload)}. "
                f"Weapons: {len(weapons_catalog_payload)}."
            )
        )
