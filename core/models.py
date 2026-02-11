import re

from django.core.exceptions import ValidationError
from django.db import models


class ImportSession(models.Model):
    """One import operation with source params and final status."""

    created_at = models.DateTimeField(auto_now_add=True)
    page_url = models.TextField()
    token = models.TextField()
    server_id = models.CharField(max_length=16)
    lang = models.CharField(max_length=32, default="ru-ru")
    status = models.CharField(max_length=16, default="new")
    error = models.TextField(blank=True, default="")


class Pull(models.Model):
    """Single pull entry captured during an import session."""

    session = models.ForeignKey(
        ImportSession,
        on_delete=models.CASCADE,
        related_name="pulls",
    )
    pool_id = models.CharField(max_length=64, db_index=True)
    pool_name = models.CharField(max_length=128, blank=True, default="")
    char_id = models.CharField(max_length=64, blank=True, default="")
    char_name = models.CharField(max_length=128, blank=True, default="")
    rarity = models.IntegerField()
    is_free = models.BooleanField(default=False)
    is_new = models.BooleanField(default=False)
    gacha_ts = models.BigIntegerField(null=True, blank=True)
    seq_id = models.IntegerField(db_index=True)
    source_pool_type = models.CharField(max_length=64, blank=True, default="")
    raw = models.JSONField(default=dict)


class StaticCharacter(models.Model):
    """Manual character catalog with static asset binding managed in admin."""

    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=128)
    aliases = models.TextField(blank=True, default="")
    static_icon_path = models.CharField(
        max_length=255,
        help_text="Path in static/, e.g. img/characters/ember.png",
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        super().clean()
        icon_path = str(self.static_icon_path or "").replace("\\", "/").strip()
        if not icon_path:
            raise ValidationError({"static_icon_path": "Static icon path is required."})
        if icon_path.startswith("/"):
            raise ValidationError({"static_icon_path": "Use a path relative to static/ (without leading slash)."})
        self.static_icon_path = icon_path

    @property
    def alias_list(self):
        values = [self.name, self.code]
        values.extend(re.split(r"[,;\n|]+", str(self.aliases or "")))
        unique = []
        seen = set()
        for value in values:
            candidate = str(value or "").strip()
            if not candidate:
                continue
            normalized = candidate.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(candidate)
        return unique


class Banner(models.Model):
    """Manual banner metadata used for dashboard banner statistics."""

    name = models.CharField(max_length=128)
    pool_id = models.CharField(max_length=64, unique=True, db_index=True)
    is_active = models.BooleanField(default=False, db_index=True)
    top_character = models.ForeignKey(
        StaticCharacter,
        on_delete=models.PROTECT,
        related_name="top_for_banners",
    )
    six_star_characters = models.ManyToManyField(
        StaticCharacter,
        related_name="banners",
        blank=True,
    )
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ("-start_date", "pool_id")

    def __str__(self):
        return f"{self.name} ({self.pool_id})"

    def clean(self):
        super().clean()
        value = str(self.pool_id or "").strip()
        if not value:
            raise ValidationError({"pool_id": "Pool id is required."})
        match = re.fullmatch(r"special_(\d+)_(\d+)_(\d+)", value)
        if not match:
            raise ValidationError({"pool_id": "Expected format: special_1_<version_minor>_<number> (for example: special_1_0_3)."})
        self.pool_id = value
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date must be greater than or equal to start date."})
        if self.is_active:
            major = str(match.group(1) or "")
            minor = str(match.group(2) or "")
            conflicts = Banner.objects.filter(is_active=True)
            if self.pk:
                conflicts = conflicts.exclude(pk=self.pk)
            for banner in conflicts.only("pool_id"):
                other = re.fullmatch(r"special_(\d+)_(\d+)_(\d+)", str(banner.pool_id or ""))
                if not other:
                    continue
                if str(other.group(1)) == major and str(other.group(2)) == minor:
                    raise ValidationError({"is_active": "Only one active banner is allowed per version."})


class VersionTopStatsSnapshot(models.Model):
    """Server-side top-character stats for one imported session and one version."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source_session_id = models.IntegerField(db_index=True)
    version_major = models.PositiveIntegerField(default=0, db_index=True)
    version_minor = models.PositiveIntegerField(default=0, db_index=True)
    version_label = models.CharField(max_length=32, db_index=True)
    tracked_characters_count = models.PositiveIntegerField(default=0)
    total_top_drops = models.PositiveIntegerField(default=0)
    stats = models.JSONField(default=list)

    class Meta:
        ordering = ("-version_major", "-version_minor", "-created_at", "-id")

    def __str__(self):
        return f"Version {self.version_label} / session {self.source_session_id}"


class WeaponCatalog(models.Model):
    """Static weapon catalog with localized fields used by weapons page and modal."""

    TYPE_SHORT = "short"
    TYPE_GREAT = "great"
    TYPE_GUNS = "guns"
    TYPE_POLEARMS = "polearms"
    TYPE_ORBITERS = "orbiters"

    WEAPON_TYPE_CHOICES = (
        (TYPE_SHORT, "Sword"),
        (TYPE_GREAT, "Great Sword"),
        (TYPE_GUNS, "Hand Cannon"),
        (TYPE_POLEARMS, "Polearm"),
        (TYPE_ORBITERS, "Arts Device"),
    )

    key = models.CharField(max_length=128, unique=True, db_index=True)
    rarity = models.PositiveSmallIntegerField(default=4, db_index=True)
    weapon_type = models.CharField(
        max_length=16,
        choices=WEAPON_TYPE_CHOICES,
        default=TYPE_SHORT,
        db_index=True,
    )
    icon_name = models.CharField(max_length=255)
    name_i18n = models.JSONField(default=dict, blank=True)
    description_i18n = models.JSONField(default=dict, blank=True)
    atk_min = models.PositiveIntegerField(default=0)
    atk_max = models.PositiveIntegerField(default=0)
    skills_min_i18n = models.JSONField(default=dict, blank=True)
    skills_max_i18n = models.JSONField(default=dict, blank=True)
    skills_full_i18n = models.JSONField(default=dict, blank=True)
    operators_i18n = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-rarity", "key")

    def __str__(self):
        names = self.name_i18n or {}
        return str(names.get("ru") or names.get("en") or self.key)


class LocalizationEntry(models.Model):
    """DB-backed localization entry: one key with language -> text JSON map."""

    key = models.CharField(max_length=190, unique=True, db_index=True)
    translations = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self):
        return self.key


class AppAddress(models.Model):
    """Runtime-editable public addresses (links) used in templates/views."""

    key = models.CharField(max_length=80, unique=True, db_index=True)
    value = models.CharField(max_length=500, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self):
        return f"{self.key}={self.value}"


class AppJsonConfig(models.Model):
    """Runtime-editable JSON config blobs keyed by constant-like names."""

    key = models.CharField(max_length=80, unique=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self):
        return self.key
