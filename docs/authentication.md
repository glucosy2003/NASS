# Authentication and access

NASS has two kinds of credentials:

- **User accounts** authenticate people (browser and desktop).
- **Connection hashes** pair a new desktop with the shop without typing an
  admin password on every machine.

## Roles

| Capability | Admin | Cashier |
|---|---|---|
| Record sales | Yes | Yes |
| View stock levels | Yes | Yes |
| View selling prices | Yes | Yes |
| View cost and profit | Yes | No |
| Add or edit items and prices | Yes | No |
| Adjust stock | Yes | No |
| Manage categories | Yes | No |
| Manage services and expenses | Yes | No |
| View reports | Yes | No |
| Manage users and sync settings | Yes | No |

Every `AdminUser` row has `role` set to `admin` or `cashier`. API permissions
enforce the same rules as the UI.

## Creating the first account

### Browser first-run setup

On an empty database, open the site root. It redirects to `/setup/`, where you
create the owner account. The username is fixed to `admin`; the full name,
optional email, and password are entered by the owner.

`/setup/` is only available while no account exists. After the first account
is created it redirects to `/login/`.

### Environment bootstrap

For unattended deployments, set these variables and run `migrate`:

```powershell
$env:NASS_BOOTSTRAP_ADMIN_USERNAME = "owner"
$env:NASS_BOOTSTRAP_ADMIN_PASSWORD = "a-strong-initial-password"
$env:NASS_BOOTSTRAP_ADMIN_EMAIL = "owner@example.com"
.\venv\Scripts\python.exe backend\manage.py migrate
```

The account is created with the `admin` role. The bootstrap is idempotent: it
does nothing if the username already exists. It only runs when both the
username and password variables are non-empty.

Change the initial password after the first login.

## Browser login

The login page has a role selector:

- **Admin** requires an account with the `admin` role.
- **Cashier** requires an account with the `cashier` role.

Choosing the wrong role produces a clear error rather than a generic failure.
Inactive or deleted accounts cannot sign in. The browser uses Django sessions
and the custom `AdminUserBackend`.

Staff accounts are created from **Admin panel &rarr; Users** or the users API.
Passwords are stored as Django password hashes, never in plain text.

## Desktop pairing

### Generate a connection hash

On the server:

```bash
cd backend
python manage.py generate_connection_hash --label "Shop PC"
```

The command prints a value such as `NASS-AB12CDEF3456789012` **once**. Only a
salted password hash of it is stored in `ConnectionCredential.code_hash`.

### Pair a desktop

1. Open **Sync Settings** in the desktop app.
2. Choose the **Connection Hash** tab.
3. Enter the server URL and paste the `NASS-...` value.
4. Confirm.

The desktop calls the anonymous endpoint `POST /api/auth/pair/` with the hash,
a local username, a device name, and an optional password hash. The server:

- finds a non-revoked credential whose hash matches;
- if the credential is not yet bound, creates an `AdminUser` for the supplied
  username (HTTP 409 if that username is already taken);
- if the credential is already bound, reconnects to the same `AdminUser`;
- returns an API token and device ID;
- records the pairing in the audit log.

The desktop then performs a full pull.

### Reusing a hash

A hash is never consumed. Pasting the same hash into another computer
reconnects it to the same account and data. This is how a replacement PC is
restored.

### Revoking a hash

```bash
python manage.py generate_connection_hash --list
python manage.py generate_connection_hash --revoke <ID>
```

A revoked hash is rejected with HTTP 403. Revocation does not invalidate tokens
that were already issued; revoke those separately if a device is lost.

## Username and password login on the desktop

An existing account can also sign in from the **Account** tab of Sync
Settings. The desktop calls `POST /api/auth/login/` and stores the returned
token. This is useful for development or when a connection hash is not
available.

Pairing is preferred for shop machines because it avoids sharing an admin
password with every cashier desktop.

## API tokens

- Created on login or pairing with `secrets.token_hex(32)`.
- Stored in `ApiToken`, bound to one device (`device_id`).
- Sent as `Authorization: Token <token>`.
- `last_used_at` is updated on each authenticated request.
- Logging out revokes the token.
- The desktop stores the token encrypted with Windows DPAPI in
  `%LOCALAPPDATA%\NASS\sync_config.json`.

A `401` response clears the stored token and marks the device disconnected. The
user must pair or sign in again.

## Desktop profiles

The desktop has two isolated profiles:

| | Production | Development |
|---|---|---|
| Build | Frozen (PyInstaller) | Source checkout |
| Config directory | `%LOCALAPPDATA%\NASS\` | `%LOCALAPPDATA%\NASS-dev\` |
| Default server | `NASS_PRODUCTION_SERVER_URL` | `NASS_DEV_SERVER_URL` |
| May contact production | Yes | **No** |

The development profile is blocked from the production host in
`sync/profile.py` before any request is built, even if the configuration file
was edited by hand. This prevents a developer's test data from overwriting the
live shop.

## Password management

Admins can change their own password from **Account** in the web panel and can
reset another user's password from **Admin panel &rarr; Users**. Passwords must
be at least four characters; use longer passwords in production.

Deactivating an account sets `is_active=False`. Its tokens stop working
immediately. Deleting an account is a soft delete and also disables login.

## Audit log

The server records security-relevant events in `AuditLog`: logins, logouts,
user creation and updates, stock adjustments, sales, and deletions. Each entry
stores the user, action, entity, device ID, and time. Admins can inspect the
latest entries through the API:

```bash
curl -H "Authorization: Token <TOKEN>" \
  https://YOURUSERNAME.pythonanywhere.com/api/auditlog/
```

## Security notes

- Serve the server over HTTPS.
- Keep `DJANGO_DEBUG=False` and a unique `DJANGO_SECRET_KEY` in production.
- Give each staff member their own account; do not share the owner login.
- Deactivate accounts when staff leave.
- Revoke a connection hash if a shop computer is lost or replaced.
- Treat a connection hash like a password: it grants access to the shop's data.
- Back up the server database before rotating credentials or hosts.
