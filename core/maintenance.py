"""Maintenance mode helpers shared by middleware and views."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone


MAINTENANCE_CONFIG_KEY = "MAINTENANCE_MODE"
MAINTENANCE_BYPASS_SESSION_KEY = "maintenance_admin_bypass"


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_timestamp_ms(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        raw = int(value)
        if raw <= 0:
            return None
        # 13 digits => milliseconds, 10 digits => seconds.
        return raw if raw >= 10**11 else raw * 1000

    text = str(value or "").strip()
    if not text:
        return None

    if text.isdigit():
        raw = int(text)
        if raw <= 0:
            return None
        return raw if raw >= 10**11 else raw * 1000

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp() * 1000)


def normalize_maintenance_payload(raw_payload):
    """Return normalized maintenance payload from AppJsonConfig."""
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    enabled = _to_bool(payload.get("enabled") if "enabled" in payload else payload.get("is_enabled"))
    if not enabled:
        enabled = _to_bool(payload.get("active"))

    launch_raw = payload.get("launch_at")
    if launch_raw in {None, ""}:
        launch_raw = payload.get("launchAt")
    if launch_raw in {None, ""}:
        launch_raw = payload.get("eta")

    launch_at_ms = _parse_timestamp_ms(launch_raw)
    launch_at_iso = ""
    if launch_at_ms:
        launch_at_iso = datetime.fromtimestamp(launch_at_ms / 1000, tz=timezone.utc).isoformat()

    return {
        "enabled": bool(enabled),
        "launch_at_ms": launch_at_ms,
        "launch_at_iso": launch_at_iso,
        "message": str(payload.get("message") or "").strip(),
    }


def is_maintenance_expired(payload, now_ms: int | None = None) -> bool:
    """Check if maintenance countdown already passed."""
    value = payload if isinstance(payload, dict) else {}
    if not value.get("enabled"):
        return False
    launch_at_ms = value.get("launch_at_ms")
    if not isinstance(launch_at_ms, int) or launch_at_ms <= 0:
        return False
    if now_ms is None:
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return launch_at_ms <= int(now_ms)


def disable_maintenance_mode_in_db() -> bool:
    """Persist maintenance enabled=false in AppJsonConfig."""
    try:
        from django.apps import apps
        from .config_store import reset_app_json_cache

        if not apps.ready:
            return False
        model = apps.get_model("core", "AppJsonConfig")
        row = model.objects.filter(key=MAINTENANCE_CONFIG_KEY).first()
        if row is None:
            return False

        payload = row.payload if isinstance(row.payload, dict) else {}
        if not payload:
            payload = {"enabled": False}
        else:
            payload = dict(payload)
            payload["enabled"] = False
            payload["active"] = False

        row.payload = payload
        row.save(update_fields=["payload"])
        reset_app_json_cache()
        return True
    except Exception:
        return False


def has_admin_bypass_session(request) -> bool:
    """Check maintenance bypass flag in current Django session."""
    if request is None:
        return False
    if not hasattr(request, "session"):
        return False
    return bool(request.session.get(MAINTENANCE_BYPASS_SESSION_KEY))


def _maintenance_copy(language: str | None):
    normalized = str(language or "").strip().lower()
    if normalized.startswith("ru"):
        return {
            "lang": "ru",
            "title": "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b",
            "badge": "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b",
            "headline": "\u0418\u0434\u0443\u0442 \u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b",
            "subtitle": "\u041c\u044b \u043e\u0431\u043d\u043e\u0432\u043b\u044f\u0435\u043c \u0441\u0435\u0440\u0432\u0438\u0441. \u0421\u043a\u043e\u0440\u043e \u0432\u0435\u0440\u043d\u0435\u043c\u0441\u044f \u0432 \u043e\u043d\u043b\u0430\u0439\u043d.",
            "launch": "\u0412\u0440\u0435\u043c\u044f \u0434\u043e \u0437\u0430\u043f\u0443\u0441\u043a\u0430",
            "unknown": "\u0422\u043e\u0447\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f \u0437\u0430\u043f\u0443\u0441\u043a\u0430 \u0441\u043a\u043e\u0440\u043e \u043f\u043e\u044f\u0432\u0438\u0442\u0441\u044f.",
            "days": "\u0434\u043d\u0438",
            "hours": "\u0447\u0430\u0441\u044b",
            "minutes": "\u043c\u0438\u043d\u0443\u0442\u044b",
            "seconds": "\u0441\u0435\u043a\u0443\u043d\u0434\u044b",
            "support": "\u041d\u0443\u0436\u043d\u0430 \u043f\u043e\u043c\u043e\u0449\u044c? support@endfieldpass.site",
        }
    return {
        "lang": "en",
        "title": "Maintenance",
        "badge": "Maintenance",
        "headline": "Maintenance in progress",
        "subtitle": "We are updating the service and will be back online soon.",
        "launch": "Time until launch",
        "unknown": "Launch time will be published soon.",
        "days": "days",
        "hours": "hours",
        "minutes": "minutes",
        "seconds": "seconds",
        "support": "Need help? support@endfieldpass.site",
    }


def build_hard_maintenance_html(
    *,
    language: str | None,
    launch_at_ms: int | None,
    message: str = "",
    next_url: str = "/",
    bypass_url: str = "/maintenance/bypass",
) -> str:
    """Build standalone maintenance page independent from templates/static files."""
    texts = _maintenance_copy(language)
    message_text = str(message or "").strip() or texts["subtitle"]
    safe_message = html.escape(message_text)
    safe_title = html.escape(texts["title"])
    safe_badge = html.escape(texts["badge"])
    safe_headline = html.escape(texts["headline"])
    safe_launch = html.escape(texts["launch"])
    safe_unknown = html.escape(texts["unknown"])
    safe_days = html.escape(texts["days"])
    safe_hours = html.escape(texts["hours"])
    safe_minutes = html.escape(texts["minutes"])
    safe_seconds = html.escape(texts["seconds"])
    safe_support = html.escape(texts["support"])
    safe_next_url = json.dumps(str(next_url or "/"))
    safe_bypass_url = json.dumps(str(bypass_url or "/maintenance/bypass"))
    launch_value = int(launch_at_ms or 0)

    return f"""<!DOCTYPE html>
<html lang="{html.escape(str(texts.get("lang") or "en"))}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} | EndfieldPass</title>
  <style>
    :root {{ color-scheme: dark; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Inter, Segoe UI, Tahoma, sans-serif;
      background: radial-gradient(circle at top, #30384f 0%, #141723 60%, #0b0d16 100%);
      color: #e9ecf7;
      display: grid;
      place-items: center;
      padding: 24px;
    }}
    .card {{
      width: min(760px, 100%);
      border: 1px solid rgba(255, 255, 255, 0.16);
      border-radius: 18px;
      background: rgba(18, 21, 34, 0.88);
      box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42);
      padding: clamp(20px, 4vw, 34px);
    }}
    .badge {{
      display: inline-block;
      margin-bottom: 14px;
      padding: 6px 12px;
      border-radius: 999px;
      border: 1px solid rgba(240, 194, 67, 0.45);
      color: #f0c243;
      background: rgba(240, 194, 67, 0.08);
      font-size: 12px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      font-weight: 700;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(24px, 4vw, 36px);
      line-height: 1.12;
    }}
    p {{
      margin: 14px 0 0;
      color: rgba(235, 239, 249, 0.82);
      line-height: 1.45;
      font-size: 16px;
    }}
    .timer-title {{
      margin-top: 24px;
      margin-bottom: 10px;
      color: rgba(236, 240, 249, 0.9);
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .timer-box {{
      display: flex;
      align-items: stretch;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .timer-item {{
      min-width: 106px;
      padding: 12px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.12);
      text-align: center;
    }}
    .timer-value {{
      font-size: clamp(24px, 4.5vw, 32px);
      font-weight: 800;
      color: #ffe393;
      line-height: 1.05;
    }}
    .timer-label {{
      margin-top: 5px;
      font-size: 12px;
      color: rgba(235, 239, 249, 0.72);
      text-transform: uppercase;
    }}
    .hint {{
      margin-top: 22px;
      font-size: 14px;
      color: rgba(235, 239, 249, 0.64);
    }}
  </style>
</head>
<body data-launch-ms="{launch_value}" data-next-url='{html.escape(safe_next_url)}' data-bypass-url='{html.escape(safe_bypass_url)}'>
  <section class="card" aria-live="polite">
    <span class="badge">{safe_badge}</span>
    <h1>{safe_headline}</h1>
    <p>{safe_message}</p>
    <div class="timer-title">{safe_launch}</div>
    <div class="timer-box" id="maintenanceTimerBox">
      <div class="timer-item"><div class="timer-value" id="timerDays">--</div><div class="timer-label">{safe_days}</div></div>
      <div class="timer-item"><div class="timer-value" id="timerHours">--</div><div class="timer-label">{safe_hours}</div></div>
      <div class="timer-item"><div class="timer-value" id="timerMinutes">--</div><div class="timer-label">{safe_minutes}</div></div>
      <div class="timer-item"><div class="timer-value" id="timerSeconds">--</div><div class="timer-label">{safe_seconds}</div></div>
    </div>
    <p id="maintenanceFallback" hidden>{safe_unknown}</p>
    <p class="hint">{safe_support}</p>
  </section>
  <script>
  (() => {{
    const root = document.body;
    const launchAtMs = Number(root.dataset.launchMs || 0);
    const nextUrl = JSON.parse(root.dataset.nextUrl || '"/"');
    const bypassUrl = JSON.parse(root.dataset.bypassUrl || '"/maintenance/bypass"');
    let syncInFlight = false;
    let lastSyncAt = 0;
    const fallback = document.getElementById("maintenanceFallback");
    const ids = {{
      days: document.getElementById("timerDays"),
      hours: document.getElementById("timerHours"),
      minutes: document.getElementById("timerMinutes"),
      seconds: document.getElementById("timerSeconds"),
    }};
    const isTruthy = (value) => {{
      const normalized = String(value || "").trim().toLowerCase();
      return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
    }};
    const hasAdminLocalStorage = () => {{
      try {{ return isTruthy(localStorage.getItem("admin")); }}
      catch (_) {{ return false; }}
    }};
    const resolveNextTarget = () => {{
      const normalizedNext = String(nextUrl || "").trim();
      if (normalizedNext && normalizedNext !== "/maintenance" && normalizedNext !== "/maintenance/") return normalizedNext;
      return "/";
    }};
    const syncDisabledState = async (force = false) => {{
      if (!window.fetch) return;
      const now = Date.now();
      if (!force) {{
        if (syncInFlight) return;
        if ((now - lastSyncAt) < 2500) return;
      }}
      syncInFlight = true;
      lastSyncAt = now;
      try {{
        const separator = bypassUrl.includes("?") ? "&" : "?";
        const target = `${{bypassUrl}}${{separator}}json=1&enable=0&next=${{encodeURIComponent("/maintenance/")}}`;
        const response = await fetch(target, {{ cache: "no-store", headers: {{ "X-Requested-With": "XMLHttpRequest" }} }});
        if (!response.ok) return;
        const payload = await response.json();
        if (payload && payload.maintenance_enabled === false) {{
          window.location.replace(resolveNextTarget());
        }}
      }} catch (_) {{
      }} finally {{
        syncInFlight = false;
      }}
    }};
    const maybeBypassMaintenance = () => {{
      if (!hasAdminLocalStorage()) {{
        syncDisabledState(false).catch(() => {{}});
        return;
      }}
      const targetNext = resolveNextTarget();
      const separator = bypassUrl.includes("?") ? "&" : "?";
      const target = `${{bypassUrl}}${{separator}}enable=1&next=${{encodeURIComponent(targetNext)}}`;
      window.location.replace(target);
    }};
    const pad = (value) => String(Math.max(0, Number(value) || 0)).padStart(2, "0");
    const renderCountdown = () => {{
      if (!launchAtMs || launchAtMs <= 0) {{
        if (fallback) fallback.hidden = false;
        return;
      }}
      const diff = Math.max(0, launchAtMs - Date.now());
      const totalSec = Math.floor(diff / 1000);
      ids.days.textContent = pad(Math.floor(totalSec / 86400));
      ids.hours.textContent = pad(Math.floor((totalSec % 86400) / 3600));
      ids.minutes.textContent = pad(Math.floor((totalSec % 3600) / 60));
      ids.seconds.textContent = pad(totalSec % 60);
    }};
    maybeBypassMaintenance();
    renderCountdown();
    window.setInterval(() => {{
      maybeBypassMaintenance();
      renderCountdown();
    }}, 1000);
    window.setInterval(() => {{
      if (!hasAdminLocalStorage()) syncDisabledState(false).catch(() => {{}});
    }}, 4500);
  }})();
  </script>
</body>
</html>"""

