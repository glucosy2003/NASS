"""Tests for Service / ServiceEntry / Expense sync (wire format + apply)."""

import sys
import tempfile
from pathlib import Path

from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DESKTOP_APP = _REPO_ROOT / "desktop_app"
if str(_DESKTOP_APP) not in sys.path:
    sys.path.insert(0, str(_DESKTOP_APP))

from django.test import TestCase  # noqa: E402

from sales.models import Expense, Service, ServiceEntry  # noqa: E402
from sales.sync import apply_changes, collect_changes  # noqa: E402
from sync import config as sync_config  # noqa: E402
from sync.config import SyncConfig  # noqa: E402
from sync.manager import SyncManager  # noqa: E402


class _EchoClient:
    """Captures pushed payload and pulls an empty reply."""

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
            "services": [],
            "service_entries": [],
            "expenses": [],
            "users": [],
        }


class ServicesPushTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        sync_config.config_dir = lambda: Path(self.tmpdir.name)
        self.service = Service.objects.create(name="Tyre Fitting", price="200.00")
        self.entry = ServiceEntry.objects.create(
            service=self.service, quantity="2", unit_price="200.00",
            total_amount="400.00", customer_name="Grace",
        )
        self.expense = Expense.objects.create(
            description="Transport", amount="50.00"
        )
        self.config = SyncConfig()
        self.config.server_url = "https://nass.example.com"
        self.config.username = "admin"
        self.config.set_token("tok123")
        self.config.device_id = "device-test-svc"

    def tearDown(self):
        self.tmpdir.cleanup()

    @mock.patch("sync.manager.NASSClient", _EchoClient)
    def test_push_carries_services_entries_and_expenses(self):
        manager = SyncManager(self.config)
        result = manager.run()
        self.assertTrue(result.ok, result.errors)

        pushed_services = manager.client.pushed["services"]
        self.assertEqual(len(pushed_services), 1)
        self.assertEqual(
            pushed_services[0]["external_id"], str(self.service.external_id)
        )

        pushed_entries = manager.client.pushed["service_entries"]
        self.assertEqual(len(pushed_entries), 1)
        self.assertEqual(
            pushed_entries[0]["service_external_id"], str(self.service.external_id)
        )
        self.assertEqual(pushed_entries[0]["total_amount"], "400.00")

        pushed_expenses = manager.client.pushed["expenses"]
        self.assertEqual(len(pushed_expenses), 1)
        self.assertEqual(
            pushed_expenses[0]["external_id"], str(self.expense.external_id)
        )
        self.assertEqual(pushed_expenses[0]["amount"], "50.00")


class ServicesApplyTests(TestCase):
    def setUp(self):
        self.service_ext = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        self.entry_ext = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        self.expense_ext = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"

    def _payload(self, services=None, entries=None, expenses=None):
        return {
            "categories": [],
            "items": [],
            "sales": [],
            "stock_adjustments": [],
            "partial_payments": [],
            "payment_records": [],
            "services": services or [],
            "service_entries": entries or [],
            "expenses": expenses or [],
            "users": [],
        }

    def test_apply_creates_service_entry_and_expense(self):
        report = apply_changes(
            self._payload(
                services=[
                    {
                        "external_id": self.service_ext,
                        "name": "Tyre Fitting",
                        "price": "200.00",
                        "deleted": False,
                        "updated_at": "2026-09-10T08:00:00+02:00",
                    }
                ],
                entries=[
                    {
                        "external_id": self.entry_ext,
                        "service_external_id": self.service_ext,
                        "date": "2026-09-10T09:00:00+02:00",
                        "quantity": "2",
                        "unit_price": "200.00",
                        "total_amount": "400.00",
                        "customer_name": "Grace",
                        "notes": "",
                        "deleted": False,
                        "updated_at": "2026-09-10T09:00:00+02:00",
                    }
                ],
                expenses=[
                    {
                        "external_id": self.expense_ext,
                        "date": "2026-09-10T10:00:00+02:00",
                        "description": "Transport",
                        "amount": "50.00",
                        "deleted": False,
                        "updated_at": "2026-09-10T10:00:00+02:00",
                    }
                ],
            )
        )
        self.assertEqual(report["services_created"], 1)
        self.assertEqual(report["service_entries_created"], 1)
        self.assertEqual(report["expenses_created"], 1)

        service = Service.objects.get(external_id=self.service_ext)
        entry = ServiceEntry.objects.get(external_id=self.entry_ext)
        expense = Expense.objects.get(external_id=self.expense_ext)
        self.assertEqual(service.price, 200)
        self.assertEqual(entry.service, service)
        self.assertEqual(entry.total_amount, 400)
        self.assertEqual(expense.amount, 50)

    def test_entries_and_expenses_idempotent(self):
        payload = self._payload(
            entries=[
                {
                    "external_id": self.entry_ext,
                    "service_external_id": None,
                    "date": "2026-09-10T09:00:00+02:00",
                    "quantity": "1",
                    "unit_price": "100.00",
                    "total_amount": "100.00",
                    "customer_name": "",
                    "notes": "",
                    "deleted": False,
                    "updated_at": "2026-09-10T09:00:00+02:00",
                }
            ],
            expenses=[
                {
                    "external_id": self.expense_ext,
                    "date": "2026-09-10T10:00:00+02:00",
                    "description": "X",
                    "amount": "10.00",
                    "deleted": False,
                    "updated_at": "2026-09-10T10:00:00+02:00",
                }
            ],
        )
        first = apply_changes(payload)
        # Missing service -> entry refused (no service yet).
        self.assertEqual(first["service_entries_created"], 0)
        self.assertEqual(first["expenses_created"], 1)
        second = apply_changes(payload)
        self.assertEqual(second["expenses_created"], 0)
        self.assertEqual(Expense.objects.filter(external_id=self.expense_ext).count(), 1)

    def test_service_lww(self):
        first_payload = self._payload(
            services=[
                {
                    "external_id": self.service_ext,
                    "name": "Tyre Fitting",
                    "price": "200.00",
                    "deleted": False,
                    "updated_at": "2026-09-01T08:00:00+02:00",
                }
            ]
        )
        newer = {
            "external_id": self.service_ext,
            "name": "Tyre Fitting Pro",
            "price": "250.00",
            "deleted": False,
            "updated_at": "2027-01-01T08:00:00+02:00",
        }
        older = {
            "external_id": self.service_ext,
            "name": "Old Echo",
            "price": "100.00",
            "deleted": False,
            "updated_at": "2026-07-01T08:00:00+02:00",
        }
        apply_changes(first_payload)
        apply_changes(self._payload(services=[newer]))
        service = Service.objects.get(external_id=self.service_ext)
        self.assertEqual(service.name, "Tyre Fitting Pro")
        self.assertEqual(service.price, 250)
        apply_changes(self._payload(services=[older]))
        service.refresh_from_db()
        self.assertEqual(service.name, "Tyre Fitting Pro")

    def test_collect_since_carries_entries_expenses(self):
        service = Service.objects.create(name="Fitting", price="100.00")
        entry = ServiceEntry.objects.create(
            service=service, quantity="1", unit_price="100.00", total_amount="100.00"
        )
        Expense.objects.create(description="Rent", amount="10.00")

        payload = collect_changes(since=None, caller_user=None, include_cost=True)
        self.assertTrue(
            any(s["external_id"] == str(service.external_id)
                for s in payload["services"])
        )
        self.assertTrue(
            any(e["external_id"] == str(entry.external_id)
                for e in payload["service_entries"])
        )
        self.assertEqual(len(payload["expenses"]), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()