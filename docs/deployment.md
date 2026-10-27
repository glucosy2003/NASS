# Deploying the central server

These instructions target **PythonAnywhere**, which is the reference host for
NASS. Any host that can run Django and WSGI will work equally well.

One NASS server serves one shop. All desktops for that shop point at the same
server URL.

## 1. Build the deployment archive

From the repository root:

```powershell
.\venv\Scripts\python.exe scripts\build_backend_zip.py
```

This creates `backend.zip` containing only `backend/`. It excludes
`__pycache__`, `.git`, `.pyc`, `.sqlite3`, `.log`, and `.env` files.

Only the following are needed on the server:

- `backend/` (Django project, apps, migrations)
- `requirements-server.txt`

## 2. Upload the code

1. Create a free **Beginner** account at <https://www.pythonanywhere.com>.
   Your server URL will be `https://YOURUSERNAME.pythonanywhere.com`.
2. Open a **Bash console** (Dashboard &rarr; Consoles &rarr; Bash).
3. Upload `backend.zip` with the **Files** tab, then unzip it:

```bash
cd ~
mkdir -p Nasimango_Auto-Stocking_System
unzip backend.zip -d Nasimango_Auto-Stocking_System
```

Upload `requirements-server.txt` to `~/Nasimango_Auto-Stocking_System/` as well.

## 3. Create the virtual environment

```bash
cd ~/Nasimango_Auto-Stocking_System
mkvirtualenv --python=/usr/bin/python3.12 nass
pip install -r requirements-server.txt
```

Use `requirements-server.txt`, not `requirements.txt`: the latter includes
desktop-only packages such as PyQt5 and openpyxl.

## 4. Create the database and environment

```bash
cd ~/Nasimango_Auto-Stocking_System
mkdir -p database
cd backend

export DJANGO_SECRET_KEY="<a long random string>"
export DJANGO_DEBUG="False"
export DJANGO_ALLOWED_HOSTS="YOURUSERNAME.pythonanywhere.com,127.0.0.1,localhost"
export NASS_SHOP_NAME="My Shop"

python manage.py migrate
```

With no `DJANGO_DB_ENGINE` set, the server uses SQLite at:

```
~/Nasimango_Auto-Stocking_System/database/nass.sqlite3
```

Create a strong secret key, for example:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(64))
PY
```

## 5. Create the first admin

Use either the browser or the environment bootstrap.

**Browser:** open `https://YOURUSERNAME.pythonanywhere.com/setup/` after the
first deploy and create the owner account.

**Bootstrap:**

```bash
export NASS_BOOTSTRAP_ADMIN_USERNAME="owner"
export NASS_BOOTSTRAP_ADMIN_PASSWORD="<a strong initial password>"
export NASS_BOOTSTRAP_ADMIN_EMAIL="owner@example.com"
python manage.py migrate
```

The bootstrap only runs when both username and password are set. Change the
password after the first login.

## 6. Configure the web app

1. **Web &rarr; Add a new web app &rarr; Manual configuration &rarr; Python 3.12.**
2. Set **Virtualenv** to `/home/YOURUSERNAME/.virtualenvs/nass`.
3. Set **Source code** to
   `/home/YOURUSERNAME/Nasimango_Auto-Stocking_System/backend`.
4. Set **Working directory** to the same path.
5. Open the **WSGI configuration file** and replace its contents with:

```python
import os
import sys

path = "/home/YOURUSERNAME/Nasimango_Auto-Stocking_System/backend"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["DJANGO_SETTINGS_MODULE"] = "nass_backend.settings"
os.environ["DJANGO_SECRET_KEY"] = "<the same long random string>"
os.environ["DJANGO_DEBUG"] = "False"
os.environ["DJANGO_ALLOWED_HOSTS"] = "YOURUSERNAME.pythonanywhere.com,127.0.0.1"
os.environ["NASS_SHOP_NAME"] = "My Shop"

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
```

6. Add the static files mapping on the **Web** tab:

| URL | Directory |
|---|---|
| `/static/` | `/home/YOURUSERNAME/Nasimango_Auto-Stocking_System/backend/website/static` |

7. Press **Reload**.

## 7. Verify the deployment

Health check:

```bash
curl https://YOURUSERNAME.pythonanywhere.com/api/health/
```

Expected:

```json
{"status": "ok", "service": "nass-api", "time": "..."}
```

Login:

```bash
curl -X POST https://YOURUSERNAME.pythonanywhere.com/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"owner","password":"<password>","device_name":"first-pc"}'
```

A successful response contains `token`, `device_id`, and `user`.

Authenticated pull:

```bash
curl -X POST https://YOURUSERNAME.pythonanywhere.com/api/sync/pull/ \
  -H "Authorization: Token <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"device_id":"test-1"}'
```

Open the web panel at `https://YOURUSERNAME.pythonanywhere.com/login/` and sign
in.

## 8. Pair the first desktop

1. On the server, generate a reusable connection hash:

```bash
cd ~/Nasimango_Auto-Stocking_System/backend
python manage.py generate_connection_hash --label "Shop PC"
```

2. Copy the printed `NASS-...` value immediately. Only a salted hash is stored,
   so it cannot be recovered later.
3. On the desktop, open **Sync Settings &rarr; Connection Hash**, enter the
   server URL and the hash, then connect.
4. The desktop creates its server account, receives a token, and performs a
   full pull.

Manage hashes:

```bash
python manage.py generate_connection_hash --list
python manage.py generate_connection_hash --revoke <ID>
```

A hash is reusable: pasting it into another desktop reconnects that computer to
the same account and data. A revoked hash returns HTTP 403.

## 9. Back up the server database

SQLite is a single file. Download it regularly from the **Files** tab, or copy
it on the server:

```bash
cd ~/Nasimango_Auto-Stocking_System
cp database/nass.sqlite3 database/nass-$(date +%Y%m%d).sqlite3
```

Keep copies outside the server as well. The server is the offsite backup for
the desktops, not a substitute for your own backup.

For MySQL/PostgreSQL, use the provider's backup facility.

## 10. Updating the server

```powershell
# On your PC, after the code changes:
.\venv\Scripts\python.exe scripts\build_backend_zip.py
```

1. Upload `backend.zip` to PythonAnywhere.
2. In a Bash console:

```bash
cd ~/Nasimango_Auto-Stocking_System
unzip -o backend.zip -d .

cd backend
export DJANGO_SECRET_KEY="<same secret>"
export DJANGO_DEBUG="False"
export DJANGO_ALLOWED_HOSTS="YOURUSERNAME.pythonanywhere.com,127.0.0.1"
python manage.py migrate
```

3. Press **Reload** on the **Web** tab.

The environment exports above are only for the console session. The WSGI file
holds the values used by the live web app.

When `sales/sync.py`, `sales/views.py`, or `sales/models.py` change, always
reload the web app after uploading. A model change also requires `migrate`.

## 11. Switching to MySQL or PostgreSQL

### MySQL on PythonAnywhere

1. **Databases &rarr; Create a new MySQL database** named `nass`
   (full name `YOURUSERNAME$nass`) with a strong password.
2. Install the driver and migrate:

```bash
workon nass
pip install pymysql
cd ~/Nasimango_Auto-Stocking_System/backend

export DJANGO_DB_ENGINE=mysql
export DJANGO_DB_NAME="YOURUSERNAME\$nass"
export DJANGO_DB_USER="YOURUSERNAME"
export DJANGO_DB_PASSWORD="<database password>"
export DJANGO_DB_HOST="YOURUSERNAME.mysql.pythonanywhere-services.com"
export DJANGO_DB_PORT="3306"

python manage.py migrate
```

3. Add the same `DJANGO_DB_*` values to the WSGI file, then reload.

### PostgreSQL

```bash
export DJANGO_DB_ENGINE=postgres
export DJANGO_DB_NAME=nass
export DJANGO_DB_USER=nass
export DJANGO_DB_PASSWORD="<database password>"
export DJANGO_DB_HOST="<host>"
export DJANGO_DB_PORT="5432"
python manage.py migrate
```

Install a PostgreSQL driver (`psycopg[binary]`) in the server environment.

## 12. Production checklist

- [ ] `DJANGO_DEBUG=False`.
- [ ] `DJANGO_SECRET_KEY` is long, random, and unique to this server.
- [ ] `DJANGO_ALLOWED_HOSTS` contains only the real hostname.
- [ ] The owner password has been changed from the bootstrap value.
- [ ] Every staff member has their own account with the correct role.
- [ ] Departed staff are deactivated, not deleted.
- [ ] Lost connection hashes are revoked.
- [ ] Static files are mapped and the site loads with styling.
- [ ] A database backup exists outside the server.
- [ ] The desktop production URL was set at build time (see
      [build-and-release.md](build-and-release.md)).

## Free-tier notes

- PythonAnywhere's free tier provides one web app, limited CPU, and no GitHub
  integration; deploys are manual uploads.
- The WSGI worker sleeps when idle, so the first request can be slow.
- SQLite on the shared filesystem is slower than MySQL but adequate for a
  single shop.
- Free web apps are disabled after a period without use. Daily desktop syncs
  keep the app active; otherwise open `/api/health/` periodically.
