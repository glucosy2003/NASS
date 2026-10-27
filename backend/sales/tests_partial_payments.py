"""Tests for PartialPayment / PaymentRecord sync (wire format + apply)."""

import sys
import tempfile
from pathlib import Path

from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DESKTOP_APP = _REPO_ROOT / "desktop_app"
if str(_DESKTOP_APP) not in sys.path:
    sys.path.insert(0, str(_DESKTOP_APP))

from django.test import TestCase  # noqa: E402

from sales.models import Category, Item, PartialPayment, PaymentRecord  # noqa: E402
from sales.sync import apply_changes, collect_changes  # noqa: E402
from sync import config as sync_config  # noqa: E402
from sync.config import SyncConfig  # noqa: E402
from sync.manager import SyncManager  # noqa: E402


def _iso(dt):
    return dt.isoformat()


class _EchoClient:
    """Captures the pushed payload and pulls an empty reply."""

    def __init__(self, server_url=None, token=None, device_id=None, timeout=None):
        self.device_id = device_id
        self.pushed = None

    def push(self, payload):
        payload["device_id"] = self.device_id
        self.pushed = dict(payload)
        return {"detail": "ok", "report": {}}

    def pull(self, since=None):
        return {
            "server_time": "2026-09-10T08:00:00+02:00",
            "categories": [],
            "items": [],
            "sales": [],
            "stock_adjustments": [],
            "partial_payments": [],
            "payment_records": [],
            "users": [],
        }


class PartialPaymentPushTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        sync_config.config_dir = lambda: Path(self.tmpdir.name)
        self.category = Category.objects.create(name="Tyres", size_required=False)
        self.item = Item.objects.create(
            name="Tyre 195",
            unit_price="150.00",
            cost_price="100.00",
            quantity_in_stock="20.000",
            category=self.category,
        )
        self.pp = PartialPayment.objects.create(
            item=self.item,
            quantity="2",
            unit_price="150.00",
            total_amount="300.00",
            customer_name="Grace",
        )
        self.pr = PaymentRecord.objects.create(partial_payment=self.pp, amount="100.00")
        self.config = SyncConfig()
        self.config.server_url = "https://nass.example.com"
        self.config.username = "admin"
        self.config.set_token("tok123")
        self.config.device_id = "device-test-pp"

    def tearDown(self):
        self.tmpdir.cleanup()

    @mock.patch("sync.manager.NASSClient", _EchoClient)
    def test_push_carries_partial_payments_and_records(self):
        manager = SyncManager(self.config)
        result = manager.run()
        self.assertTrue(result.ok, result.errors)

        pushed_pps = manager.client.pushed["partial_payments"]
        self.assertEqual(len(pushed_pps), 1)
        self.assertEqual(pushed_pps[0]["external_id"], str(self.pp.external_id))
        self.assertEqual(pushed_pps[0]["item_external_id"], str(self.item.external_id))
        self.assertFalse(pushed_pps[0]["collected"])

        pushed_prs = manager.client.pushed["payment_records"]
        self.assertEqual(len(pushed_prs), 1)
        self.assertEqual(pushed_prs[0]["external_id"], str(self.pr.external_id))
        self.assertEqual(
            pushed_prs[0]["partial_payment_external_id"], str(self.pp.external_id)
        )
        self.assertEqual(pushed_prs[0]["amount"], "100.00")


class PartialPaymentApplyTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Tyres", size_required=False)
        self.item = Item.objects.create(
            name="Tyre 195",
            unit_price="150.00",
            cost_price="100.00",
            quantity_in_stock="20.000",
            category=self.category,
        )
        self.pp_ext = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.pr_ext = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    def _payload(self, partial=None, records=None):
        return {
            "categories": [],
            "items": [],
            "sales": [],
            "stock_adjustments": [],
            "partial_payments": partial or [],
            "payment_records": records or [],
            "users": [],
        }

    def test_apply_creates_partial_and_payment_record(self):
        report = apply_changes(
            self._payload(
                partial=[
                    {
                        "external_id": self.pp_ext,
                        "item_external_id": str(self.item.external_id),
                        "quantity": "2",
                        "unit_price": "150.00",
                        "total_amount": "300.00",
                        "notes": "",
                        "customer_name": "Grace",
                        "collected": False,
                        "deleted": False,
                        "updated_at": _iso(self.item.updated_at),
                    }
                ],
                records=[
                    {
                        "external_id": self.pr_ext,
                        "partial_payment_external_id": self.pp_ext,
                        "amount": "100.00",
                        "deleted": False,
                    }
                ],
            )
        )
        self.assertEqual(report["partial_payments_created"], 1)
        self.assertEqual(report["payment_records_created"], 1)

        pp = PartialPayment.objects.get(external_id=self.pp_ext)
        self.assertEqual(pp.item, self.item)
        self.assertEqual(pp.total_amount, 300)
        self.assertEqual(float(pp.paid), 100.0)
        self.assertEqual(float(pp.balance), 200.0)
        self.assertTrue(pp.is_outstanding)

    def test_apply_payment_records_is_idempotent(self):
        payload = self._payload(
            partial=[
                {
                    "external_id": self.pp_ext,
                    "item_external_id": str(self.item.external_id),
                    "quantity": "1",
                    "unit_price": "150.00",
                    "total_amount": "150.00",
                    "customer_name": "",
                    "collected": False,
                    "deleted": False,
                    "updated_at": _iso(self.item.updated_at),
                }
            ],
            records=[
                {
                    "external_id": self.pr_ext,
                    "partial_payment_external_id": self.pp_ext,
                    "amount": "90.00",
                    "deleted": False,
                }
            ],
        )
        first = apply_changes(payload)
        second = apply_changes(payload)
        self.assertEqual(first["payment_records_created"], 1)
        self.assertEqual(second["payment_records_created"], 0)
        self.assertEqual(
            PaymentRecord.objects.filter(external_id=self.pr_ext).count(), 1
        )

    def test_apply_lww_keeps_newer_partial_header(self):
        base = {
            "external_id": self.pp_ext,
            "item_external_id": str(self.item.external_id),
            "quantity": "1",
            "unit_price": "150.00",
            "total_amount": "150.00",
            "notes": "",
            "customer_name": "Old",
            "collected": False,
            "deleted": False,
            "updated_at": "2026-09-01T10:00:00+02:00",
        }
        newer = dict(base, customer_name="Newer", collected=True,
                     updated_at="2027-01-01T10:00:00+02:00")
        older = dict(base, customer_name="Older echo",
                     updated_at="2026-08-01T10:00:00+02:00")

        apply_changes(self._payload(partial=[base]))
        pp = PartialPayment.objects.get(external_id=self.pp_ext)
        self.assertEqual(pp.customer_name, "Old")

        newer_report = apply_changes(self._payload(partial=[newer]))
        self.assertEqual(newer_report["partial_payments_updated"], 1)
        pp.refresh_from_db()
        self.assertEqual(pp.customer_name, "Newer")
        self.assertTrue(pp.collected)

        older_report = apply_changes(self._payload(partial=[older]))
        self.assertEqual(older_report["partial_payments_skipped"], 1)
        pp.refresh_from_db()
        self.assertEqual(pp.customer_name, "Newer")

    def test_collect_changes_since_carries_children(self):
        from sales.models import ROLE_ADMIN
        from sales.admin_auth import AdminAuthManager

        ok, _ = AdminAuthManager.create_admin_user(
            username="ppviewer",
            full_name="PP Viewer",
            email="ppviewer@test.local",
            password="pass1234",
            role=ROLE_ADMIN,
        )
        self.assertTrue(ok)

        self.pp = PartialPayment.objects.create(
            item=self.item, quantity="3", unit_price="50.00", total_amount="150.00"
        )
        self.pr = PaymentRecord.objects.create(partial_payment=self.pp, amount="50.00")

        payload = collect_changes(since=None, caller_user=None, include_cost=True)
        self.assertTrue(
            any(p["external_id"] == str(self.pp.external_id)
                for p in payload["partial_payments"])
        )
        self.assertTrue(
            any(r["external_id"] == str(self.pr.external_id)
                for r in payload["payment_records"])
        )

        # A later payment bumps the partial's updated_at; a since filter that
        # predates it must still carry the header and both records.
        later = PaymentRecord.objects.create(partial_payment=self.pp, amount="100.00")
        since = self.pr.updated_at
        payload = collect_changes(
            since=since
            - __import__("datetime").timedelta(seconds=1),
            caller_user=None,
            include_cost=True,
        )
        self.assertTrue(
            any(r["external_id"] == str(later.external_id)
                for r in payload["payment_records"])
        )


if __name__ == "__main__":
    import unittest

    unittest.main()