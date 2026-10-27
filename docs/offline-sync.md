# Offline sync and the stock ledger

## Principles

1. **Every write is local first.** The desktop commits to SQLite before it
   tries the network. A sale is never lost because the connection dropped.
2. **The server is the shared record.** It applies changes from every device
   and returns everything the device is missing.
3. **Operations are idempotent.** Re-sending a row never duplicates it.
4. **Stock is additive.** Quantities change only through appended deltas, so
   two devices can sell the same item at the same time without losing stock.

## Local databases

| Build | Database | Config |
|---|---|---|
| Installed app | `%LOCALAPPDATA%\NASS\nass.sqlite3` | `%LOCALAPPDATA%\NASS\sync_config.json` |
| Source checkout | `database/nass.sqlite3` | `%LOCALAPPDATA%\NASS-dev\sync_config.json` |
| Central server | `database/nass.sqlite3` (or MySQL/PostgreSQL) | Environment variables |

On first run, the installed app copies the bundled clean template
`seed.sqlite3` to `%LOCALAPPDATA%\NASS\nass.sqlite3`. It never copies the
developer database.

## What synchronises

| Table | Direction | Conflict rule |
|---|---|---|
| Categories | Both | Last writer wins by `updated_at` |
| Items | Both | Last writer wins; stock is not taken from the row |
| Stock adjustments | Both | Additive, idempotent by `external_id` |
| Sales and sale lines | Both | Append-only, idempotent by `external_id` |
| Partial payments | Both | Append-only header; totals derived |
| Payment records | Both | Append-only |
| Services | Both | Last writer wins |
| Service entries | Both | Append-only |
| Expenses | Both | Append-only |
| Users | Both | Last writer wins; password hashes travel |

Not synchronised: API tokens, connection hashes, sync configuration, and audit
logs. Tokens are per device; audit entries are written by the server that
receives the action.

## Wire format

- Every syncable row carries `external_id`, `updated_at`, and `deleted`.
- Decimals are strings (`"100.50"`) to avoid float drift.
- Timestamps are ISO-8601 with a timezone.
- Cost and profit fields are included only when the pushing user is an admin.

## One sync pass

The desktop runs **push, then pull**.

### Push

1. Capture a cursor with the current time.
2. Collect rows changed since `last_push` (or all rows when a full push is
   pending).
3. `POST /api/sync/push/` with the collected changes.
4. If the server reports no errors, set `last_push` to the captured cursor.
   Otherwise keep the old cursor so the next pass retries.

Capturing the cursor *before* building the payload matters: rows created while
the request is in flight are newer than the cursor and are sent next time.
Using the response time would strand them permanently.

### Pull

1. Send `since = last_pull - 1 minute` (a deliberate overlap).
2. `POST /api/sync/pull/` returns changed rows and `server_time`.
3. Apply the rows locally, then set `last_pull = server_time`.

The overlap absorbs rows written on the server while the previous request was
in flight. The extra minute is safe because applying a row twice is idempotent.

### First pairing

A new desktop does a full pull (no `since`), restoring the whole dataset. It
then marks `initial_pull_done` and disables the pending full push, because it
now has an exact copy of the server.

## Idempotency and deterministic IDs

- Every row has a UUID `external_id`, generated on the device that created it.
  The server and every other device store the row under the same UUID.
- Sale stock effects use UUIDs derived from the sale line:

  ```
  sale delta:    uuid5(sale_item.external_id, "nass-sale-stock")
  restore delta: uuid5(sale_item.external_id, "nass-sale-delete-stock")
  opening:       uuid5(item.external_id, "nass-opening-stock")
  ```

  Receiving the same sale again rebuilds identical adjustments, which are
  skipped because the `external_id` already exists.

## Stock ledger invariant

```
Item.quantity_in_stock == sum(StockAdjustment.delta for that item)
```

`quantity_in_stock` is a cache. It is updated in the same transaction as the
delta so reads stay fast, but the ledger is authoritative.

Sources of deltas:

- item creation (opening stock);
- a sale (negative quantity per line);
- sale deletion (positive restore per line);
- a manual stock adjustment.

A plain item update cannot change `quantity_in_stock`; the API removes that
field from update requests. Use the stock endpoint, which appends a delta.

## Background sync

The desktop starts an auto-sync timer after pairing. The default interval is
one minute and is stored as `auto_sync_minutes` in the sync configuration.

- Sync runs in a worker thread; the UI stays responsive.
- The status bar shows Syncing, Synced, an error, or Not connected.
- A `401` clears the token and marks the device disconnected.
- Network errors and timeouts (15 seconds) are retried once.
- A manual sync can be started from the UI.

Because the protocol only sends changes, payloads stay small even with years of
sales history.

## Upgrades and the local database

Before running a pending migration, the desktop:

1. takes a transactional snapshot with SQLite's online backup API;
2. verifies it with `PRAGMA integrity_check`;
3. keeps the newest five in `%LOCALAPPDATA%\NASS\backups\`;
4. runs `migrate`;
5. refuses to open the GUI if migration fails.

The installer never touches `%LOCALAPPDATA%\NASS\`, so reinstalling or
upgrading cannot delete shop data.

## Repairing stock

Use the read-only report first:

**Server:**

```bash
cd backend
python manage.py rebuild_stock
```

**Desktop:**

```powershell
& "$env:ProgramFiles\NASS\NASS_v1.0.1.exe" --rebuild-stock
```

### Recompute the cache from the ledger

When `quantity_in_stock` disagrees with the deltas but the deltas are correct:

```bash
python manage.py rebuild_stock --recompute
```

This sets each cached quantity to the sum of its deltas. It does not create or
remove adjustments.

### Record authoritative opening balances

When the ledger is incomplete but the item quantities are correct (for example
after importing an old database):

```bash
python manage.py rebuild_stock --openings
```

This creates or updates the deterministic opening adjustment for every item so
the invariant holds. On the desktop, `--rebuild-stock` performs this step and
also flags a full push.

### Reset the server ledger before a full push

Only when you intend the desktop to become the source of truth:

```bash
python manage.py rebuild_stock --reset
```

This deletes all deltas and zeroes every quantity on the **server**. Then sync
the repaired desktop once so it pushes the complete ledger.

Recommended order for a mismatch:

1. Run `--rebuild-stock` on the desktop that holds the correct quantities.
2. Run `rebuild_stock --reset` on the server.
3. Sync that desktop once (full push).
4. Verify on the server with `rebuild_stock` (no flags).

Never reset the server ledger and then let an un-repaired desktop push, or the
wrong quantities become authoritative.

## New computer restore

1. Install NASS.
2. Open **Sync Settings &rarr; Connection Hash**.
3. Enter the server URL and the shop's reusable hash.
4. Connect.

The desktop creates or reconnects to the same account, receives a token, and
pulls the full dataset. The shop is operational again without copying files.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Always "Not connected" | No token or wrong URL | Re-pair or check Sync Settings |
| "Authentication failed" | Token revoked or account disabled | Sign in again; check the account |
| Push reports errors | Invalid row or permission problem | Check the per-table report; fix the row |
| Changes appear twice | A custom script bypassed `external_id` | Find and remove the duplicate row |
| Stock drifts after a repair | Wrong pass order | Follow the repair order above |
| Dev app refuses the server | Profile guard | Point it at a dev server; this is intentional |
| Sync is slow | Large initial pull or slow host | Normal on first run; later passes are incremental |

For a client-side trace, run the desktop from source and watch the terminal:

```powershell
.\venv\Scripts\python.exe desktop_app\main.py
```

The sync status and last error are also stored in `sync_config.json` in the
profile's configuration directory.
