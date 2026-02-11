import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.config_store import GAME_DATA_KEYS, reset_app_json_cache
from core.localization import normalize_language_code, reset_translation_cache
from core.models import AppAddress, AppJsonConfig, LocalizationEntry, WeaponCatalog


class Command(BaseCommand):
    help = "Import localization keys, app addresses, game data and weapon catalog from JSON into DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            help="Path to JSON file. Supports {'translations': {...}, 'addresses': {...}}.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Remove all existing localization entries before import.",
        )
        parser.add_argument(
            "--replace-addresses",
            action="store_true",
            help="Remove all existing app addresses before import.",
        )
        parser.add_argument(
            "--replace-game-data",
            action="store_true",
            help="Remove all existing app JSON config rows before import.",
        )
        parser.add_argument(
            "--replace-weapons",
            action="store_true",
            help="Remove all existing weapon catalog rows before import.",
        )

    @staticmethod
    def _to_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _collect_translation_rows(raw_payload):
        if not isinstance(raw_payload, dict):
            return {}
        payload = raw_payload.get("translations")
        if payload is None:
            payload = raw_payload
        if not isinstance(payload, dict):
            return {}

        rows = {}
        for raw_lang, mapping in payload.items():
            if not isinstance(mapping, dict):
                continue
            lang = normalize_language_code(str(raw_lang or ""))
            for raw_key, raw_text in mapping.items():
                key = str(raw_key or "").strip()
                if not key:
                    continue
                text = str(raw_text or "")
                if not text:
                    continue
                rows.setdefault(key, {})[lang] = text
        return rows

    @staticmethod
    def _collect_address_rows(raw_payload):
        if not isinstance(raw_payload, dict):
            return {}
        addresses = raw_payload.get("addresses")
        if not isinstance(addresses, dict):
            return {}
        rows = {}
        for raw_key, raw_value in addresses.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            value = str(raw_value or "").strip()
            if not value:
                continue
            rows[key] = value
        return rows

    @staticmethod
    def _collect_game_data_rows(raw_payload):
        if not isinstance(raw_payload, dict):
            return {}
        game_data = raw_payload.get("game_data")
        if not isinstance(game_data, dict):
            return {}

        key_map = {str(value).upper(): str(value) for value in GAME_DATA_KEYS}
        rows = {}
        for raw_key, raw_value in game_data.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            canonical_key = key_map.get(key.upper())
            if not canonical_key:
                continue
            if isinstance(raw_value, (dict, list)):
                rows[canonical_key] = raw_value
        return rows

    @staticmethod
    def _normalize_i18n_dict(value):
        if not isinstance(value, dict):
            return {}
        normalized = {}
        for raw_lang, raw_value in value.items():
            lang = normalize_language_code(str(raw_lang or ""))
            if isinstance(raw_value, (list, tuple)):
                items = [str(item or "").strip() for item in raw_value if str(item or "").strip()]
                normalized[lang] = items
                continue
            text = str(raw_value or "").strip()
            if text:
                normalized[lang] = text
        return normalized

    @classmethod
    def _collect_weapon_rows(cls, raw_payload):
        if not isinstance(raw_payload, dict):
            return {}
        rows = raw_payload.get("weapons_catalog")
        if not isinstance(rows, list):
            return {}

        allowed_types = {
            WeaponCatalog.TYPE_SHORT,
            WeaponCatalog.TYPE_GREAT,
            WeaponCatalog.TYPE_GUNS,
            WeaponCatalog.TYPE_POLEARMS,
            WeaponCatalog.TYPE_ORBITERS,
        }
        i18n_fields = (
            "name_i18n",
            "description_i18n",
            "skills_min_i18n",
            "skills_max_i18n",
            "skills_full_i18n",
            "operators_i18n",
        )
        normalized_rows = {}
        for item in rows:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            payload = {}
            if "rarity" in item:
                payload["rarity"] = max(0, cls._to_int(item.get("rarity"), default=4))
            if "weapon_type" in item:
                weapon_type = str(item.get("weapon_type") or "").strip().lower()
                if weapon_type in allowed_types:
                    payload["weapon_type"] = weapon_type
            if "icon_name" in item:
                icon_name = str(item.get("icon_name") or "").strip()
                if icon_name:
                    payload["icon_name"] = icon_name
            if "atk_min" in item:
                payload["atk_min"] = max(0, cls._to_int(item.get("atk_min"), default=0))
            if "atk_max" in item:
                payload["atk_max"] = max(0, cls._to_int(item.get("atk_max"), default=0))

            for field_name in i18n_fields:
                if field_name not in item:
                    continue
                payload[field_name] = cls._normalize_i18n_dict(item.get(field_name))

            normalized_rows[key] = payload
        return normalized_rows

    def handle(self, *args, **options):
        path = Path(str(options.get("json_path") or "").strip())
        if not path.exists() or not path.is_file():
            raise CommandError(f"JSON file not found: {path}")

        try:
            # Accept both regular UTF-8 and UTF-8 with BOM.
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise CommandError(f"Failed to parse JSON: {exc}") from exc

        translations = self._collect_translation_rows(payload)
        addresses = self._collect_address_rows(payload)
        game_data = self._collect_game_data_rows(payload)
        weapons_catalog = self._collect_weapon_rows(payload)
        if not translations and not addresses and not game_data and not weapons_catalog:
            raise CommandError("No translations/addresses/game_data/weapons_catalog found in JSON.")

        replace = bool(options.get("replace"))
        replace_addresses = bool(options.get("replace_addresses"))
        replace_game_data = bool(options.get("replace_game_data"))
        replace_weapons = bool(options.get("replace_weapons"))

        created = 0
        updated = 0
        address_created = 0
        address_updated = 0
        game_data_created = 0
        game_data_updated = 0
        weapon_created = 0
        weapon_updated = 0

        with transaction.atomic():
            if replace:
                LocalizationEntry.objects.all().delete()
            if replace_addresses:
                AppAddress.objects.all().delete()
            if replace_game_data:
                AppJsonConfig.objects.all().delete()
            if replace_weapons:
                WeaponCatalog.objects.all().delete()

            for key, incoming_map in translations.items():
                obj = LocalizationEntry.objects.filter(key=key).first()
                if obj is None:
                    LocalizationEntry.objects.create(key=key, translations=dict(incoming_map))
                    created += 1
                    continue

                current = {} if replace else dict(obj.translations or {})
                current.update(incoming_map)
                if current != (obj.translations or {}):
                    obj.translations = current
                    obj.save(update_fields=["translations", "updated_at"])
                    updated += 1

            for key, value in addresses.items():
                obj = AppAddress.objects.filter(key=key).first()
                if obj is None:
                    AppAddress.objects.create(key=key, value=value)
                    address_created += 1
                    continue
                if str(obj.value or "") != value:
                    obj.value = value
                    obj.save(update_fields=["value", "updated_at"])
                    address_updated += 1

            for key, payload_value in game_data.items():
                obj = AppJsonConfig.objects.filter(key=key).first()
                if obj is None:
                    AppJsonConfig.objects.create(key=key, payload=payload_value)
                    game_data_created += 1
                    continue
                if obj.payload != payload_value:
                    obj.payload = payload_value
                    obj.save(update_fields=["payload", "updated_at"])
                    game_data_updated += 1

            for key, incoming in weapons_catalog.items():
                obj = WeaponCatalog.objects.filter(key=key).first()
                if obj is None:
                    payload_for_create = {
                        "key": key,
                        "rarity": max(0, self._to_int(incoming.get("rarity"), default=4)),
                        "weapon_type": str(incoming.get("weapon_type") or WeaponCatalog.TYPE_SHORT).strip().lower() or WeaponCatalog.TYPE_SHORT,
                        "icon_name": str(incoming.get("icon_name") or f"{key}.webp").strip() or f"{key}.webp",
                        "name_i18n": incoming.get("name_i18n") or {"ru": key, "en": key},
                        "description_i18n": incoming.get("description_i18n") or {},
                        "atk_min": max(0, self._to_int(incoming.get("atk_min"), default=0)),
                        "atk_max": max(0, self._to_int(incoming.get("atk_max"), default=0)),
                        "skills_min_i18n": incoming.get("skills_min_i18n") or {},
                        "skills_max_i18n": incoming.get("skills_max_i18n") or {},
                        "skills_full_i18n": incoming.get("skills_full_i18n") or {},
                        "operators_i18n": incoming.get("operators_i18n") or {},
                    }
                    WeaponCatalog.objects.create(**payload_for_create)
                    weapon_created += 1
                    continue

                changed_fields = []
                for field_name, value in incoming.items():
                    if getattr(obj, field_name) != value:
                        setattr(obj, field_name, value)
                        changed_fields.append(field_name)
                if changed_fields:
                    obj.save(update_fields=changed_fields + ["updated_at"])
                    weapon_updated += 1

        reset_translation_cache()
        reset_app_json_cache()
        summary = (
            f"Localization import done. Keys created: {created}, updated: {updated}. "
            f"Addresses created: {address_created}, updated: {address_updated}. "
            f"Game data created: {game_data_created}, updated: {game_data_updated}. "
            f"Weapons created: {weapon_created}, updated: {weapon_updated}."
        )
        self.stdout.write(self.style.SUCCESS(summary))
