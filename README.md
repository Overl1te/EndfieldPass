# EndfieldPass

<div align="center">

![EndfieldPass Logo](logo.png)

### Сайт для аналитики молитв в **Arknights: Endfield**

![Website](https://img.shields.io/badge/Website-endfieldpass.site-1f8bff?logo=googlechrome&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-4.2-0C4B33?logo=django&logoColor=white)
![Cloud Sync](https://img.shields.io/badge/Cloud%20Sync-Google%20Drive-4285F4?logo=googledrive&logoColor=white)
![Languages](https://img.shields.io/badge/Languages-ru%20%7C%20en%20%7C%20de%20%7C%20zh--Hans%20%7C%20ja-2ea44f)

**Вставляешь ссылку истории круток -> получаешь статистику, pity и прогресс аккаунта.**

[Сайт](https://endfieldpass.site/) • [README (EN)](README_EN.md) • [Contributing (RU)](CONTRIBUTING.md) • [Contributing (EN)](CONTRIBUTING_EN.md)

</div>

---

## Официальный сайт

Используй официальный сайт: **https://endfieldpass.site/**

---

## Что делает сайт

`EndfieldPass` импортирует историю молитв Endfield и превращает её в удобную аналитику:

- Импорт истории по ссылке (или вручную через `token/server_id`)
- Подсчёт pity для персонажных и оружейных баннеров
- Дашборд с историей и графиком по датам
- Страница персонажей (`получен / не получен`)
- Страница оружия
- Экспорт/импорт JSON для бэкапов
- Синхронизация с Google Drive
- Импорт по прямой JSON-ссылке

---

## Как пользоваться

1. Открой **https://endfieldpass.site/**.
2. Перейди в `Import`.
3. Вставь ссылку истории (или используй ручной ввод `token/server_id`).
4. Запусти импорт.
5. Открой `Dashboard`, `Characters` и `Weapons`.

---

## Как быстро достать ссылку истории

В репозитории есть helper-скрипты:

- `endfieldpass.ps1` для Windows
- `endfieldpass.sh` для Linux

Они читают логи игры и вытаскивают последнюю валидную ссылку, которую можно вставить на **https://endfieldpass.site/**.

---

## Облако и бэкапы

- Подключи Google Drive в `Settings`.
- Файл синхронизации: `EndfieldPass/history-latest.json`.
- Для ручного бэкапа можно в любой момент экспортировать JSON в `Settings`.

---

## Приватность

- История хранится локально в браузере (`localStorage`).
- В облачном режиме данные отправляются только в подключённый тобой провайдер.
- OAuth-токены хранятся в сессии приложения.

---

## Документация

- Русская версия: [README](README.md)
- English version: [README_EN](README_EN.md)
- Правила контрибьюта (RU): [CONTRIBUTING](CONTRIBUTING.md)
- Contribution rules (EN): [CONTRIBUTING_EN](CONTRIBUTING_EN.md)

---

## Ссылки

- Сайт: https://endfieldpass.site/
- Репозиторий: https://github.com/Overl1te/EndfieldPass
- Поддержка: https://github.com/sponsors/Overl1te
