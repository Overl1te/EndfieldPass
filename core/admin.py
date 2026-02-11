import re

from django import forms
from django.contrib import admin

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


@admin.register(ImportSession)
class ImportSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "server_id", "lang", "status")
    search_fields = ("server_id", "token")
    list_filter = ("status", "lang")


@admin.register(Pull)
class PullAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "pool_id", "char_name", "rarity", "seq_id")
    search_fields = ("pool_id", "pool_name", "char_id", "char_name")
    list_filter = ("rarity", "is_free", "is_new", "source_pool_type")


@admin.register(StaticCharacter)
class StaticCharacterAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code", "static_icon_path")
    search_fields = ("name", "code", "aliases", "static_icon_path")


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "pool_id", "is_active", "top_character", "start_date", "end_date")
    search_fields = ("name", "pool_id", "top_character__name", "top_character__code")
    list_filter = ("is_active", "start_date", "end_date")
    list_editable = ("is_active",)
    filter_horizontal = ("six_star_characters",)


@admin.register(VersionTopStatsSnapshot)
class VersionTopStatsSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "version_label",
        "tracked_characters_count",
        "total_top_drops",
        "source_session_id",
    )
    search_fields = ("version_label", "source_session_id")
    list_filter = ("version_label", "version_major", "version_minor")


@admin.register(LocalizationEntry)
class LocalizationEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "updated_at")
    search_fields = ("key",)


@admin.register(AppAddress)
class AppAddressAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "value", "updated_at")
    search_fields = ("key", "value")


@admin.register(AppJsonConfig)
class AppJsonConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "updated_at")
    search_fields = ("key",)


@admin.register(WeaponCatalog)
class WeaponCatalogAdmin(admin.ModelAdmin):
    class WeaponCatalogAdminForm(forms.ModelForm):
        LANGUAGES = (
            ("ru", "RU"),
            ("en", "EN"),
            ("de", "DE"),
            ("zh-hans", "ZH-Hans"),
            ("ja", "JA"),
        )
        SKILL_TIERS = (
            ("min", "Min"),
            ("max", "Max"),
            ("full", "Max+Ess"),
        )

        for _lang, _lang_label in LANGUAGES:
            _slug = str(_lang).replace("-", "_")
            locals()[f"name_{_slug}"] = forms.CharField(required=False, label=f"Name ({_lang_label})")
            locals()[f"description_{_slug}"] = forms.CharField(
                required=False,
                label=f"Description ({_lang_label})",
                widget=forms.Textarea(attrs={"rows": 4}),
            )
            locals()[f"operators_{_slug}"] = forms.CharField(
                required=False,
                label=f"Operators ({_lang_label})",
                help_text="One operator per line (or separate by comma/semicolon).",
                widget=forms.Textarea(attrs={"rows": 3}),
            )
            for _tier, _tier_label in SKILL_TIERS:
                for _index in range(1, 4):
                    locals()[f"skills_{_tier}_{_slug}_{_index}"] = forms.CharField(
                        required=False,
                        label=f"{_tier_label} skill #{_index} ({_lang_label})",
                        widget=forms.Textarea(attrs={"rows": 2}),
                    )
        del _lang, _lang_label, _slug, _tier, _tier_label, _index

        class Meta:
            model = WeaponCatalog
            fields = "__all__"

        @staticmethod
        def _slug(lang):
            return str(lang or "").replace("-", "_").strip().lower()

        @staticmethod
        def _text_i18n_value(payload, lang):
            if not isinstance(payload, dict):
                return ""
            return str(payload.get(lang) or "").strip()

        @staticmethod
        def _list_i18n_value(payload, lang):
            if not isinstance(payload, dict):
                return []
            raw = payload.get(lang)
            if isinstance(raw, (list, tuple)):
                return [str(value or "").strip() for value in raw if str(value or "").strip()]
            if isinstance(raw, str) and raw.strip():
                return [raw.strip()]
            return []

        @staticmethod
        def _set_i18n_text(payload, lang, value):
            base = dict(payload or {})
            text = str(value or "").strip()
            if text:
                base[lang] = text
            else:
                base.pop(lang, None)
            return base

        @staticmethod
        def _set_i18n_list(payload, lang, values):
            base = dict(payload or {})
            normalized = [str(value or "").strip() for value in (values or []) if str(value or "").strip()]
            if normalized:
                base[lang] = normalized
            else:
                base.pop(lang, None)
            return base

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instance = getattr(self, "instance", None)
            if not instance or not instance.pk:
                return

            for lang, _lang_label in self.LANGUAGES:
                slug = self._slug(lang)
                self.fields[f"name_{slug}"].initial = self._text_i18n_value(instance.name_i18n, lang)
                self.fields[f"description_{slug}"].initial = self._text_i18n_value(instance.description_i18n, lang)

                operators = self._list_i18n_value(instance.operators_i18n, lang)
                self.fields[f"operators_{slug}"].initial = "\n".join(operators)

                for tier, _tier_label in self.SKILL_TIERS:
                    values = self._list_i18n_value(getattr(instance, f"skills_{tier}_i18n", {}), lang)
                    for index in range(1, 4):
                        field_name = f"skills_{tier}_{slug}_{index}"
                        self.fields[field_name].initial = values[index - 1] if len(values) >= index else ""

        def save(self, commit=True):
            obj = super().save(commit=False)

            for lang, _lang_label in self.LANGUAGES:
                slug = self._slug(lang)
                obj.name_i18n = self._set_i18n_text(obj.name_i18n, lang, self.cleaned_data.get(f"name_{slug}"))
                obj.description_i18n = self._set_i18n_text(obj.description_i18n, lang, self.cleaned_data.get(f"description_{slug}"))

                operators_raw = str(self.cleaned_data.get(f"operators_{slug}") or "")
                operators = [value.strip() for value in re.split(r"[\n,;]+", operators_raw) if value.strip()]
                obj.operators_i18n = self._set_i18n_list(obj.operators_i18n, lang, operators)

                for tier, _tier_label in self.SKILL_TIERS:
                    values = [
                        self.cleaned_data.get(f"skills_{tier}_{slug}_1"),
                        self.cleaned_data.get(f"skills_{tier}_{slug}_2"),
                        self.cleaned_data.get(f"skills_{tier}_{slug}_3"),
                    ]
                    current = getattr(obj, f"skills_{tier}_i18n", {})
                    setattr(obj, f"skills_{tier}_i18n", self._set_i18n_list(current, lang, values))

            if commit:
                obj.save()
                self.save_m2m()
            return obj

    form = WeaponCatalogAdminForm
    list_display = ("id", "key", "rarity", "weapon_type", "icon_name", "updated_at")
    search_fields = ("key", "icon_name")
    list_filter = ("rarity", "weapon_type")
    readonly_fields = ("created_at", "updated_at")

    @staticmethod
    def _lang_slug(lang):
        return str(lang or "").replace("-", "_").strip().lower()

    def get_fieldsets(self, request, obj=None):
        fieldsets = [
            (
                "Main",
                {
                    "fields": (
                        "key",
                        ("rarity", "weapon_type"),
                        "icon_name",
                        ("atk_min", "atk_max"),
                    ),
                },
            ),
        ]

        for lang, lang_label in self.form.LANGUAGES:
            slug = self._lang_slug(lang)
            classes = () if lang == "ru" else ("collapse",)
            fieldsets.append(
                (
                    f"Quick i18n ({lang_label})",
                    {
                        "classes": classes,
                        "description": "Each skill field is one line. Fill up to 3 per tier.",
                        "fields": (
                            f"name_{slug}",
                            f"description_{slug}",
                            f"operators_{slug}",
                            (f"skills_min_{slug}_1", f"skills_min_{slug}_2", f"skills_min_{slug}_3"),
                            (f"skills_max_{slug}_1", f"skills_max_{slug}_2", f"skills_max_{slug}_3"),
                            (f"skills_full_{slug}_1", f"skills_full_{slug}_2", f"skills_full_{slug}_3"),
                        ),
                    },
                )
            )

        fieldsets.append(
            (
                "Advanced i18n JSON",
                {
                    "classes": ("collapse",),
                    "fields": (
                        "name_i18n",
                        "description_i18n",
                        "skills_min_i18n",
                        "skills_max_i18n",
                        "skills_full_i18n",
                        "operators_i18n",
                        "created_at",
                        "updated_at",
                    ),
                },
            )
        )
        return tuple(fieldsets)
