<p align="center">
  <img src="desktop_app/assets/logo.png" alt="NASS logo" width="110">
</p>

<h1 align="center">Nasimango Auto-Stocking System</h1>

<p align="center">
  Offline-first stock, sales, and reporting for a single shop.<br>
  Django REST API &middot; staff web panel &middot; PyQt5 Windows desktop app
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12%2B-3776AB">
  <img alt="Django" src="https://img.shields.io/badge/django-5.2-092E20">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-yellow">
</p>

---

## Overview

NASS is a complete shop-management system built around one rule: **the shop must
keep selling even when the internet is down**.

Each desktop keeps a full local copy of the data in SQLite. A central Django
server holds the master record, serves a staff web panel, and acts as the
offsite backup. Desktops pull and push changes whenever a connection is
available.

### Features

- **Offline-first desktop app** — sales, stock, services, and reports work
  without a network connection.
- **Automatic synchronisation** — pull/push over HTTPS with per-device tokens
  and reusable connection hashes.
- **Auditable stock ledger** — every quantity change is a delta, and the
  invariant `quantity_in_stock == sum(deltas)` is verifiable.
- **Sales and partial payments** — cash sales, part payments, and payment
  history.
- **Services and expenses** — service charges, expense tracking, and
  profit/loss reporting.
- **Exports** — CSV from the web panel and Excel from the desktop app.
- **Two roles** — `admin` and `cashier`, enforced on both the API and the UI.
- **Safe upgrades** — the installer replaces program files only; the shop
  database is snapshotted and migrated on first launch.
- **Windows installer** — built with PyInstaller and Inno Setup.

## Architecture

```
┌──────────────────────────┐        pull / push        ┌──────────────────────────┐
│  Desktop app (PyQt5)     │ ◄───────────────────────► │  Central server (Django) │
│  local SQLite copy       │      HTTPS + API token    │  REST API + web panel    │
│  works offline           │                           │  master database         │
└──────────────────────────┘                           └──────────────────────────┘
                                                                  ▲
                                                                  │ HTTPS
                                                       ┌──────────┴──────────┐
                                                       │ Browser (staff)     │
                                                       └─────────────────────┘
```

The desktop is the offline working copy. The server is the official record and
the offsite backup. The browser panel is online-only and talks directly to the
server.

See [docs/architecture.md](docs/architecture.md) for the full design.

## Tech stack

| Layer | Technology |
|---|---|
| Server | Python, Django 5.2, Django REST Framework |
| Server database | SQLite by default; MySQL or PostgreSQL via environment variables |
| Desktop | Python, PyQt5, Django ORM against local SQLite |
| Sync | HTTPS JSON API with device tokens and soft-delete metadata |
| Packaging | PyInstaller + Inno Setup (Windows) |
| Exports | `openpyxl` (Excel), Django CSV responses |

## Repository layout

```
.
├── backend/                 Django project: REST API, models, web panel
│   ├── nass_backend/        Settings, URL configuration, WSGI
│   ├── sales/               Business models, API, sync engine, tests
│   └── website/             Staff web panel (templates, static, views)
├── desktop_app/             PyQt5 desktop application and sync client
│   ├── front_end/           Windows, dialogs, and widgets
│   └── sync/                Sync client, config, crypto, profiles
├── database/
│   └── seed.sqlite3         Clean, migrated template for fresh installs
├── docs/                    Architecture, setup, deployment, and runbooks
├── packaging/               PyInstaller spec and Inno Setup script
├── scripts/                 Build and diagnostic helpers
└── requirements*.txt
```

## Quick start

### Prerequisites

- Python **3.12+**
- Windows for the desktop app and installer

### 1. Set up the environment

```powershell
git clone https://github.com/glucosy2003/NASS.git
cd nasimango-auto-stocking-system

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Start the server

```powershell
# Optional: start from the clean template instead of an empty database.
Copy-Item database\seed.sqlite3 database\nass.sqlite3

python backend\manage.py migrate
python backend\manage.py runserver
```

Open <http://127.0.0.1:8000/> and complete the first-run admin setup.

### 3. Start the desktop app

In a second terminal, from the repository root:

```powershell
.\venv\Scripts\python.exe desktop_app\main.py
```

A source checkout runs in the **development** profile. It uses
`database/nass.sqlite3` and refuses to connect to the production server. Point
it at your local server with `NASS_DEV_SERVER_URL` (default
`http://127.0.0.1:8000`).

### 4. Run the tests

```powershell
.\venv\Scripts\python.exe backend\manage.py check
.\venv\Scripts\python.exe backend\manage.py test sales website
```

## Configuration

Copy `.env.example` to `.env` and adjust the values. The most important
settings are:

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | `dev-only-change-me` | Django secret; required when `DEBUG=False` |
| `DJANGO_DEBUG` | `True` | Debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `NASS_SHOP_NAME` | `My Shop` | Shop name shown in the app and website |
| `DJANGO_DB_ENGINE` | *(empty)* | `mysql` or `postgres`; empty uses SQLite |
| `DJANGO_DB_NAME` | `nass` | Database name for MySQL/PostgreSQL |
| `DJANGO_DB_USER` / `DJANGO_DB_PASSWORD` | *(empty)* | Database credentials |
| `DJANGO_DB_HOST` / `DJANGO_DB_PORT` | `localhost` / engine default | Database host and port |
| `NASS_BOOTSTRAP_ADMIN_USERNAME` | *(empty)* | Optional first admin username |
| `NASS_BOOTSTRAP_ADMIN_PASSWORD` | *(empty)* | Optional first admin password |
| `NASS_PRODUCTION_SERVER_URL` | `https://your-server.example.com` | Server used by the frozen desktop build |
| `NASS_PRODUCTION_HOSTS` | *(empty)* | Extra hosts treated as production |
| `NASS_DEV_SERVER_URL` | `http://127.0.0.1:8000` | Server used by a source checkout |

## Building the Windows installer

```powershell
# 1. Build the server deployment zip (optional).
.\venv\Scripts\python.exe scripts\build_backend_zip.py

# 2. Build the desktop bundle.
.\venv\Scripts\python.exe -m PyInstaller packaging\NASS.spec --noconfirm

# 3. Build the installer.
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

The installer is written to `installer_output\NASS_v<version>_Setup.exe`.

Full instructions, including version bumping and bundle verification, are in
[docs/build-and-release.md](docs/build-and-release.md).

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | System design, data model, and sync rules |
| [Setup](docs/setup.md) | Local development setup |
| [Deployment](docs/deployment.md) | Deploy the central server to PythonAnywhere |
| [Build and release](docs/build-and-release.md) | Build the desktop app and installer |
| [Authentication](docs/authentication.md) | Roles, bootstrap, pairing, and tokens |
| [Offline sync](docs/offline-sync.md) | Sync protocol, stock ledger, and repair tools |
| [Website](docs/website.md) | Staff web panel features and layout |
| [Upgrading](docs/upgrading.md) | Upgrade a live shop without losing data |
| [Troubleshooting](docs/troubleshooting.md) | Common problems and fixes |

## Security

- Never commit `.env`, `database/nass.sqlite3`, or any real shop data.
- Rotate `DJANGO_SECRET_KEY` and admin passwords before going live.
- Use HTTPS in production and keep the server's `ALLOWED_HOSTS` narrow.
- Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before
opening a pull request.

## License

Released under the [MIT License](LICENSE).
