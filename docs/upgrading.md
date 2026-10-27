# Upgrading a live shop

## What is safe by design

The Windows installer replaces files in `Program Files\NASS\` only. Shop data
lives in:

```
%LOCALAPPDATA%\NASS\nass.sqlite3
```

It is never overwritten by installing a new version. The desktop app also takes
a verified snapshot before running a pending database migration.

Server data lives in the server's database (`database/nass.sqlite3` for SQLite,
or MySQL/PostgreSQL). Server upgrades are applied with `manage.py migrate`.

## Before upgrading

1. **Back up the server database.**
   - SQLite: download or copy `database/nass.sqlite3`.
   - MySQL/PostgreSQL: use the provider's backup or `mysqldump`/`pg_dump`.
2. **Let every desktop finish a sync.** Check that the status bar is not
   showing an error.
3. **Note the current version.** It is shown in the desktop sidebar/footer and
   on the web About page.
4. **Keep the previous installer.** It is the fastest rollback for the desktop
   program files.

## Upgrade order

For a release that changes models or the sync protocol:

1. Back up the server database.
2. Deploy the new server code and run migrations.
3. Reload the web app.
4. Install the new desktop version on one computer.
5. Verify sales, stock, reports, and sync.
6. Roll the desktop update out to the remaining computers.

Deploying the server first lets every device talk to a server that understands
the new data. The desktop still works offline while it waits to be updated.

## Server upgrade

```bash
cd ~/Nasimango_Auto-Stocking_System
# upload and unzip the new backend.zip
unzip -o backend.zip -d .

cd backend
export DJANGO_SECRET_KEY="<same secret>"
export DJANGO_DEBUG="False"
export DJANGO_ALLOWED_HOSTS="YOURUSERNAME.pythonanywhere.com,127.0.0.1"
python manage.py migrate
```

Then press **Reload** on the **Web** tab.

If the server is on MySQL/PostgreSQL, export the same `DJANGO_DB_*` variables
used by the WSGI file before running `migrate`.

Verify:

```bash
curl https://YOURUSERNAME.pythonanywhere.com/api/health/
```

## Desktop upgrade

1. Run the new `NASS_v<version>_Setup.exe`.
2. Install over the existing version (same `AppId`, so it is treated as an
   upgrade).
3. Launch NASS.

On first launch, if a migration is pending, the app:

1. snapshots the database with SQLite's online backup API;
2. verifies the snapshot with `PRAGMA integrity_check`;
3. stores it in `%LOCALAPPDATA%\NASS\backups\`;
4. runs migrations;
5. opens normally.

If migration fails, the app does not open. A message box shows the failure,
the snapshot path, and the rollback instructions.

## Backups kept by the desktop

```
%LOCALAPPDATA%\NASS\backups\nass-YYYYMMDD-HHMMSS.sqlite3
```

The newest five snapshots are retained. A legacy
`%LOCALAPPDATA%\NASS\nass.sqlite3.bak` is refreshed at the same time.

A snapshot is only taken when a migration is actually pending, so routine
launches do not overwrite the last known-good copy.

## Rolling back a desktop

1. Close NASS.
2. Copy the newest backup over the live database:

   ```powershell
   Copy-Item "$env:LOCALAPPDATA\NASS\backups\nass-YYYYMMDD-HHMMSS.sqlite3" `
             "$env:LOCALAPPDATA\NASS\nass.sqlite3" -Force
   ```

3. Reinstall the previous version with its installer.
4. Launch and verify.

Do not copy a backup while NASS is running.

## Rolling back the server

1. Stop or reload the web app.
2. Restore the database backup taken before the upgrade.
3. Deploy the previous `backend.zip`.
4. Reload the web app.

Desktop clients that already synced with the newer schema may need to be
restored from their own backups as well. For this reason, upgrade the server
and desktops together and keep a backup from both sides.

## Version compatibility

- The sync format is additive: new fields are ignored by older clients.
- Database migrations are not automatically reversible in every release.
  Restoring a backup is the supported rollback.
- Do not run a newer desktop against an older server for long. Pair it, test
  it, then upgrade the server promptly.

## Post-upgrade checks

- [ ] `/api/health/` returns `ok`.
- [ ] Web login works for an admin and a cashier.
- [ ] A test sale appears in reports with the correct date and profit.
- [ ] Stock decreased by the sold quantity.
- [ ] The desktop status bar shows a successful sync.
- [ ] Another desktop sees the test sale after syncing.
- [ ] `manage.py rebuild_stock` reports a balanced ledger.
- [ ] The About page shows the expected version.

## Cleaning old installers

`installer_output/` and `dist/` are ignored by git. Delete old builds when they
are no longer needed. Never keep a build that was made before the clean-database
fix: it may contain a developer database.
