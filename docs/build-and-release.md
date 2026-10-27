# Build and release

This guide builds the three release artifacts:

1. `backend.zip` for the central server;
2. the PyInstaller desktop bundle in `dist/`;
3. the Windows installer in `installer_output/`.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12+ | Build with the project **venv**, not system Python |
| PyInstaller | 6.22.3+ | Installed in the venv |
| Inno Setup | 6.3+ | `ISCC.exe` compiler |

Install the build tools into the venv:

```powershell
pip install "pyinstaller>=6.22.3"
```

Install Inno Setup:

```powershell
winget install --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements
```

The compiler is usually at one of:

```
C:\Program Files (x86)\Inno Setup 6\ISCC.exe
%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
```

## 1. Build the server archive

```powershell
.\venv\Scripts\python.exe scripts\build_backend_zip.py
```

Output: `backend.zip` in the repository root.

Excluded: `__pycache__`, `.git`, `.pyc`, `.sqlite3`, `.log`, `.env`, and the
virtual environment. Both `backend/` and `website/` are included.

Deploy it as described in [deployment.md](deployment.md).

## 2. Build the desktop bundle

```powershell
.\venv\Scripts\python.exe -m PyInstaller packaging\NASS.spec --noconfirm
```

Output: `dist\NASS_v<version>\`

```
dist\NASS_v1.0.1\
├── NASS_v1.0.1.exe
└── _internal\
    ├── backend\            Django project and migrations
    ├── website\            Staff web panel templates and static files
    ├── database\seed.sqlite3
    ├── assets\             logo and images
    └── ...                 Python, PyQt5, Django, DRF, requests
```

The spec resolves all paths from the repository root, so the command works from
any working directory. Builds take roughly 4&ndash;5 minutes.

The desktop bundle is **one folder**, not one file. This keeps startup fast;
the installer packages the whole folder.

## 3. Build the installer

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Output: `installer_output\NASS_v<version>_Setup.exe` (about 65&ndash;75 MB).

The installer:

- installs to `Program Files\NASS\`;
- creates Start Menu and optional Desktop shortcuts;
- upgrades in place using a stable `AppId`;
- registers an uninstaller;
- never writes to `%LOCALAPPDATA%\NASS\`, where shop data lives.

## 4. Verify the bundle before shipping

The most important check is that the developer database was not bundled.

```powershell
# Must return NOTHING.
Get-ChildItem "dist\NASS_v1.0.1" -Recurse -Filter "nass.sqlite3"

# Must return exactly one file.
Get-ChildItem "dist\NASS_v1.0.1" -Recurse -Filter "seed.sqlite3"
```

Inspect the seed template:

```powershell
.\venv\Scripts\python.exe -c @"
import sqlite3
con = sqlite3.connect(r'dist\NASS_v1.0.1\_internal\database\seed.sqlite3')
for table in ('sales_category', 'sales_item', 'sales_sale', 'sales_adminuser'):
    print(table, con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
"@
```

Expected: 9 categories and 0 rows in items, sales, and users.

> Never change the spec's data entry from `database/seed.sqlite3` to
> `database/`. The latter bundles the developer's live database.

Also confirm that no real `.env`, token, or backup file is present:

```powershell
Get-ChildItem "dist\NASS_v1.0.1" -Recurse -Include "*.env","*.sqlite3-*","sync_config.json"
```

## 5. Version bump checklist

When releasing a new version, update:

1. `backend/nass_backend/settings.py`:

   ```python
   NASS_VERSION = "1.0.2"
   ```

2. `packaging/NASS.spec`:

   ```python
   VERSION = "1.0.2"
   ```

3. `packaging/installer.iss`:

   ```ini
   #define MyAppVersion "1.0.2"
   ```

4. `CHANGELOG.md` &mdash; add the release notes.

The executable name, bundle folder, and installer filename are all derived from
the version, so no other renames are needed. The desktop windows read
`NASS_VERSION` from Django settings.

## 6. Verify an upgrade keeps shop data

On a test machine:

1. Install the previous version and create a sale.
2. Note the file size and modification time of
   `%LOCALAPPDATA%\NASS\nass.sqlite3`.
3. Install the new version over the old one.
4. Launch NASS.
5. Confirm the sale is still present.

If a migration was pending, a verified snapshot appears in
`%LOCALAPPDATA%\NASS\backups\`. If migration fails, the app refuses to start and
shows the snapshot path and rollback instructions.

Rollback:

1. Close NASS.
2. Copy the newest snapshot over `%LOCALAPPDATA%\NASS\nass.sqlite3`.
3. Reinstall the previous version.

## 7. Release checklist

- [ ] `manage.py check` passes.
- [ ] The full test suite passes.
- [ ] `CHANGELOG.md` describes the release.
- [ ] `NASS_VERSION`, the spec, and the installer all have the same version.
- [ ] `backend.zip` was rebuilt if backend code changed.
- [ ] The bundle contains `seed.sqlite3` and no `nass.sqlite3`.
- [ ] The installer runs on a clean machine.
- [ ] An upgrade over the previous version preserves data.
- [ ] The production server URL was set at build time
      (`NASS_PRODUCTION_SERVER_URL`).
- [ ] The server was migrated and reloaded.
- [ ] A server database backup was taken before deploying.

## 8. Build script

Run from the repository root:

```powershell
$PYTHON = ".\venv\Scripts\python.exe"
$ISCC   = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
$VER    = "1.0.1"

Write-Host "Building NASS v$VER" -ForegroundColor Cyan

& $PYTHON scripts\build_backend_zip.py
if ($LASTEXITCODE -ne 0) { throw "backend.zip build failed" }

& $PYTHON -m PyInstaller packaging\NASS.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

& $ISCC packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$leaked = Get-ChildItem "dist\NASS_v$VER" -Recurse -Filter "nass.sqlite3"
if ($leaked) {
    $leaked | ForEach-Object { Write-Host "LEAK: $($_.FullName)" -ForegroundColor Red }
    throw "Developer database was bundled"
}

$seed = Get-ChildItem "dist\NASS_v$VER" -Recurse -Filter "seed.sqlite3"
if (-not $seed) { throw "seed.sqlite3 is missing from the bundle" }

$setup = Get-Item "installer_output\NASS_v${VER}_Setup.exe"
Write-Host ("OK: {0} ({1:N1} MB)" -f $setup.FullName, ($setup.Length / 1MB)) -ForegroundColor Green
```

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `No module named PyInstaller` | Install it into the venv: `pip install "pyinstaller>=6.22.3"` |
| `Hidden import 'rest_framework' not found` | Install `requirements.txt` into the build venv |
| `ISCC.exe not found` | Install Inno Setup and use the full compiler path |
| Installer build is very slow | Keep `Compression=lzma2` and `SolidCompression=no` |
| App exits immediately after launch | Startup errors are shown in a Windows message box; also run from source for a traceback |
| Bundle contains `nass.sqlite3` | The spec's data entry is wrong; restore `database/seed.sqlite3` and rebuild |
| Installer uses the wrong bundle | The version in the spec and the installer must match |
| `dist` or `installer_output` committed to git | They are ignored; remove them from the index with `git rm -r --cached dist installer_output` |
