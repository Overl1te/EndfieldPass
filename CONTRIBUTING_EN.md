# Contributing to EndfieldPass

Official website: **https://endfieldpass.site/**

Language versions:
- Russian: [CONTRIBUTING](CONTRIBUTING.md)
- English: [CONTRIBUTING_EN](CONTRIBUTING_EN.md)

## TL;DR in 5 minutes

1. Install dependencies and apply migrations:
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
```
2. Make sure baseline data is auto-bootstrapped (localization, characters, weapons).
3. Run app:
```bash
python manage.py runserver
```
4. Before opening PR, run:
```bash
python manage.py check
python manage.py test
```

If you are on Windows and want fast local setup, use `start.bat`.

## What this project is

EndfieldPass is a Django app with one main `core` app where:
- canonical URLs always include language prefix (`/ru/...`, `/en/...`),
- part of UI/catalog data is DB-driven and can be updated without server restart,
- there are import flows, cloud sync, and maintenance mode,
- required data is auto-imported after migrations.

## Where to change what

If you need to change:
- Pages/endpoints: `core/views.py`, `core/urls.py`, `templates/*`
- Language and localization logic: `core/localization.py`, `core/middleware.py`, `core/context_processors.py`
- DB runtime config reads: `core/config_store.py`, models `AppAddress`/`AppJsonConfig` in `core/models.py` (note: `DONATE_URL`/`OFFICIAL_REPOSITORY_URL` are env-first)
- Maintenance mode behavior: `core/maintenance.py`, `core/middleware.py`, `templates/core/maintenance.html`
- In-memory import session/progress logic: `core/import_runtime.py`, `core/views.py`
- Cloud/OAuth/URL import: `core/cloud.py`, cloud endpoints in `core/views.py`
- Security hardening (XSS/SSRF/headers/input validation): `core/middleware.py`, `core/views.py`, `core/cloud.py`
- Auto-bootstrap after migrations: `core/bootstrap.py`, `core/apps.py`, `core/management/commands/bootstrap_app_data.py`
- DB schema/entities: `core/models.py` + migrations in `core/migrations/*`
- Admin behavior: `core/admin.py`
- Styling: `static/css/*`
- Legal page content: `templates/core/privacy_policy.html`, `templates/core/cookies_policy.html`

## Key module map

`core/views.py`
- Main HTTP/business orchestration layer.
- Page rendering, import API, cloud sync flow, history import/export.
- Does not own low-level import runtime state directly.

`core/import_runtime.py`
- Thread-safe process-local in-memory store for import sessions/progress.

`core/config_store.py`
- DB-backed runtime config access (`AppAddress`, `AppJsonConfig`).
- JSON TTL cache.
- Use `reset_app_json_cache()` when immediate consistency is needed.

`core/localization.py`
- Language normalization and translation fallback logic.
- DB translation cache.

`core/middleware.py`
- `SiteLanguageMiddleware`: enforces `/<lang>/...` URL format.
- `SecurityHeadersMiddleware`: attaches security headers.
- `MaintenanceModeMiddleware`: global maintenance redirect logic.

`core/maintenance.py`
- Maintenance payload normalization.
- Countdown expiration checks.
- Standalone hard-maintenance HTML response (works even if templates/static are broken).

`core/cloud.py`
- OAuth helpers and cloud import/export logic.
- URL-import SSRF protections (private/local network blocking, redirect/content-size limits).

`core/bootstrap.py`
- Post-migrate bootstrap orchestration.
- Idempotency via source sha1 and `SYSTEM_BOOTSTRAP_STATE` in `AppJsonConfig`.

`core/models.py`
- Main entities: import sessions, pulls, banners/stats, weapon catalog, runtime config rows.

## Data flows

### 1) Normal page request
1. Request comes in.
2. `SiteLanguageMiddleware` resolves/normalizes language path.
3. `MaintenanceModeMiddleware` decides whether to redirect to maintenance page.
4. View builds context from DB + runtime state.
5. Template renders localized UI.

### 2) Import flow
1. Client calls `POST /api/import/session`.
2. Server validates input.
3. In-memory session is created in `core/import_runtime.py`.
4. Background worker fetches records via `core/services.py`.
5. Client polls `GET /api/import/<id>/status`.

### 3) Automatic DB bootstrap after migrations
1. `python manage.py migrate` runs.
2. `post_migrate` signal triggers `bootstrap_after_migrate`.
3. Commands run:
- `import_localization_json`
- `sync_static_characters --update-existing`
- `sync_weapon_catalog` (create missing rows only, do not overwrite imported metadata)
4. `SYSTEM_BOOTSTRAP_STATE` is updated in `AppJsonConfig`.

## Database basics for contributors

Important models:
- `ImportSession`, `Pull`
- `StaticCharacter`, `Banner`, `VersionTopStatsSnapshot`
- `WeaponCatalog`
- `LocalizationEntry`
- `AppAddress` (runtime/fallback links and addresses)
- `AppJsonConfig`

Rule:
- If you change `models.py`, create migration and verify it works on a clean DB.

## Localization workflow

1. Add translation key in `core/localization.py`.
2. Use that key in template/view.
3. If runtime override is expected, verify behavior via `LocalizationEntry`.
4. At minimum validate `ru` and `en` rendering.

Important:
- Do not inject raw user/external HTML into templates/JS.
- For backend-to-JS data use `json_script` or explicit escaping.

## Maintenance mode

Controlled by `AppJsonConfig` key `MAINTENANCE_MODE`.

Example payload:
```json
{
  "enabled": true,
  "launch_at": "2026-02-12T18:00:00+03:00",
  "message": "Maintenance is in progress. We are updating the service."
}
```

Fields:
- `enabled`: global maintenance switch.
- `launch_at`: ISO / unix seconds / unix milliseconds.
- `message`: custom maintenance page text.

Developer bypass:
```js
localStorage.setItem("admin", "true");
```
Disable bypass:
```js
localStorage.removeItem("admin");
```

## Security rules for PRs

Already present in project:
- ORM-based data access for request input.
- API payload validation + size limits.
- URL-import SSRF protection.
- Security headers via middleware.

When adding/changing code:
- Do not use `innerHTML` with unescaped external/user strings.
- Do not disable CSRF unless architecture explicitly requires it.
- Do not accept arbitrary URLs without scheme/host/size validation.
- Every new endpoint must validate input explicitly.

## Deploy and hosting checklist

Base pipeline:
1. `pip install -r requirements.txt`
2. `cp .env.example .env` and fill required values
3. `python manage.py check`
4. `python manage.py migrate`
5. Verify bootstrap completed (or run `python manage.py bootstrap_app_data` manually)
6. `python manage.py collectstatic --noinput` for production
7. Start WSGI/ASGI process

Minimum environment variables:
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS` (for production behind a domain/proxy)
- Optional for cloud sync:
- `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`
- `YANDEX_OAUTH_CLIENT_ID`, `YANDEX_OAUTH_CLIENT_SECRET`
- Optional for Cloudflare Turnstile:
- `TURNSTILE_ENABLED`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`
- Optional advanced Turnstile:
- `TURNSTILE_VERIFY_URL`, `TURNSTILE_TIMEOUT_SECONDS`

Links source of truth:
- `DONATE_URL` and `OFFICIAL_REPOSITORY_URL` come from `.env`/settings first.
- DB `AppAddress` values are used only as fallback when corresponding env value is empty.

Turnstile local-dev note:
- Keep `TURNSTILE_ENABLED=0` on localhost if Cloudflare endpoints are blocked in your network.
- For local testing with enabled Turnstile, use Cloudflare test keys.

## Pre-PR checklist

Required:
- `python manage.py check`
- `python manage.py test`
- If security/validation changed, add negative-case tests.

For UI changes:
- Provide before/after screenshots.
- Verify desktop and mobile behavior.

For DB changes:
- Verify fresh install path (`migrate` on empty DB).
- Verify bootstrap remains idempotent.

## Frequent issues and quick fixes

Issue: "Changed DB config but UI still shows old values"
- Cause: `AppJsonConfig` cache.
- Fix: use `use_cache=False` where immediate reads are required or call `reset_app_json_cache()`.

Issue: "Import progress does not move"
- Verify `/api/import/session` creates a session.
- Verify `/api/import/<id>/status` responses.
- Remember progress store is process-local in-memory state.

Issue: "After deploy localization/catalog are empty"
- Run `python manage.py bootstrap_app_data --force`.
- Verify `special/localization/localization.json` exists.

Issue: "Contributor docs text is broken/garbled"
- Open file as UTF-8.
- Do not save contributor files as ANSI.

## Issue and PR format

Issue (bug):
- reproduction steps,
- expected result,
- actual result,
- logs/screenshots,
- environment.

PR:
- what changed,
- why changed,
- how tested,
- remaining risks.

## Do not do this

- Do not commit secrets (`.env`, tokens, OAuth credentials).
- Do not combine unrelated large refactors and features without clear reason.
- Do not submit opaque "magic" changes without explanation.

## Useful commands

```bash
python manage.py check
python manage.py test
python manage.py migrate
python manage.py bootstrap_app_data
python manage.py bootstrap_app_data --force
python manage.py import_localization_json special/localization/localization.json
python manage.py sync_static_characters --update-existing
python manage.py sync_weapon_catalog
```

## Contacts

Support: `support@endfieldpass.site`

Disclaimer:
- EndfieldPass is not affiliated with GRYPHLINE.
- Arknights: Endfield and related content/materials are trademarks and property of GRYPHLINE.
