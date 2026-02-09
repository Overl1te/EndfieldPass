from django.contrib import admin

from .models import ImportSession, Pull


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
