# EndfieldPass

<div align="center">

![EndfieldPass Logo](logo.png)

### Pull history tracker and analytics for **Arknights: Endfield**

![Website](https://img.shields.io/badge/Website-endfieldpass.site-1f8bff?logo=googlechrome&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-4.2-0C4B33?logo=django&logoColor=white)
![Cloud Sync](https://img.shields.io/badge/Cloud%20Sync-Google%20Drive-4285F4?logo=googledrive&logoColor=white)
![Languages](https://img.shields.io/badge/Languages-ru%20%7C%20en%20%7C%20de%20%7C%20zh--Hans%20%7C%20ja-2ea44f)

**Paste your pull-history URL -> get clean stats, pity tracking, and account progress.**

[Website](https://endfieldpass.site/) • [README (RU)](README.md) • [Contributing (EN)](CONTRIBUTING_EN.md) • [Contributing (RU)](CONTRIBUTING.md)

</div>

---

## Official Website

Use the official website: **https://endfieldpass.site/**

---

## What the website does

`EndfieldPass` is a website that imports your Endfield pull history and turns it into readable analytics:

- Pull-history import from URL (or manual token/server mode)
- Pity tracking for character and weapon banners
- Dashboard with history and timeline chart
- Characters page (`obtained / not obtained`)
- Weapons page
- JSON export/import for backups
- Google Drive cloud sync
- Direct JSON URL import

---

## How to use

1. Open **https://endfieldpass.site/**.
2. Go to `Import`.
3. Paste your pull-history URL (or use manual `token/server_id`).
4. Run import.
5. Open `Dashboard`, `Characters`, and `Weapons`.

---

## How to extract your history URL quickly

This repo includes helper scripts:

- `endfieldpass.ps1` for Windows
- `endfieldpass.sh` for Linux

They read game logs and extract the latest valid history URL that you can paste into **https://endfieldpass.site/**.

---

## Cloud and backups

- Connect Google Drive in `Settings`.
- History sync file: `EndfieldPass/history-latest.json`.
- You can always export JSON manually from `Settings`.

---

## Privacy

- Pull history is stored locally in your browser (`localStorage`).
- In cloud mode, data is sent only to the provider you connect.
- OAuth cloud tokens are kept in application session data.

---

## Documentation

- Russian README: [README](README.md)
- English README: [README_EN](README_EN.md)
- Russian contributing rules: [CONTRIBUTING](CONTRIBUTING.md)
- English contributing rules: [CONTRIBUTING_EN](CONTRIBUTING_EN.md)

---

## Links

- Website: https://endfieldpass.site/
- Repository: https://github.com/Overl1te/EndfieldPass
- Support: https://github.com/sponsors/Overl1te

