# Troubleshooting

## Server

### The server will not start

Run the checks:

```powershell
.\venv\Scripts\python.exe backend\manage.py check
```

Common causes:

- **`DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is False.`**
  Set a long random `DJANGO_SECRET_KEY`, or use `DJANGO_DEBUG=True` for local
  development only.
- **`Unknown DJANGO_DB_ENGINE`** &mdash; use `mysql`, `postgres`, or leave the
  variable empty for SQLite.
- **`no such table`** &mdash; run `python backend\manage.py migrate`.
- **Database is locked** &mdash; close a second process using the same SQLite
  file, or use MySQL/PostgreSQL for concurrent server writes.

### `DisallowedHost` or HTTP 400

Add the hostname to `DJANGO_ALLOWED_HOSTS` (comma-separated, no scheme):

```
DJANGO_ALLOWED_HOSTS=YOURUSERNAME.pythonanywhere.com,127.0.0.1
```

Restart the server or reload the web app.

### The site loads without CSS

Static files are not mapped. On PythonAnywhere, add:

| URL | Directory |
|---|---|
| `/static/` | `/home/YOURUSERNAME/Nasimango_Auto-Stocking_System/backend/website/static` |

For other hosts, run `collectstatic` and configure the web server.

### Login fails with "Invalid username or password"

- Confirm the account exists and is active.
- Choose the correct role (Admin or Cashier).
- If the owner account was bootstrapped, use the bootstrap password.
- Recover by creating a temporary admin:

```powershell
.\venv\Scripts\python.exe backend\manage.py shell -c "from sales.models import AdminUser; u, _ = AdminUser.objects.get_or_create(username='recovery', defaults={'full_name': 'Recovery', 'role': 'admin'}); u.set_password('change-me-now'); u.is_active=True; u.deleted=False; u.save()"
```

Then sign in and fix the real account. Remove the recovery account afterwards.

### HTTP 401 from the API

The token is missing, revoked, or belongs to a disabled account. Sign in again
from the desktop, or re-pair with a valid connection hash.

### HTTP 403 from pairing

The connection hash is invalid or revoked. Generate a new one:

```bash
python manage.py generate_connection_hash --label "Shop PC"
```

### HTTP 409 "Username is already taken" while pairing

The hash is new but the chosen desktop username already exists. Use a different
username or pair with the hash that is already bound to the existing account.

### Sync reports errors

Check the per-table report in the desktop status or server response. Typical
causes:

- a row references an item or category that does not exist;
- a cashier tried to push cost or admin-only data;
- a malformed decimal or timestamp was inserted by a script.

Fix the source row and sync again. Because operations are idempotent, retrying
is safe.

## Desktop

### The app closes immediately after launch

The app is built without a console, so startup errors appear in a Windows
message box. Read the dialog.

To see a traceback, run from source:

```powershell
.\venv\Scripts\python.exe desktop_app\main.py
```

If the message mentions a database update failure, the app refused to start on
purpose. Restore the backup it names, then reinstall the previous version.

### "Blocked: the development app cannot connect to the production server"

This is intentional. A source checkout runs in the development profile and may
not write to the live shop. Point it at a local or sandbox server:

```powershell
$env:NASS_DEV_SERVER_URL = "http://127.0.0.1:8000"
```

### The desktop cannot connect

- Confirm the server URL includes `https://` and no trailing `/api/`.
- Open `https://YOURSERVER/api/health/` in a browser.
- Check that the computer has internet access and the server is awake.
- Re-pair if the token was revoked or the account was disabled.

### The shop data seems empty after reinstalling

Program files and shop data are separate:

```
Program Files\NASS\                       program files
%LOCALAPPDATA%\NASS\nass.sqlite3          shop data
```

If data is missing, check that the app is running as the same Windows user and
that `%LOCALAPPDATA%` is not redirected. Restore the newest file in
`%LOCALAPPDATA%\NASS\backups\`.

### Stock does not match physical stock

1. Run the read-only check on the server:

   ```bash
   cd backend
   python manage.py rebuild_stock
   ```

2. If only the cached quantity is wrong:

   ```bash
   python manage.py rebuild_stock --recompute
   ```

3. If the ledger is incomplete, follow the repair order in
   [offline-sync.md](offline-sync.md#repairing-stock).

Do not edit `quantity_in_stock` directly; it will drift again on the next sync.

### Sales made on one computer do not appear on another

- Both computers must be paired to the same server and account.
- Check the sync status on both.
- Confirm the server received the sale:

  ```bash
  curl -H "Authorization: Token <TOKEN>" \
    https://YOURSERVER/api/sales/
  ```

- A sale pushed with errors stays in the outbox and is retried on the next
  pass. Fix the reported error.

### Report export is empty

The export uses the From and To dates currently in the form. Set a range that
contains data, then click **Export CSV** again. Very old exports may have used
today's date; that bug is fixed in 1.0.1.

### Dates appear one day off

The server timezone is `Africa/Lusaka`. Ensure timestamps carry a timezone and
that the browser or desktop clock is correct. Report filters build local
day boundaries, so a UTC date string from a custom script can land on the
previous day.

### Reset a development desktop connection

```powershell
Remove-Item "$env:LOCALAPPDATA\NASS-dev\sync_config.json"
```

The next launch starts unpaired. The development database is unaffected.

## Build and installer

See the troubleshooting table in
[build-and-release.md](build-and-release.md#9-troubleshooting).

The most serious build mistake is bundling `database/nass.sqlite3`. Check
before shipping:

```powershell
Get-ChildItem "dist\NASS_v1.0.1" -Recurse -Filter "nass.sqlite3"
```

It must return nothing.

## Useful commands

```powershell
# Health checks
.\venv\Scripts\python.exe backend\manage.py check

# Full tests
.\venv\Scripts\python.exe backend\manage.py test sales website

# Migration status
.\venv\Scripts\python.exe backend\manage.py showmigrations

# Interactive shell
.\venv\Scripts\python.exe backend\manage.py shell

# Stock ledger report
.\venv\Scripts\python.exe backend\manage.py rebuild_stock

# Connection hashes
.\venv\Scripts\python.exe backend\manage.py generate_connection_hash --list
.\venv\Scripts\python.exe backend\manage.py generate_connection_hash --revoke <ID>
```

## Where to look for logs

| Component | Location |
|---|---|
| Development server | The terminal running `runserver` |
| PythonAnywhere | **Web** tab &rarr; error log |
| Desktop startup | Windows message box; run from source for a traceback |
| Sync status | Desktop status bar and `sync_config.json` (`last_sync_status`) |

## Before asking for help

Include:

- the version (`NASS_VERSION` or the About page);
- whether the problem is on the server, desktop, or during build;
- the exact error text or HTTP status;
- the relevant server log lines;
- steps to reproduce.

Remove passwords, tokens, connection hashes, and shop data from anything you
share.
