from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import WeaponCatalog
from core.views import _runtime_weapon_official_names


SUPPORTED_LANGS = ("ru", "en", "de", "zh-hans", "ja")

MISSING_NAME_TRANSLATIONS = {
    "Маяк следопыта": {
        "ru": "Маяк следопыта",
        "en": "Pathfinder Beacon",
        "de": "Pfadfinder-Leitfeuer",
        "zh-hans": "寻路者信标",
        "ja": "探路者のビーコン",
    },
    "Прочное притяжение": {
        "ru": "Прочное притяжение",
        "en": "Firm Attraction",
        "de": "Stabile Anziehung",
        "zh-hans": "稳固牵引",
        "ja": "堅牢なる引力",
    },
}

WEAPON_TYPE_OVERRIDES = {
    "Гнев кузни": WeaponCatalog.TYPE_SHORT,
}

WEAPON_TYPE_KEYWORDS = (
    (WeaponCatalog.TYPE_POLEARMS, ("пика", "копь", "ланс")),
    (WeaponCatalog.TYPE_GUNS, ("джимини", "пеко", "тарр", "дархофф", "гипернов", "доставка", "громберг")),
    (WeaponCatalog.TYPE_ORBITERS, ("obj", "идентификатор", "опус", "opus", "модуль", "станс", "химера", "маяк", "флуоресцен", "эталон")),
    (WeaponCatalog.TYPE_GREAT, ("резак", "принц", "скала", "добродетель", "мечта", "хранитель", "растерзан")),
)

DEFAULT_DESCRIPTION_I18N = {
    "ru": "Описание пока не заполнено.",
    "en": "Description is not filled yet.",
    "de": "Beschreibung ist noch nicht ausgefullt.",
    "zh-hans": "描述暂未填写。",
    "ja": "説明はまだ入力されていません。",
}

DEFAULT_SKILLS_MIN_I18N = {
    "ru": [
        "Навык I: заполняется.",
        "Навык II: заполняется.",
        "Навык III: заполняется.",
    ],
    "en": [
        "Skill I: pending.",
        "Skill II: pending.",
        "Skill III: pending.",
    ],
    "de": [
        "Fertigkeit I: folgt.",
        "Fertigkeit II: folgt.",
        "Fertigkeit III: folgt.",
    ],
    "zh-hans": [
        "技能 I：待补充。",
        "技能 II：待补充。",
        "技能 III：待补充。",
    ],
    "ja": [
        "スキル I：追記予定。",
        "スキル II：追記予定。",
        "スキル III：追記予定。",
    ],
}

DEFAULT_SKILLS_MAX_I18N = {
    "ru": [
        "Навык I (макс): заполняется.",
        "Навык II (макс): заполняется.",
        "Навык III (макс): заполняется.",
    ],
    "en": [
        "Skill I (max): pending.",
        "Skill II (max): pending.",
        "Skill III (max): pending.",
    ],
    "de": [
        "Fertigkeit I (max): folgt.",
        "Fertigkeit II (max): folgt.",
        "Fertigkeit III (max): folgt.",
    ],
    "zh-hans": [
        "技能 I（最大）：待补充。",
        "技能 II（最大）：待补充。",
        "技能 III（最大）：待补充。",
    ],
    "ja": [
        "スキル I（最大）：追記予定。",
        "スキル II（最大）：追記予定。",
        "スキル III（最大）：追記予定。",
    ],
}

DEFAULT_SKILLS_FULL_I18N = {
    "ru": [
        "Навык I (фулл эссенции): заполняется.",
        "Навык II (фулл эссенции): заполняется.",
        "Навык III (фулл эссенции): заполняется.",
    ],
    "en": [
        "Skill I (full essence): pending.",
        "Skill II (full essence): pending.",
        "Skill III (full essence): pending.",
    ],
    "de": [
        "Fertigkeit I (volle Essenz): folgt.",
        "Fertigkeit II (volle Essenz): folgt.",
        "Fertigkeit III (volle Essenz): folgt.",
    ],
    "zh-hans": [
        "技能 I（满精华）：待补充。",
        "技能 II（满精华）：待补充。",
        "技能 III（满精华）：待补充。",
    ],
    "ja": [
        "スキル I（フルエッセンス）：追記予定。",
        "スキル II（フルエッセンス）：追記予定。",
        "スキル III（フルエッセンス）：追記予定。",
    ],
}

DEFAULT_OPERATORS_I18N = {
    "ru": ["Подбор оператора заполняется."],
    "en": ["Operator compatibility is pending."],
    "de": ["Operatoren-Kompatibilitat folgt."],
    "zh-hans": ["适配干员待补充。"],
    "ja": ["適性オペレーターは追記予定。"],
}

SPECIAL_WEAPON_DETAILS = {
    "Гнев кузни": {
        "weapon_type": WeaponCatalog.TYPE_SHORT,
        "description_i18n": {
            "ru": (
                "Острый меч от «Колдовского часа». Особые методы плавки придали клинку красный цвет. "
                "Модуль искусств представляет собой жидкий ориджиний, напоминающий первую кровь, "
                "пролитую на ледниках."
            ),
            "en": (
                "A sharp blade from \"Witching Hour\". Special smelting techniques gave the weapon a crimson hue. "
                "Its Arts module is liquid Originium, like the first blood spilled on the glaciers."
            ),
            "de": (
                "Eine scharfe Klinge aus der \"Hexenstunde\". Besondere Schmelzmethoden verliehen ihr eine rote Farbe. "
                "Das Arts-Modul besteht aus fluessigem Originium."
            ),
            "zh-hans": (
                "来自“魔女时刻”的锋利长剑。特殊熔炼工艺让剑身呈现赤红色，术式模块为液态源石。"
            ),
            "ja": (
                "「魔女の刻」製の鋭い剣。特別な鍛造で刃は赤く染まり、術式モジュールは液体オリジニウムで構成される。"
            ),
        },
        "atk_min": 52,
        "atk_max": 510,
        "skills_min_i18n": {
            "ru": [
                "Увелич. интеллекта [бол.] +20 к интеллекту.",
                "Увелич. атаки [бол.] +5%.",
                "Сумерки: пламенеющий вопль: +16% к наносимому тепловому УРН. После супернавыка +75% к урону базовой атаки на 20 сек.",
            ],
            "en": [
                "Mind bonus [major]: +20 INT.",
                "ATK bonus [major]: +5%.",
                "Twilight: Blazing Howl: +16% Heat DMG dealt. After using Ultimate, +75% basic attack DMG for 20s.",
            ],
        },
        "skills_max_i18n": {
            "ru": [
                "Увелич. интеллекта [бол.] +52 к интеллекту.",
                "Увелич. атаки [бол.] +13%.",
                "Сумерки: пламенеющий вопль: +32% к наносимому тепловому УРН. После супернавыка +150% к урону базовой атаки на 20 сек.",
            ],
            "en": [
                "Mind bonus [major]: +52 INT.",
                "ATK bonus [major]: +13%.",
                "Twilight: Blazing Howl: +32% Heat DMG dealt. After using Ultimate, +150% basic attack DMG for 20s.",
            ],
        },
        "skills_full_i18n": {
            "ru": [
                "Увелич. интеллекта [бол.] +156 к интеллекту.",
                "Увелич. атаки [бол.] +39%.",
                "Сумерки: пламенеющий вопль: +44.8% к наносимому тепловому УРН. После супернавыка +210% к урону базовой атаки на 20 сек.",
            ],
            "en": [
                "Mind bonus [major]: +156 INT.",
                "ATK bonus [major]: +39%.",
                "Twilight: Blazing Howl: +44.8% Heat DMG dealt. After using Ultimate, +210% basic attack DMG for 20s.",
            ],
        },
        "operators_i18n": {
            "ru": ["Лэватейн"],
            "en": ["Laevatain"],
            "de": ["Laevatain"],
            "zh-hans": ["莱瓦汀"],
            "ja": ["レーヴァテイン"],
        },
    },
}


def _normalize_i18n_map(raw_map, fallback):
    payload = {}
    for lang in SUPPORTED_LANGS:
        payload[lang] = raw_map.get(lang) or raw_map.get("en") or raw_map.get("ru") or fallback
    return payload


def _build_name_i18n(weapon_key):
    source = dict(_runtime_weapon_official_names().get(weapon_key) or MISSING_NAME_TRANSLATIONS.get(weapon_key) or {})
    if not source:
        source = {"ru": weapon_key, "en": weapon_key}
    return _normalize_i18n_map(source, weapon_key)


def _guess_weapon_type(weapon_key):
    if weapon_key in WEAPON_TYPE_OVERRIDES:
        return WEAPON_TYPE_OVERRIDES[weapon_key]
    lower = str(weapon_key or "").strip().lower()
    for type_code, keywords in WEAPON_TYPE_KEYWORDS:
        if any(keyword in lower for keyword in keywords):
            return type_code
    return WeaponCatalog.TYPE_SHORT


class Command(BaseCommand):
    help = "Create/update WeaponCatalog rows from static icons and in-code translations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Also update existing rows with current generated values.",
        )

    def handle(self, *args, **options):
        update_existing = bool(options.get("update_existing"))
        weapons_root = Path(settings.BASE_DIR) / "static" / "img" / "weapons"
        if not weapons_root.exists():
            self.stdout.write(self.style.ERROR("Weapons folder not found: static/img/weapons"))
            return

        supported_ext = {".webp", ".png", ".jpg", ".jpeg", ".avif"}
        created_count = 0
        updated_count = 0
        skipped_count = 0

        for rarity_dir in weapons_root.iterdir():
            if not rarity_dir.is_dir():
                continue
            rarity_name = str(rarity_dir.name).strip()
            if not rarity_name.isdigit():
                continue
            rarity = int(rarity_name)
            for icon_path in rarity_dir.iterdir():
                if not icon_path.is_file() or icon_path.suffix.lower() not in supported_ext:
                    continue

                weapon_key = str(icon_path.stem).strip()
                if not weapon_key:
                    skipped_count += 1
                    continue

                defaults = {
                    "rarity": rarity,
                    "icon_name": icon_path.name,
                    "weapon_type": _guess_weapon_type(weapon_key),
                    "name_i18n": _build_name_i18n(weapon_key),
                    "description_i18n": dict(DEFAULT_DESCRIPTION_I18N),
                    "atk_min": 0,
                    "atk_max": 0,
                    "skills_min_i18n": dict(DEFAULT_SKILLS_MIN_I18N),
                    "skills_max_i18n": dict(DEFAULT_SKILLS_MAX_I18N),
                    "skills_full_i18n": dict(DEFAULT_SKILLS_FULL_I18N),
                    "operators_i18n": dict(DEFAULT_OPERATORS_I18N),
                }
                special = SPECIAL_WEAPON_DETAILS.get(weapon_key)
                if special:
                    defaults.update(special)
                    defaults["weapon_type"] = special.get("weapon_type") or defaults["weapon_type"]

                obj, created = WeaponCatalog.objects.get_or_create(key=weapon_key, defaults=defaults)
                if created:
                    created_count += 1
                    continue

                if not update_existing:
                    continue

                changed = False
                for field_name, value in defaults.items():
                    if getattr(obj, field_name) != value:
                        setattr(obj, field_name, value)
                        changed = True
                if changed:
                    obj.save(update_fields=list(defaults.keys()) + ["updated_at"])
                    updated_count += 1

        summary = (
            f"Weapon catalog synced. Created: {created_count}, "
            f"updated: {updated_count}, skipped: {skipped_count}."
        )
        self.stdout.write(self.style.SUCCESS(summary))
