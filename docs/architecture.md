# Architecture

## Design goals

NASS manages **one shop**. The shop may have several computers (5&ndash;20 is
the intended range), but there is exactly one server and one dataset.

The design is driven by three constraints:

1. **The shop must keep working offline.** A lost internet connection must not
   stop a sale.
2. **Every device must converge on the same data.** Sales and stock changes
   made on different computers must never overwrite each other.
3. **The shop's data must survive an upgrade.** The installer must never be
   able to delete or corrupt the local database.

## Topology

```
┌──────────────────────────┐        push / pull        ┌──────────────────────────┐
│  Desktop app (PyQt5)     │ ◄───────────────────────► │  Central server (Django) │
│  local SQLite working    │      HTTPS + API token    │  REST API + web panel    │
│  copy; works offline     │                           │  master database         │
└──────────────────────────┘                           └──────────────────────────┘
                                                                  ▲
                                                                  │ HTTPS
                                                       ┌──────────┴──────────┐
                                                       │ Browser (staff)     │
                                                       │ online only         │
                                                       └─────────────────────┘
```

- The **desktop** is the offline working copy. Every write is committed to the
  local SQLite database first, then synchronised when a connection exists.
- The **server** is the official record and the offsite backup. It also serves
  the browser panel directly.
- The **browser panel** is online-only: it reads and writes the server
  database immediately and does not participate in desktop sync.

One server serves exactly one shop. There is no tenant or shop identifier in
the sync payload.

## Components

| Component | Location | Responsibility |
|---|---|---|
| Django project | `backend/nass_backend/` | Settings, URL routing, WSGI entry point |
| Business app | `backend/sales/` | Models, API, sync engine, permissions, management commands |
| Web panel | `website/` | Staff HTML UI, templates, static assets |
| Desktop app | `desktop_app/` | PyQt5 UI, local database, sync client |
| Sync client | `desktop_app/sync/` | HTTP client, config, token encryption, background sync |
| Packaging | `packaging/` | PyInstaller spec and Inno Setup script |

The desktop imports the same Django models and the same `sales.sync` module as
the server. That is deliberate: the wire format has a single implementation,
so the two sides cannot drift apart.

## Data model

All syncable tables carry the same metadata:

| Field | Meaning |
|---|---|
| `external_id` | Stable UUID shared by every copy of the row |
| `updated_at` | Last local modification time, used for conflict resolution |
| `deleted` | Soft-delete flag; rows are never physically removed by sync |

| Model | Role |
|---|---|
| `Category` | Item grouping; optional size requirement |
| `Item` | Product, prices, cached stock quantity |
| `StockAdjustment` | Append-only stock delta; the source of truth for stock |
| `Sale` / `SaleItem` | Sale header and lines; append-only |
| `PartialPayment` / `PaymentRecord` | Credit sale header and append-only payments |
| `Service` / `ServiceEntry` | Service definition and appended service income |
| `Expense` | Operating expense |
| `AdminUser` | Staff account, password hash, role |
| `ApiToken` | Login session bound to one device |
| `ConnectionCredential` | Server-issued pairing hash (stored hashed) |
| `SyncLog` | Per-device last pull/push timestamps |
| `AuditLog` | Security and activity trail |

Decimals are transmitted as strings (for example `"100.50"`) and timestamps as
ISO-8601 with a timezone, so no float or timezone drift is introduced by the
wire format.

## Stock ledger

Stock is **never** set by assigning an absolute quantity during sync. It only
changes through appended deltas:

- opening stock when an item is created;
- a sale (negative delta per sold line);
- a deletion of a sale (positive restore delta);
- a manual stock adjustment.

The invariant is:

```
Item.quantity_in_stock == sum(StockAdjustment.delta for that item)
```

`quantity_in_stock` is a cache for fast reads. It is recomputed from the ledger
whenever the integrity check runs, and can be repaired with
`manage.py rebuild_stock` (server) or `NASS_v<version>.exe --rebuild-stock`
(desktop).

Sale-related deltas use deterministic UUIDs derived from the sale line, so
receiving the same sale twice rebuilds the same adjustment instead of
double-counting:

```
opening:  uuid5(item.external_id, "nass-opening-stock")
sale:     uuid5(sale_item.external_id, "nass-sale-stock")
restore:  uuid5(sale_item.external_id, "nass-sale-delete-stock")
```

## Conflict rules

| Data | Rule |
|---|---|
| Categories, items, users | Last writer wins by `updated_at` |
| Sales and service entries | Append-only; idempotent by `external_id` |
| Payments | Append-only; totals are derived from non-deleted records |
| Stock | Additive deltas only; never overwritten by a row value |
| Deletions | Soft delete (`deleted=true`) propagates as a normal change |

Because sales are append-only and stock is additive, two cashiers selling at
the same time on two computers both succeed. The server applies both changes
and every device converges on the same totals.

## Sync protocol

The desktop always runs **push, then pull**.

1. **Push** — `POST /api/sync/push/`
   - The client collects rows changed since `last_push` (or every row when a
     full push is pending).
   - The cursor is captured *before* the payload is built and only advanced
     when the server reports no errors. Rows created while the request is in
     flight are therefore picked up next time.
   - The server applies changes idempotently by `external_id` and returns a
     per-table report.
2. **Pull** — `POST /api/sync/pull/`
   - The client sends `since` (the previous `server_time`), minus a one-minute
     overlap to absorb rows written during the previous request.
   - The server returns changed rows plus `server_time`, which becomes the
     next cursor.
3. **First pairing** — the client performs a full pull (no `since`) to restore
   the entire dataset, then marks the initial pull as done.

An optional `device_id` is sent with each request and recorded in `SyncLog`.
Authentication is a per-device token in the `Authorization: Token <token>`
header.

The client retries once on a connection error or timeout (15 seconds). A
`401` clears the stored token and marks the device as disconnected. Sync runs
automatically in the background (default every minute) and can be triggered
manually from the desktop.

## Security model

- **Roles** — `admin` (full access) and `cashier` (sales and read-only stock;
  no cost, profit, price, user, or configuration access).
- **Web sessions** — Django sessions for the browser panel, using a custom
  backend over `AdminUser`.
- **API tokens** — random 64-character tokens bound to a device; revocable.
- **Connection hashes** — generated on the server with
  `manage.py generate_connection_hash`; only a salted hash is stored. A hash
  can be reused to reconnect another computer to the same account and can be
  revoked permanently.
- **Desktop token storage** — encrypted with Windows DPAPI in
  `%LOCALAPPDATA%\NASS\sync_config.json`. On non-Windows systems the fallback
  is base64, which is obfuscation only.
- **Profile separation** — a source checkout runs as the `dev` profile, keeps
  its configuration in `%LOCALAPPDATA%\NASS-dev\`, and is blocked from
  contacting the production host. The frozen build runs as `prod` and uses
  `%LOCALAPPDATA%\NASS\`.
- **Audit trail** — logins, user changes, stock adjustments, sales, and
  deletions are written to `AuditLog`.

## Database safety on upgrade

A desktop update replaces files in `Program Files\NASS\` only. Shop data lives
in `%LOCALAPPDATA%\NASS\nass.sqlite3` and is never touched by the installer.

On first launch after an update, `desktop_app/startup_db.py`:

1. checks whether a migration is actually pending;
2. if so, takes a transactional snapshot with SQLite's online backup API;
3. verifies the snapshot with `PRAGMA integrity_check`;
4. keeps the newest five snapshots in `%LOCALAPPDATA%\NASS\backups\`;
5. runs migrations, and **refuses to start** if they fail, showing the backup
   path and rollback instructions.

## Scale and limits

- One shop, roughly 5&ndash;20 desktop devices.
- Sync payloads contain only changed rows, not the whole dataset.
- SQLite is sufficient for the server at this scale; MySQL and PostgreSQL are
  supported through environment variables for larger installations.
- The system is not multi-tenant. Running multiple shops means running
  multiple servers.
