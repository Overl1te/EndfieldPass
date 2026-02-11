# Контрибьютинг в EndfieldPass

Официальный сайт: **https://endfieldpass.site/**

Языковые версии:
- Русская: [CONTRIBUTING](CONTRIBUTING.md)
- English: [CONTRIBUTING_EN](CONTRIBUTING_EN.md)

## TL;DR за 5 минут

1. Установи зависимости и примени миграции:
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
```
2. Убедись, что базовые данные подхватились автоматически (локализация, персонажи, оружие).
3. Запусти проект:
```bash
python manage.py runserver
```
4. Перед PR обязательно:
```bash
python manage.py check
python manage.py test
```

Если нужно быстро поднять проект на Windows, используй `start.bat`.

## Что это за проект (очень коротко)

EndfieldPass — Django-приложение с одним core-приложением, где:
- интерфейс всегда живет на URL с префиксом языка (`/ru/...`, `/en/...`),
- данные интерфейса и каталогов частично лежат в БД и могут обновляться без перезапуска,
- есть импорт истории, облачная синхронизация и режим техработ,
- есть автоинициализация данных после миграций.

## Куда идти, если хочешь изменить что-то конкретное

Если ты меняешь:
- Страницы/эндпоинты: `core/views.py`, `core/urls.py`, `templates/*`
- Логику языков и переводов: `core/localization.py`, `core/middleware.py`, `core/context_processors.py`
- Данные из БД-конфига: `core/config_store.py`, модели `AppAddress`/`AppJsonConfig` в `core/models.py` (важно: `DONATE_URL`/`OFFICIAL_REPOSITORY_URL` имеют приоритет из env)
- Режим техработ: `core/maintenance.py`, `core/middleware.py`, `templates/core/maintenance.html`
- Импорт прогресса/сессии в памяти: `core/import_runtime.py`, `core/views.py`
- Cloud/OAuth/URL-import: `core/cloud.py`, cloud-эндпоинты в `core/views.py`
- Защиту (XSS/SSRF/headers/валидацию): `core/middleware.py`, `core/views.py`, `core/cloud.py`
- Bootstrap данных после миграций: `core/bootstrap.py`, `core/apps.py`, `core/management/commands/bootstrap_app_data.py`
- Модели/схему БД: `core/models.py` + миграции `core/migrations/*`
- Админку: `core/admin.py`
- Стили: `static/css/*`
- Контент legal-страниц: `templates/core/privacy_policy.html`, `templates/core/cookies_policy.html`

## Карта ключевых модулей

`core/views.py`
- Главный роутер бизнес-логики HTTP.
- Здесь рендер страниц, API импорта, cloud-flow, экспорт/импорт истории.
- Важно: не хранит runtime-состояние импорта в глобалах напрямую, использует `core/import_runtime.py`.

`core/import_runtime.py`
- Потокобезопасный in-memory store для импорт-сессий и прогресса.
- Это process-local состояние (после рестарта процесса очищается).

`core/config_store.py`
- Читает runtime-значения из БД (таблицы `AppAddress`, `AppJsonConfig`).
- Кеширует JSON-конфиги с TTL.
- После изменения конфигов в БД обычно нужен `reset_app_json_cache()` в коде.

`core/localization.py`
- Нормализация кода языка.
- Выбор перевода с fallback.
- Кеш DB-переводов.

`core/middleware.py`
- `SiteLanguageMiddleware`: перенаправляет все неслужебные URL в формат `/<lang>/...`.
- `SecurityHeadersMiddleware`: добавляет security-заголовки.
- `MaintenanceModeMiddleware`: глобальный редирект в режим техработ.

`core/maintenance.py`
- Нормализация payload техрежима.
- Проверка истечения таймера.
- Автономная HTML-страница техработ (работает даже если шаблоны/статика сломаны).

`core/cloud.py`
- OAuth helper-логика и cloud import/export.
- Включает защиту URL-import от SSRF (блок private/local сетей, лимиты размера/redirect).

`core/bootstrap.py`
- Автозагрузка базовых данных после миграций.
- Идемпотентность через sha1 источника и state в `AppJsonConfig` (`SYSTEM_BOOTSTRAP_STATE`).

`core/models.py`
- Основные сущности: импорт-сессии, пулы, баннеры, weapon catalog, runtime config.

## Потоки данных (как это работает)

### 1) Обычная страница
1. Приходит запрос.
2. `SiteLanguageMiddleware` проверяет язык в пути.
3. `MaintenanceModeMiddleware` решает, пускать ли на страницу.
4. View собирает данные (часть из БД, часть из runtime state).
5. Шаблон рендерится с локализацией.

### 2) Импорт истории
1. Клиент отправляет `POST /api/import/session`.
2. Сервер валидирует входные данные.
3. Создается in-memory session в `core/import_runtime.py`.
4. Фоновый поток тянет записи через `core/services.py`.
5. Статус читается через `GET /api/import/<id>/status`.

### 3) Автозагрузка данных после миграций
1. Выполняется `python manage.py migrate`.
2. Сигнал `post_migrate` вызывает `bootstrap_after_migrate`.
3. Запускается:
- `import_localization_json`
- `sync_static_characters --update-existing`
- `sync_weapon_catalog` (        )
4. В `AppJsonConfig` обновляется `SYSTEM_BOOTSTRAP_STATE`.

## БД: что важно знать контрибутору

Ключевые модели:
- `ImportSession`, `Pull` — данные импортов и круток.
- `StaticCharacter`, `Banner`, `VersionTopStatsSnapshot` — витрина статистики.
- `WeaponCatalog` — данные оружия для страницы и модалки.
- `LocalizationEntry` — DB-переводы.
- `AppAddress` — runtime/fallback ссылки и адреса.
- `AppJsonConfig` — runtime JSON-конфиги (техрежим, game_data и др.).

Правило:
- Меняешь `models.py` -> сразу создавай миграцию и проверяй, что миграции применяются на чистой БД.

## Локализация: как добавлять текст правильно

1. Для UI-строки добавь ключ в `core/localization.py`.
2. Используй этот ключ в шаблоне/вьюхе.
3. Если нужен runtime override через БД, убедись что ключ может прийти из `LocalizationEntry`.
4. Проверь минимум `ru` и `en`.

Важно:
- Не вставляй сырой HTML из пользовательских данных в шаблон/JS.
- Для JS-данных из backend используй `json_script` или явное экранирование.

## Режим техработ: как включить и как проверить

Техрежим задается через `AppJsonConfig` с ключом `MAINTENANCE_MODE`.

Пример payload:
```json
{
  "enabled": true,
  "launch_at": "2026-02-12T18:00:00+03:00",
  "message": "Идут технические работы. Обновляем сервис."
}
```

Поля:
- `enabled`: вкл/выкл редирект на техстраницу.
- `launch_at`: ISO/UNIX seconds/UNIX milliseconds.
- `message`: текст на странице техработ.

Bypass для разработчика:
```js
localStorage.setItem("admin", "true");
```
Снять bypass:
```js
localStorage.removeItem("admin");
```

## Безопасность: минимальные правила для PR

Что уже есть в проекте:
- ORM вместо raw SQL для пользовательского ввода.
- Валидация JSON/API payload и лимиты размеров.
- SSRF-защита для прямого URL-import.
- Security headers через middleware.

Требования к новым изменениям:
- Не добавляй `innerHTML` с неэкранированными строками из внешних данных.
- Не отключай CSRF там, где это не оправдано архитектурой.
- Не принимай URL без валидации схемы/хоста/размера ответа.
- Любой новый endpoint должен валидировать входные данные явно.

## Деплой и запуск на хостинге

Базовый pipeline:
1. `pip install -r requirements.txt`
2. `cp .env.example .env` и заполнить обязательные значения
3. `python manage.py check`
4. `python manage.py migrate`
5. Проверить, что bootstrap отработал (или вручную выполнить `python manage.py bootstrap_app_data`)
6. `python manage.py collectstatic --noinput` (для production)
7. Запуск WSGI/ASGI процесса

Переменные окружения minimum:
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS` (для production за доменом/прокси)
- Опционально для cloud-sync:
- `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`
- `YANDEX_OAUTH_CLIENT_ID`, `YANDEX_OAUTH_CLIENT_SECRET`
- Опционально для Cloudflare Turnstile:
- `TURNSTILE_ENABLED`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`
- Расширенные опции Turnstile:
- `TURNSTILE_VERIFY_URL`, `TURNSTILE_TIMEOUT_SECONDS`

Источник истины для ссылок:
- `DONATE_URL` и `OFFICIAL_REPOSITORY_URL` берутся из `.env`/settings в первую очередь.
- Значения из DB (`AppAddress`) используются только как fallback, если env-переменная пустая.

Turnstile для локалки:
- Держите `TURNSTILE_ENABLED=0`, если в вашей сети блокируются endpoint'ы Cloudflare.
- Для локального теста с включенным Turnstile используйте test keys от Cloudflare.

## Что проверять перед Pull Request

Обязательный минимум:
- `python manage.py check`
- `python manage.py test`
- Если менял безопасность/валидацию, добавь отдельные тесты на негативные кейсы.

Для UI:
- Приложи `before/after` скриншоты.
- Проверь mobile + desktop.

Для БД:
- Проверь fresh install сценарий (`migrate` на пустой БД).
- Убедись, что bootstrap не ломает тесты и повторный запуск идемпотентен.

## Частые проблемы и быстрые решения

Проблема: "Данные из БД поменял, но UI не видит"
- Причина: кеш `AppJsonConfig`.
- Что делать: убедись, что чтение идет с `use_cache=False` там, где нужна мгновенная реакция, или вызови `reset_app_json_cache()` в нужном месте.

Проблема: "После импорта нет прогресса"
- Проверь, что создается session через `/api/import/session`.
- Проверь ответы `/api/import/<id>/status`.
- Помни, что runtime прогресс хранится в памяти процесса.

Проблема: "После деплоя пустая локализация/каталоги"
- Выполни `python manage.py bootstrap_app_data --force`.
- Проверь наличие `special/localization/localization.json`.

Проблема: "Русский текст в документации отображается кракозябрами"
- Открой файл в UTF-8.
- Не сохраняй contributors-файлы в ANSI.

## Формат issue и PR

Issue (bug):
- шаги воспроизведения,
- ожидание,
- факт,
- логи/скриншоты,
- окружение.

PR:
- что изменил,
- почему изменил,
- как тестировал,
- какие риски остались.

## Не делай так

- Не коммить секреты (`.env`, токены, OAuth credentials).
- Не смешивай крупный рефакторинг и фичу без необходимости.
- Не оставляй “магические” изменения без описания в PR.

## Полезные команды

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

## Контакты

Поддержка: `support@endfieldpass.site`

Дисклеймер:
- EndfieldPass не связана с GRYPHLINE.
- Arknights: Endfield, контент и материалы игры являются товарными знаками и принадлежат GRYPHLINE.
