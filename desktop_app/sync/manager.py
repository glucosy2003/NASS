"""SyncManager: orchestrates one sync pass between the local SQLite working
copy and the central server, reusing `sales/sync.py` for the wire format.

Order is always PUSH then PULL (the architecture's pull-then-push protocol,
executed push-first here so local sales reach the server before new data is
downloaded — both are safe because every op is idempotent).
"""

from datetime import datetime, timedelta, timezone

from sales.models import AdminUser, ROLE_ADMIN
from sales.sync import apply_changes, collect_changes
from sync import profile
from sync.client import ApiError, NASSClient, NotAuthenticated
from sync.config import SyncConfig
from sync.profile import ProfileViolation


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class SyncError(Exception):
    pass


class SyncResult:
    def __init__(self):
        self.ok = False
        self.connected = False
        self.push_report = {}
        self.pull_report = {}
        self.errors = []
        self.message = ""
        self.server_time = None
        self.started_at = None
        self.finished_at = None

    @property
    def total_changes(self):
        pushed = sum(
            self.push_report.get(k, 0)
            for k in (
                "categories_created",
                "categories_updated",
                "items_created",
                "items_updated",
                "stock_adjustments",
                "sales_created",
                "sales_deleted",
                "partial_payments_created",
                "partial_payments_updated",
                "payment_records_created",
                "services_created",
                "services_updated",
                "service_entries_created",
                "service_entries_deleted",
                "expenses_created",
                "users_created",
                "users_updated",
            )
        )
        pulled = sum(
            self.pull_report.get(k, 0)
            for k in (
                "categories_created",
                "categories_updated",
                "items_created",
                "items_updated",
                "stock_adjustments",
                "sales_created",
                "partial_payments_created",
                "partial_payments_updated",
                "payment_records_created",
                "services_created",
                "services_updated",
                "service_entries_created",
                "expenses_created",
                "users_created",
                "users_updated",
            )
        )
        return pushed + pulled


class SyncManager:
    def __init__(self, config):
        self.config = config
        # A dev run pointed at the production host is refused BEFORE any
        # request is built. The error is carried into run()/initial_pull() so
        # the failure is reported and persisted normally, instead of escaping
        # the constructor and leaving a stale "connected" flag on disk.
        self.profile_error = None
        try:
            self.client = NASSClient(
                server_url=config.server_url,
                token=config.token_plaintext,
                device_id=config.device_id,
            )
        except ProfileViolation as exc:
            self.client = None
            self.profile_error = exc

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _blocked(self, result):
        """Record a profile violation on `result` and finish it. Returns it."""
        result.connected = False
        result.ok = False
        result.errors = [str(self.profile_error)]
        result.message = "Sync blocked (wrong build profile)"
        result.finished_at = _now_iso()
        self._persist(result)
        return result

    def _include_cost(self):
        """Only admin-created push payloads carry cost/profit fields."""
        username = (self.config.username or "").strip()
        if username:
            try:
                user = AdminUser.objects.filter(username=username).first()
            except Exception:  # noqa: BLE001
                user = None
            if user is not None:
                return user.role == ROLE_ADMIN
        return True

    def _push(self):
        # Capture the cursor BEFORE the payload is built, and only advance it
        # once every row was accepted. Rows created while the request is in
        # flight keep an updated_at newer than this timestamp, so they are
        # picked up by the next (since=started) pass; using response-time as
        # the cursor would permanently strand them. On report errors the cursor
        # is left untouched so the next pass retries the same rows.
        started = _now_iso()
        since = None if self.config.pending_full_push else self.config.last_push
        caller_user = None
        username = (self.config.username or "").strip()
        if username:
            try:
                caller_user = AdminUser.objects.filter(username=username).first()
            except Exception:  # noqa: BLE001
                pass
        changes = collect_changes(
            since=since, caller_user=caller_user, include_cost=self._include_cost()
        )
        response = self.client.push(dict(changes))
        report = response.get("report", {})
        if not (report.get("errors") or []):
            self.config.last_push = started
        self.config.pending_full_push = False
        return report

    def _pull(self, since=None):
        """since=None means a full pull (whole dataset)."""
        payload = self.client.pull(since=since)
        report = apply_changes(payload, caller_user=None)
        self.config.last_pull = payload.get("server_time") or self.config.last_pull
        self.config.initial_pull_done = True
        return report, payload.get("server_time")

    def _pull_cursor(self):
        """Incremental pull start with a 1-minute overlap, to absorb rows
        written on the server while the previous request was in flight."""
        since = self.config.last_pull
        if since:
            try:
                return (
                    datetime.fromisoformat(since) - timedelta(minutes=1)
                ).isoformat()
            except (ValueError, TypeError):
                return None
        return None

    # ------------------------------------------------------------------
    # public entry points
    # ------------------------------------------------------------------
    def initial_pull(self):
        """Plug-and-play restore: pull everything from the server."""
        result = SyncResult()
        result.started_at = _now_iso()
        try:
            if self.profile_error is not None:
                return self._blocked(result)
            if not self.config.is_configured:
                raise SyncError("Not configured: no server/login yet.")
            report, server_time = self._pull(since=None)
            result.connected = True
            result.pull_report = report
            result.server_time = server_time
            result.errors = report.get("errors") or []
            result.ok = not result.errors
            result.message = "Full pull OK" if result.ok else "Full pull had errors"
            # The desktop now holds an exact copy of the server dataset, so a
            # one-time full push is unnecessary on this fresh pairing.
            self.config.pending_full_push = False
        except NotAuthenticated as exc:
            result.errors = [f"Authentication failed: {exc}"]
            result.message = "Authentication failed"
            self.config.clear_token()
        except (ApiError, SyncError) as exc:
            result.errors = [str(exc)]
            result.message = "Full pull failed"
        except Exception as exc:  # noqa: BLE001
            result.errors = [f"Unexpected error: {exc}"]
            result.message = "Full pull failed"
        finally:
            result.finished_at = _now_iso()
            self._persist(result)
        return result

    def run(self):
        """One full sync pass: PUSH local changes, then PULL remote changes."""
        result = SyncResult()
        result.started_at = _now_iso()
        try:
            if self.profile_error is not None:
                return self._blocked(result)
            if not self.config.is_configured:
                raise SyncError("Not configured: no server/login yet.")
            result.push_report = self._push()
            result.pull_report, result.server_time = self._pull(
                since=self._pull_cursor()
            )
            result.connected = True

            errors = (result.push_report.get("errors") or []) + (
                result.pull_report.get("errors") or []
            )
            result.errors = errors
            result.ok = not errors
            result.message = "Synced OK" if result.ok else "Sync had errors"
        except NotAuthenticated as exc:
            result.errors = [f"Authentication failed: {exc}"]
            result.message = "Authentication failed"
            self.config.clear_token()
        except (ApiError, SyncError) as exc:
            result.errors = [str(exc)]
            result.message = "Sync failed"
        except Exception as exc:  # noqa: BLE001
            result.errors = [f"Unexpected error: {exc}"]
            result.message = "Sync failed"
        finally:
            result.finished_at = _now_iso()
            self._persist(result)
        return result

    def _persist(self, result):
        self.config.last_sync_status = result.message
        self.config.last_sync_at = result.finished_at
        self.config.last_sync_connected = result.connected
        self.config.save()