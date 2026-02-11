import re
from pathlib import Path

from django.core.management.base import BaseCommand

from core.models import StaticCharacter
from core.views import _runtime_character_official_names, _runtime_characters


def _build_code(icon_name):
    stem = Path(str(icon_name or "")).stem.strip().lower()
    if not stem:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_")


def _collect_aliases(character):
    icon = str(character.get("icon") or "").strip()
    official_names = _runtime_character_official_names().get(icon, {})
    values = [
        str(character.get("name") or "").strip(),
        *[str(value or "").strip() for value in (character.get("aliases") or [])],
        *[str(value or "").strip() for value in official_names.values()],
        Path(icon).stem.strip(),
    ]
    unique = []
    seen = set()
    for value in values:
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


class Command(BaseCommand):
    help = "Create/update StaticCharacter records from DB-backed character catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Also update existing rows with current catalog values.",
        )

    def handle(self, *args, **options):
        update_existing = bool(options.get("update_existing"))
        created_count = 0
        updated_count = 0
        skipped_count = 0

        for item in _runtime_characters():
            icon = str(item.get("icon") or "").strip()
            code = _build_code(icon)
            if not code or not icon:
                skipped_count += 1
                continue

            aliases = _collect_aliases(item)
            name_value = str(item.get("name") or "").strip()
            if not name_value:
                name_value = aliases[0] if aliases else code
            defaults = {
                "name": name_value,
                "aliases": ", ".join(aliases),
                "static_icon_path": f"img/characters/{icon}",
            }

            obj, created = StaticCharacter.objects.get_or_create(code=code, defaults=defaults)
            if created:
                created_count += 1
                continue

            if update_existing:
                changed = False
                for field_name, value in defaults.items():
                    if getattr(obj, field_name) != value:
                        setattr(obj, field_name, value)
                        changed = True
                if changed:
                    obj.save(update_fields=["name", "aliases", "static_icon_path"])
                    updated_count += 1

        summary = (
            f"Static characters synced. Created: {created_count}, "
            f"updated: {updated_count}, skipped: {skipped_count}."
        )
        self.stdout.write(self.style.SUCCESS(summary))
