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
