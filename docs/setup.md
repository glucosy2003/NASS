# Development setup

This guide gets a working server and desktop app running from a fresh clone on
Windows.

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.12 or newer | Server and desktop |
| Git | any recent version | Cloning |
| Inno Setup | 6.3+ | Building the Windows installer (optional) |
| PyInstaller | 6.22.3+ | Building the desktop bundle (optional) |

The desktop app is Windows-only. The server can run on any platform supported
by Django.

## 1. Clone and install

```powershell
git clone https://github.com/YOUR_GITHUB_USERNAME/nasimango-auto-stocking-system.git
cd nasimango-auto-stocking-system

python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks the activation script, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. Create the development database

Two options:

**A. Start from the clean template (recommended):**

```powershell
Copy-Item database\seed.sqlite3 database\nass.sqlite3
python backend\manage.py migrate
```

`seed.sqlite3` is a fully migrated database with the default categories and no
items, sales, or users.

**B. Start empty:**

```powershell
python backend\manage.py migrate
```

`database/nass.sqlite3` is ignored by git. Delete it at any time to start over;
the next `migrate` recreates it.

> Never copy the production database from
> `%LOCALAPPDATA%\NASS\nass.sqlite3` into the repository.

## 3. Start the server

```powershell
python backend\manage.py runserver
```

Open <http://127.0.0.1:8000/>.

- On a fresh database you are redirected to `/setup/` to create the owner
  account (username `admin`).
- Otherwise sign in at `/login/` with the **Admin** or **Cashier** role.

To create the first admin non-interactively, set the bootstrap variables before
migrating:

```powershell
$env:NASS_BOOTSTRAP_ADMIN_USERNAME = "owner"
$env:NASS_BOOTSTRAP_ADMIN_PASSWORD = "a-strong-initial-password"
$env:NASS_BOOTSTRAP_ADMIN_EMAIL = "owner@example.com"
python backend\manage.py migrate
```

The bootstrap only runs when both username and password are set. Change the
password after the first login.

## 4. Start the desktop app

In a second terminal, from the repository root:

```powershell
.\venv\Scripts\python.exe desktop_app\main.py
```

A source checkout always runs in the **development** profile:

| Setting | Value |
|---|---|
| Local database | `database/nass.sqlite3` (shared with the dev server) |
| Config directory | `%LOCALAPPDATA%\NASS-dev\` |
| Default server | `http://127.0.0.1:8000` |

The dev profile refuses to connect to the production host. Override the server
with `NASS_DEV_SERVER_URL`:

```powershell
$env:NASS_DEV_SERVER_URL = "http://127.0.0.1:8000"
```

### Pair the desktop

Open **Sync Settings** in the desktop app.

**Option A &mdash; connection hash (recommended):**

```powershell
python backend\manage.py generate_connection_hash --label "Dev Desktop"
```

Copy the printed `NASS-...` value into the **Connection Hash** tab together with
the server URL. The hash is shown once and is reusable.

**Option B &mdash; username and password:**

Use the account created at `/setup/` on the **Account** tab.

After pairing, the desktop performs a full pull. Because the dev server and
desktop use the same SQLite file, they already share data; the pull simply
confirms the connection.

## 5. Run the checks and tests

```powershell
.\venv\Scripts\python.exe backend\manage.py check
.\venv\Scripts\python.exe backend\manage.py test sales website
```

The full suite takes about a minute and must pass before opening a pull
request.

Useful test subsets:

```powershell
# Sync and stock behaviour
.\venv\Scripts\python.exe backend\manage.py test sales.tests_sync_desktop

# Website views
.\venv\Scripts\python.exe backend\manage.py test website

# A single test
.\venv\Scripts\python.exe backend\manage.py test sales.tests_sync_desktop.SalesTests.test_seed_is_clean
```

## Configuration

Settings are read from environment variables. For local development, copy
`.env.example` to `.env` and load it in your shell, or set variables directly.

```powershell
$env:NASS_SHOP_NAME = "My Shop"
$env:DJANGO_DEBUG = "True"
python backend\manage.py runserver
```

See the table in the [README](../README.md#configuration) for all variables.

## Common tasks

### Create a staff account

Use **Admin panel &rarr; Users** in the browser, or the users API. Choose the
`admin` or `cashier` role. Cashiers cannot see cost, profit, or configuration.

### Reset the development database

```powershell
Remove-Item database\nass.sqlite3
Copy-Item database\seed.sqlite3 database\nass.sqlite3
python backend\manage.py migrate
```

### Clear the development sync configuration

```powershell
Remove-Item "$env:LOCALAPPDATA\NASS-dev\sync_config.json"
```

### Inspect the stock ledger

```powershell
python backend\manage.py rebuild_stock
```

This is a read-only report. See [offline-sync.md](offline-sync.md) for the
repair flags.

### Generate an API token without the desktop

```powershell
$body = '{"username":"admin","password":"your-password","device_name":"curl"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/auth/login/ `
  -ContentType "application/json" -Body $body
```

## Troubleshooting

If the server starts but the desktop cannot connect, check:

- the server URL in **Sync Settings**;
- that the server is running on the expected port;
- that the account exists and is active;
- that the connection hash was copied completely.

More fixes are in [troubleshooting.md](troubleshooting.md).
