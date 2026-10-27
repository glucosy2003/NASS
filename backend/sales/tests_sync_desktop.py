"""Tests for the desktop sync package (desktop_app/sync).

These run under the Django test runner so the local SQLite "working copy"
behaviour can be exercised with a real (test) database while the HTTP client
is mocked. The package is imported from desktop_app/.
"""

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DESKTOP_APP = _REPO_ROOT / "desktop_app"
if str(_DESKTOP_APP) not in sys.path:
    sys.path.insert(0, str(_DESKTOP_APP))

from django.contrib.auth.hashers import make_password  # noqa: E402
from django.test import TestCase  # noqa: E402

from sales.models import (
    Category,
    Item,
    ROLE_ADMIN,
    AdminUser,
    Service,
    ServiceEntry,
)  # noqa: E402
from sales.admin_auth import AdminAuthManager  # noqa: E402
from sales.sync import apply_changes, collect_changes  # noqa: E402
from sync import config as sync_config  # noqa: E402
from sync import crypto  # noqa: E402
from sync import profile  # noqa: E402
from sync.client import ApiError, NASSClient, NotAuthenticated  # noqa: E402
from sync.config import SyncConfig  # noqa: E402
from sync.manager import SyncManager  # noqa: E402
from sync.profile import ProfileViolation  # noqa: E402


class CryptoKitTests(unittest.TestCase):
    def test_roundtrip(self):
        encoded = crypto.encode("super-secret-token")
        self.assertTrue(encoded)
        self.assertEqual(crypto.decode(encoded), "super-secret-token")
        self.assertNotIn("super-secret-token", encoded)

    def test_empty_and_garbage(self):
        self.assertEqual(crypto.encode(""), "")
        self.assertEqual(crypto.decode(""), "")
        self.assertEqual(crypto.decode("garbage:mangled"), "")


class ConfigPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        sync_config.config_dir = lambda: Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_save_load_roundtrip_with_encrypted_token(self):
        cfg = SyncConfig()
        cfg.server_url = "https://nass.example.com"
        cfg.username = "admin"
        cfg.set_token("plaintext-token")
        cfg.last_pull = "2026-09-09T10:00:00+00:00"
        cfg.initial_pull_done = True
        cfg.save()

        loaded = SyncConfig.load()
        self.assertEqual(loaded.server_url, "https://nass.example.com")
        self.assertEqual(loaded.username, "admin")
        self.assertEqual(loaded.token_plaintext, "plaintext-token")
        self.assertEqual(loaded.last_pull, "2026-09-09T10:00:00+00:00")
        self.assertTrue(loaded.initial_pull_done)
        self.assertTrue(loaded.is_configured)

    def test_is_configured_requires_server_and_token(self):
        self.assertFalse(SyncConfig().is_configured)

    def test_clear_token_disables_connection(self):
        cfg = SyncConfig()
        cfg.server_url = "https://nass.example.com"
        cfg.set_token("x")
        self.assertTrue(cfg.is_configured)
        cfg.clear_token()
        self.assertFalse(cfg.is_configured)


class NASSClientTests(unittest.TestCase):
    def _fake_response(self, status=200, json=None):
        resp = mock.Mock()
        resp.status_code = status
        resp.content = json is not None
        if json is not None:
            resp.json.return_value = json
        else:
            resp.content = b""
        resp.text = str(json or "")
        return resp

    @mock.patch("sync.client.requests.request")
    def test_auth_header_and_push_device_id(self, request_mock):
        request_mock.return_value = self._fake_response(json={"detail": "ok", "report": {}})
        client = NASSClient(
            server_url="https://nass.example.com/",
            token="tok123",
            device_id="dev-1",
        )
        client.push({"sales": []})

        args, kwargs = request_mock.call_args
        method, url = args
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://nass.example.com/api/sync/push/")
        self.assertEqual(kwargs["headers"]["Authorization"], "Token tok123")
        self.assertEqual(kwargs["json"]["device_id"], "dev-1")

    @mock.patch("sync.client.requests.request")
    def test_401_raises_not_authenticated(self, request_mock):
        request_mock.return_value = self._fake_response(status=401)
        client = NASSClient(server_url="https://nass.example.com", token="bad")
        with self.assertRaises(NotAuthenticated):
            client.pull()

    @mock.patch("sync.client.requests.request")
    def test_connection_error_becomes_api_error(self, request_mock):
        request_mock.side_effect = __import__("requests").ConnectionError("offline")
        client = NASSClient(server_url="https://nass.example.com", token="x")
        with self.assertRaises(ApiError):
            client.health()

    @mock.patch("sync.client.requests.request")
    def test_pair_sends_hash_to_auth_pair(self, request_mock):
        request_mock.return_value = self._fake_response(
            json={
                "detail": "Paired.",
                "token": "tok-new",
                "device_id": "uuid-1",
                "username": "desk-admin",
            }
        )
        client = NASSClient(server_url="https://nass.example.com")
        resp = client.pair(
            connection_hash="NASS-ABCDEF1234567890",
            username="desk-admin",
            password_hash="pbkdf2_sha256$fake",
            device_name="POS-1",
        )

        args, kwargs = request_mock.call_args
        method, url = args
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://nass.example.com/api/auth/pair/")
        self.assertEqual(kwargs["json"]["hash"], "NASS-ABCDEF1234567890")
        self.assertEqual(kwargs["json"]["username"], "desk-admin")
        self.assertEqual(kwargs["json"]["password_hash"], "pbkdf2_sha256$fake")
        self.assertEqual(kwargs["json"]["device_name"], "POS-1")
        # Anonymous endpoint — no auth header on the pair request.
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertEqual(resp["token"], "tok-new")


class FakeClient:
    """In-memory stand-in for NASSClient — records calls, serves canned replies.

    Mirrors the real client's push() behaviour of attaching the device id to
    the outgoing payload.
    """

    def __init__(self, server_url=None, token=None, device_id=None, timeout=None):
        self.device_id = device_id
        self.pushed = None
        self.pull_since = None

    def push(self, payload):
        payload["device_id"] = self.device_id
        self.pushed = dict(payload)
        return {"detail": "ok", "report": {}}

    def pull(self, since=None):
        self.pull_since = since
        return {
            "server_time": "2026-09-10T08:00:00+02:00",
            "categories": [
                {
                    "external_id": "77777777-7777-7777-7777-777777777777",
                    "name": "Spark Plugs",
                    "size_required": False,
                    "deleted": False,
                    "updated_at": "2026-09-10T08:00:00+02:00",
                }
            ],
            "items": [],
            "sales": [],
            "stock_adjustments": [],
            "users": [],
        }


class SyncManagerTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        sync_config.config_dir = lambda: Path(self.tmpdir.name)

        ok, user = AdminAuthManager.create_admin_user(
            username="admin",
            full_name="Admin",
            email="admin@test.local",
            password="pass1234",
            role=ROLE_ADMIN,
        )
        self.assertTrue(ok)

        self.category = Category.objects.create(name="Tyres", size_required=False)
        self.item = Item.objects.create(
            name="Tyre 195",
            unit_price="150.00",
            cost_price="100.00",
            quantity_in_stock="20.000",
            category=self.category,
        )

        self.config = SyncConfig()
        self.config.server_url = "https://nass.example.com"
        self.config.username = "admin"
        self.config.set_token("tok123")
        self.config.device_id = "device-test-1"

    def tearDown(self):
        self.tmpdir.cleanup()

    @mock.patch("sync.manager.NASSClient", FakeClient)
    def test_full_run_pushes_then_pulls(self):
        manager = SyncManager(self.config)
        result = manager.run()

        self.assertTrue(result.ok, result.errors)

        # push carried the local item (external_id present, updated_at bumped)
        pushed_items = manager.client.pushed["items"]
        self.assertEqual(pushed_items[0]["external_id"], str(self.item.external_id))
        # push carried local stock_adjustments key (empty is fine)
        self.assertIn("stock_adjustments", manager.client.pushed)
        # device_id was attached by the client
        self.assertEqual(manager.client.pushed["device_id"], "device-test-1")

        # pull arguments: incremental since last_pull (None on first run)
        self.assertIsNone(manager.client.pull_since)

        # application of the pulled category happened locally
        self.assertTrue(Category.objects.filter(name="Spark Plugs").exists())

        # state persisted on the config
        self.assertEqual(self.config.last_pull, "2026-09-10T08:00:00+02:00")
        self.assertTrue(self.config.initial_pull_done)
        self.assertTrue(self.config.last_push)
        saved = SyncConfig.load()
        self.assertTrue(saved.initial_pull_done)

    @mock.patch("sync.manager.NASSClient", FakeClient)
    def test_initial_pull_is_full(self):
        manager = SyncManager(self.config)
        result = manager.initial_pull()
        self.assertTrue(result.ok, result.errors)
        self.assertIsNone(manager.client.pull_since)
        self.assertTrue(Category.objects.filter(name="Spark Plugs").exists())

    @mock.patch("sync.manager.NASSClient", FakeClient)
    def test_second_run_uses_incremental_pull_with_overlap(self):
        manager = SyncManager(self.config)
        first = manager.run()
        self.assertTrue(first.ok, first.errors)

        # Second pass: pull uses last server_time minus the 1-minute overlap.
        second = manager.run()
        self.assertTrue(second.ok, second.errors)
        self.assertEqual(
            manager.client.pull_since, "2026-09-10T07:59:00+02:00"
        )

    @mock.patch("sync.manager.NASSClient")
    def test_push_cursor_kept_on_report_errors(self, client_cls):
        class ErroringClient(FakeClient):
            def push(self, payload):
                self.pushed = dict(payload)
                return {"detail": "ok", "report": {"errors": ["sales:boom"]}}

        client_cls.return_value = ErroringClient()
        self.config.last_push = "2026-09-10T08:00:00+02:00"
        manager = SyncManager(self.config)
        result = manager.run()
        self.assertFalse(result.ok)
        # Cursor must NOT advance past the failed rows so they retry next pass.
        self.assertEqual(
            self.config.last_push, "2026-09-10T08:00:00+02:00"
        )

    @mock.patch("sync.manager.NASSClient", FakeClient)
    def test_pending_full_push_forces_since_none_and_clears_flag(self):
        self.config.pending_full_push = True
        manager = SyncManager(self.config)
        result = manager.run()
        self.assertTrue(result.ok, result.errors)
        # Fresh installs building a full heal-push explicitly request it.
        manager.client.pull_since  # first run: no last_pull yet -> full pull
        self.assertFalse(self.config.pending_full_push)
        self.assertTrue(self.config.last_push)

    @mock.patch("sync.manager.NASSClient")
    def test_auth_failure_clears_token(self, client_cls):
        from sync.client import NotAuthenticated as NA

        client_cls.return_value = mock.Mock(
            push=mock.Mock(side_effect=NA("bad token", 401, None)),
            pull=mock.Mock(side_effect=NA("bad token", 401, None)),
        )
        manager = SyncManager(self.config)
        result = manager.run()
        self.assertFalse(result.ok)
        self.assertIn("Authentication", result.message)
        self.assertFalse(self.config.is_configured)


class SyncConnectionTrackingTests(TestCase):
    """A sync pass that merely reaches the server counts as connected, even
    when individual rows failed (indicator stays green)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        sync_config.config_dir = lambda: Path(self.tmpdir.name)

        ok, user = AdminAuthManager.create_admin_user(
            username="admin",
            full_name="Admin",
            email="admin@test.local",
            password="pass1234",
            role=ROLE_ADMIN,
        )
        self.assertTrue(ok)

        self.config = SyncConfig()
        self.config.server_url = "https://nass.example.com"
        self.config.username = "admin"
        self.config.set_token("tok123")
        self.config.device_id = "device-test-2"

    def tearDown(self):
        self.tmpdir.cleanup()

    @mock.patch("sync.manager.NASSClient", FakeClient)
    def test_successful_run_marks_connected(self):
        manager = SyncManager(self.config)
        result = manager.run()
        self.assertTrue(result.connected)
        self.assertTrue(self.config.last_sync_connected)

    @mock.patch("sync.manager.NASSClient")
    def test_row_errors_stay_connected_but_not_ok(self, client_cls):
        class ErroringClient(FakeClient):
            def push(self, payload):
                self.pushed = dict(payload)
                return {"detail": "ok", "report": {"errors": ["sales:x"]}}

        client_cls.return_value = ErroringClient()
        manager = SyncManager(self.config)
        result = manager.run()
        # Connection reached the server...
        self.assertTrue(result.connected)
        self.assertTrue(self.config.last_sync_connected)
        # ...but the pass still reports the row-level failure.
        self.assertFalse(result.ok)

    @mock.patch("sync.manager.NASSClient")
    def test_unreachable_server_marks_disconnected(self, client_cls):
        client_cls.return_value = mock.Mock(
            push=mock.Mock(side_effect=ApiError("offline")),
            pull=mock.Mock(side_effect=ApiError("offline")),
        )
        manager = SyncManager(self.config)
        result = manager.run()
        self.assertFalse(result.connected)
        self.assertFalse(self.config.last_sync_connected)


class ServiceEntryDeletePropagationTests(TestCase):
    def _base_payload(self):
        return {
            "categories": [],
            "items": [],
            "sales": [],
            "stock_adjustments": [],
            "partial_payments": [],
            "payment_records": [],
            "services": [],
            "service_entries": [],
            "expenses": [],
            "users": [],
        }

    def test_deleted_flag_propagates_to_existing_row(self):
        service = Service.objects.create(name="Fitting", price="5000.00")
        entry = ServiceEntry.objects.create(
            external_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            service=service,
            date="2026-09-10T10:00:00+02:00",
            quantity="1",
            unit_price="5000.00",
            total_amount="5000.00",
        )

        payload = self._base_payload()
        payload["service_entries"] = [
            {
                "external_id": str(entry.external_id),
                "service_external_id": str(service.external_id),
                "date": "2026-09-10T10:00:00+02:00",
                "quantity": "1",
                "unit_price": "5000.00",
                "total_amount": "5000.00",
                "customer_name": "",
                "notes": "",
                "deleted": True,
                "updated_at": "2026-09-11T08:00:00+02:00",
            }
        ]
        report = apply_changes(payload, caller_user=None)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["service_entries_deleted"], 1)
        entry.refresh_from_db()
        self.assertTrue(entry.deleted)

    def test_new_entry_arrives_pre_deleted(self):
        service = Service.objects.create(name="Fitting", price="5000.00")
        payload = self._base_payload()
        payload["service_entries"] = [
            {
                "external_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "service_external_id": str(service.external_id),
                "date": "2026-09-10T10:00:00+02:00",
                "quantity": "2",
                "unit_price": "5000.00",
                "total_amount": "10000.00",
                "customer_name": "",
                "notes": "",
                "deleted": True,
                "updated_at": "2026-09-11T08:00:00+02:00",
            }
        ]
        report = apply_changes(payload, caller_user=None)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["service_entries_created"], 1)
        entry = ServiceEntry.objects.get(
            external_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        )
        self.assertTrue(entry.deleted)


class NaturalKeyConvergenceTests(TestCase):
    """Production scenario: the desktop and the server were seeded separately,
    so the same username / category name exists under a different external_id.

    apply_changes must converge these into one row instead of failing on the
    unique constraint — otherwise the website keeps the stale account (web login
    only works with the old/testing password) and every sync pass returns errors
    (dashboard stays at "Sync inactive" even though the connection succeeded).
    """

    def _make_owner(self):
        owner = AdminUser.objects.create(
            username="sync-owner", email="owner@test.local", is_active=True,
        )
        owner.set_password("ownerpw")
        owner.save()
        return owner

    def _payload(self, users=(), categories=()):
        return {
            "categories": list(categories),
            "items": [],
            "sales": [],
            "stock_adjustments": [],
            "partial_payments": [],
            "payment_records": [],
            "services": [],
            "service_entries": [],
            "expenses": [],
            "users": list(users),
        }

    def test_same_username_converges_and_new_password_wins(self):
        owner = self._make_owner()
        stale = AdminUser.objects.create(
            external_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            username="admin",
            email="admin@old.local",
            role=ROLE_ADMIN,
            is_active=True,
        )
        stale.set_password("oldpassword")
        stale.save()

        report = apply_changes(
            self._payload(users=[{
                "external_id": "22222222-2222-2222-2222-222222222222",
                "username": "admin",
                "full_name": "Shop Admin",
                "email": "admin@new.local",
                "password_hash": make_password("newpassword"),
                "role": ROLE_ADMIN,
                "is_active": True,
                "deleted": False,
                "desktop_password_required": False,
                "updated_at": "2026-09-01T08:00:00+00:00",
            }]),
            caller_user=owner,
        )

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["users_created"] + report["users_updated"], 1)
        # Exactly one "admin" after convergence, holding the new identity.
        self.assertEqual(AdminUser.objects.filter(username="admin").count(), 1)
        admin = AdminUser.objects.get(username="admin")
        self.assertEqual(
            str(admin.external_id), "22222222-2222-2222-2222-222222222222"
        )
        self.assertFalse(admin.check_password("oldpassword"))
        self.assertTrue(admin.check_password("newpassword"))

    def test_same_category_name_converges(self):
        owner = self._make_owner()
        Category.objects.create(
            external_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            name="Car Tyres",
            size_required=True,
        )

        report = apply_changes(
            self._payload(categories=[{
                "external_id": "44444444-4444-4444-4444-444444444444",
                "name": "Car Tyres",
                "size_required": True,
                "deleted": False,
                "updated_at": "2026-09-01T08:00:00+00:00",
            }]),
            caller_user=owner,
        )

        self.assertEqual(report["errors"], [])
        self.assertEqual(Category.objects.filter(name="Car Tyres").count(), 1)
        cat = Category.objects.get(name="Car Tyres")
        self.assertEqual(
            str(cat.external_id), "44444444-4444-4444-4444-444444444444"
        )

    def test_collect_changes_always_includes_users(self):
        self._make_owner()
        stale = AdminUser.objects.create(
            username="admin", email="admin@test.local", role=ROLE_ADMIN,
        )
        stale.set_password("pw")
        stale.save()
        # Make every user "old" so a since-filter would exclude them.
        AdminUser.objects.all().update(updated_at="2020-01-01T00:00:00+00:00")

        changes = collect_changes(
            since="2026-09-01T00:00:00+00:00", caller_user=None
        )
        usernames = {u["username"] for u in changes["users"]}
        self.assertIn("admin", usernames)
        self.assertIn("sync-owner", usernames)


class BuildProfileInterlockTests(unittest.TestCase):
    """The production and development desktop apps must never talk to each
    other. These tests pin the guarantee: a dev run cannot reach the live
    server, and the two builds keep separate credentials."""

    PROD_HOST = profile.PRODUCTION_SERVER_URL
    PROD_DOMAIN = urlparse(PROD_HOST).hostname

    def test_running_from_source_is_the_dev_profile(self):
        # The test suite itself runs unfrozen, i.e. it is the dev build.
        self.assertEqual(profile.current_profile(), profile.PROFILE_DEV)
        self.assertTrue(profile.is_development())

    def test_frozen_build_is_the_prod_profile(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(profile.current_profile(), profile.PROFILE_PROD)
            self.assertFalse(profile.is_development())

    def test_dev_may_not_use_the_production_server(self):
        with self.assertRaises(ProfileViolation):
            profile.assert_allowed(self.PROD_HOST, profile.PROFILE_DEV)

    def test_client_refuses_to_build_against_production_when_dev(self):
        with mock.patch("sync.client.profile.assert_allowed", side_effect=ProfileViolation("blocked")):
            with self.assertRaises(ProfileViolation):
                NASSClient(server_url=self.PROD_HOST)

    def test_prod_may_use_the_production_server(self):
        self.assertEqual(
            profile.assert_allowed(self.PROD_HOST, profile.PROFILE_PROD),
            self.PROD_HOST,
        )

    def test_dev_may_use_its_own_sandbox_server(self):
        for url in ("http://127.0.0.1:8000", "https://nass-dev.example.com"):
            self.assertEqual(profile.assert_allowed(url, profile.PROFILE_DEV), url)

    def test_production_host_detected_through_url_tricks(self):
        for url in (
            f"https://{self.PROD_DOMAIN}",
            f"http://{self.PROD_DOMAIN}",
            f"https://{self.PROD_DOMAIN}:443/api/",
            f"https://{self.PROD_DOMAIN.upper()}/",
        ):
            self.assertTrue(profile.is_production_server(url), url)
        for url in ("http://127.0.0.1:8000", "", f"https://not-{self.PROD_DOMAIN}"):
            self.assertFalse(profile.is_production_server(url), url)

    def test_each_profile_gets_its_own_config_folder(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(profile.config_dir_name(), "NASS")
        self.assertEqual(profile.config_dir_name(), "NASS-dev")
        self.assertNotEqual(
            profile.config_dir_name(), "NASS", "dev must not share prod config"
        )

    def test_default_server_url_differs_per_profile(self):
        self.assertEqual(
            profile.default_server_url(profile.PROFILE_PROD), self.PROD_HOST
        )
        self.assertNotEqual(
            profile.default_server_url(profile.PROFILE_DEV),
            profile.default_server_url(profile.PROFILE_PROD),
        )
        with mock.patch.dict(os.environ, {"NASS_DEV_SERVER_URL": "http://localhost:9000"}):
            self.assertEqual(
                profile.default_server_url(profile.PROFILE_DEV), "http://localhost:9000"
            )

    def test_sync_manager_reports_blocked_without_any_request(self):
        # Isolate config_dir so the test never writes to the real
        # %LOCALAPPDATA% dev/prod profile folder.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sync_config, "config_dir", lambda: Path(tmp)):
                cfg = SyncConfig()
                cfg.server_url = self.PROD_HOST  # e.g. hand-edited config file
                cfg.set_token("tok")
                with mock.patch(
                    "sync.manager.profile.assert_allowed",
                    side_effect=ProfileViolation("blocked"),
                ):
                    with mock.patch("sync.client.requests.request") as request_mock:
                        manager = SyncManager(cfg)
                        result = manager.run()
                request_mock.assert_not_called()
                self.assertFalse(result.ok)
                self.assertFalse(result.connected)
                self.assertIn("Sync blocked", result.message)
                self.assertFalse(cfg.last_sync_connected)

    def test_sync_manager_blocks_the_full_pull_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sync_config, "config_dir", lambda: Path(tmp)):
                cfg = SyncConfig()
                cfg.server_url = self.PROD_HOST
                cfg.set_token("tok")
                with mock.patch(
                    "sync.manager.profile.assert_allowed",
                    side_effect=ProfileViolation("blocked"),
                ):
                    with mock.patch("sync.client.requests.request") as request_mock:
                        result = SyncManager(cfg).initial_pull()
                request_mock.assert_not_called()
                self.assertFalse(result.connected)
                self.assertFalse(cfg.last_sync_connected)


class SeedDatabaseTests(unittest.TestCase):
    """A fresh shop install is seeded from database/seed.sqlite3. It must stay
    empty, or a developer's working data would ship inside the installer."""

    def setUp(self):
        self.seed = _REPO_ROOT / "database" / "seed.sqlite3"
        if not self.seed.exists():
            self.skipTest("seed.sqlite3 not present")

    def test_seed_exists_and_is_not_the_dev_database(self):
        dev = _REPO_ROOT / "database" / "nass.sqlite3"
        self.assertNotEqual(self.seed.resolve(), dev.resolve())

    def test_seed_contains_no_shop_data(self):
        import sqlite3

        con = sqlite3.connect(str(self.seed))
        try:
            for table in (
                "sales_adminuser",
                "sales_item",
                "sales_sale",
                "sales_saleitem",
                "sales_stockadjustment",
                "sales_partialpayment",
                "sales_paymentrecord",
                "sales_service",
                "sales_serviceentry",
                "sales_expense",
                "sales_connectioncredential",
                "sales_apitoken",
            ):
                with self.subTest(table=table):
                    self.assertEqual(
                        con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                        0,
                        f"{table} must be empty in the seed",
                    )
        finally:
            con.close()

    def test_seed_is_fully_migrated(self):
        import sqlite3

        con = sqlite3.connect(str(self.seed))
        try:
            applied = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM django_migrations WHERE app='sales'"
                )
            }
        finally:
            con.close()
        latest = {
            p.stem for p in (_REPO_ROOT / "backend" / "sales" / "migrations").glob("0*.py")
        }
        self.assertTrue(latest)
        self.assertEqual(
            latest - applied, set(), "seed DB is behind the migration files"
        )

    def test_seed_has_default_categories_so_install_is_usable(self):
        import sqlite3

        con = sqlite3.connect(str(self.seed))
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM sales_category WHERE deleted=0"
            ).fetchone()[0]
        finally:
            con.close()
        self.assertGreater(n, 0)


if __name__ == "__main__":
    unittest.main()