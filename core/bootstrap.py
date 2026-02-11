"""Application data bootstrap helpers for fresh deployments."""

from __future__ import annotations

import os
import sys
from hashlib import sha1
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone


BOOTSTRAP_STATE_KEY = "SYSTEM_BOOTSTRAP_STATE"
MAINTENANCE_MODE_KEY = "MAINTENANCE_MODE"
MAINTENANCE_DEFAULT_PAYLOAD = {
    "enabled": False,
    "active": False,
    "launch_at": "",
    "message": "",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _is_test_mode() -> bool:
    argv = {str(value or "").strip().lower() for value in sys.argv}
    if "test" in argv:
        return True
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def _print_line(message: str, verbosity: int = 1) -> None:
    if int(verbosity or 0) > 0:
        print(message)


def _default_localization_json_path() -> Path:
    return Path(settings.BASE_DIR) / "special" / "localization" / "localization.json"


def _file_sha1(path: Path) -> str:
    hasher = sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _table_exists(using: str, model) -> bool:
    try:
        table_names = connections[using].introspection.table_names()
    except Exception:
        return False
    return str(model._meta.db_table or "") in set(table_names)


def _load_bootstrap_state(*, using: str) -> dict:
    app_json_model = apps.get_model("core", "AppJsonConfig")
    if not _table_exists(using, app_json_model):
        return {}
    row = (
        app_json_model.objects.using(using)
        .filter(key=BOOTSTRAP_STATE_KEY)
        .values_list("payload", flat=True)
        .first()
    )
    return row if isinstance(row, dict) else {}


def _save_bootstrap_state(*, using: str, payload: dict) -> None:
    app_json_model = apps.get_model("core", "AppJsonConfig")
    if not _table_exists(using, app_json_model):
        return
    app_json_model.objects.using(using).update_or_create(
        key=BOOTSTRAP_STATE_KEY,
        defaults={"payload": payload},
    )


def _ensure_maintenance_config(*, using: str) -> None:
    """Guarantee MAINTENANCE_MODE row exists with safe defaults."""
    app_json_model = apps.get_model("core", "AppJsonConfig")
    if not _table_exists(using, app_json_model):
        return

    row = (
        app_json_model.objects.using(using)
        .filter(key=MAINTENANCE_MODE_KEY)
        .values_list("payload", flat=True)
        .first()
    )
    if row is None:
        app_json_model.objects.using(using).create(
            key=MAINTENANCE_MODE_KEY,
            payload=dict(MAINTENANCE_DEFAULT_PAYLOAD),
        )
        return

    if not isinstance(row, dict):
        app_json_model.objects.using(using).update_or_create(
            key=MAINTENANCE_MODE_KEY,
            defaults={"payload": dict(MAINTENANCE_DEFAULT_PAYLOAD)},
        )
        return

    payload = dict(row)
    changed = False
    if "enabled" not in payload and "active" not in payload:
        payload["enabled"] = False
        payload["active"] = False
        changed = True
    if "launch_at" not in payload and "launchAt" not in payload and "eta" not in payload:
        payload["launch_at"] = ""
        changed = True
    if "message" not in payload:
        payload["message"] = ""
        changed = True
    if changed:
        app_json_model.objects.using(using).filter(key=MAINTENANCE_MODE_KEY).update(payload=payload)


def run_data_bootstrap(
    *,
    using: str = "default",
    force: bool = False,
    verbosity: int = 1,
    source_path: str | Path | None = None,
) -> dict:
    """Import baseline data into DB for fresh instances after migrations."""
    _ensure_maintenance_config(using=using)

    if not _env_bool("ENDFIELDPASS_AUTO_BOOTSTRAP", default=True):
        return {"status": "disabled"}

    if (
        _is_test_mode()
        and not force
        and not _env_bool("ENDFIELDPASS_AUTO_BOOTSTRAP_IN_TESTS", default=False)
    ):
        return {"status": "skipped_in_tests"}

    target_path = Path(source_path) if source_path is not None else _default_localization_json_path()
    if not target_path.exists() or not target_path.is_file():
        _print_line(f"[bootstrap] source JSON not found, skipping: {target_path}", verbosity)
        return {"status": "missing_source", "path": str(target_path)}

    source_hash = _file_sha1(target_path)
    state = _load_bootstrap_state(using=using)
    force_run = bool(force or _env_bool("ENDFIELDPASS_AUTO_BOOTSTRAP_FORCE", default=False))
    if (
        not force_run
        and bool(state.get("ready"))
        and str(state.get("localization_sha1") or "") == source_hash
    ):
        return {"status": "up_to_date", "path": str(target_path), "hash": source_hash}

    _print_line(f"[bootstrap] importing app data from {target_path}", verbosity)
    call_command("import_localization_json", str(target_path), verbosity=max(0, int(verbosity or 0) - 1))

    _print_line("[bootstrap] syncing static characters", verbosity)
    call_command("sync_static_characters", "--update-existing", verbosity=max(0, int(verbosity or 0) - 1))

    # Keep localization.json as source of truth for weapon metadata.
    # Sync command should only create missing rows from static assets,
    # but must not overwrite already imported DB content.
    _print_line("[bootstrap] syncing weapon catalog (create missing only)", verbosity)
    call_command("sync_weapon_catalog", verbosity=max(0, int(verbosity or 0) - 1))

    payload = {
        "ready": True,
        "localization_sha1": source_hash,
        "source_path": str(target_path),
        "bootstrapped_at": timezone.now().isoformat(),
    }
    _save_bootstrap_state(using=using, payload=payload)
    _print_line("[bootstrap] completed", verbosity)
    return {"status": "done", "path": str(target_path), "hash": source_hash}


def bootstrap_after_migrate(sender, app_config, using, verbosity, **kwargs):
    """post_migrate hook: ensure required seed data exists automatically."""
    try:
        run_data_bootstrap(using=using or "default", verbosity=verbosity)
    except (OperationalError, ProgrammingError):
        # Tables may still be unavailable in unusual migration ordering.
        return
