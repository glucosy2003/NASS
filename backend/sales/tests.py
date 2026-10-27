from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from sales.admin_auth import AdminAuthManager
from sales.models import (
    ROLE_ADMIN,
    ROLE_CASHIER,
    AdminUser,
    AuditLog,
    Category,
    Item,
    Sale,
    SaleItem,
    StockAdjustment,
)
from sales.sync import apply_changes, collect_changes


class AdminAuthManagerTests(TestCase):
    def setUp(self):
        self.admin = AdminUser(
            username="admin", full_name="System Administrator", email="admin@test.local"
        )
        self.admin.set_password("1234")
        self.admin.save()

    def test_authenticate_admin_success(self):
        user = AdminAuthManager.authenticate_admin("admin", "1234")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "admin")

    def test_authenticate_admin_wrong_password(self):
        user = AdminAuthManager.authenticate_admin("admin", "wrong")
        self.assertIsNone(user)

    def test_change_password_minimum_length_is_4(self):
        success, message = AdminAuthManager.change_password(self.admin, "1234", "123")
        self.assertFalse(success)
        self.assertIn("at least 4", message)

    def test_change_password_success(self):
        success, message = AdminAuthManager.change_password(self.admin, "1234", "5678")
        self.assertTrue(success)
        self.assertIn("successfully", message.lower())

        refreshed = AdminUser.objects.get(pk=self.admin.pk)
        self.assertTrue(refreshed.check_password("5678"))


class SalesCalculationTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Tyres", size_required=False)
        self.item = Item.objects.create(
            name="Sample Tyre",
            unit_price=Decimal("100.25"),
            cost_price=Decimal("70.10"),
            quantity_in_stock=10,
            category=self.category,
        )

    def test_sale_item_profit_saved_correctly(self):
        sale = Sale.objects.create(total_amount=Decimal("0.00"), total_profit=Decimal("0.00"))
        sale_item = SaleItem.objects.create(
            sale=sale,
            item=self.item,
            quantity=2,
            selling_price=Decimal("100.25"),
            cost_price=Decimal("70.10"),
        )

        self.assertEqual(sale_item.profit, Decimal("60.30"))

    def test_sale_totals_use_decimal_values(self):
        sale = Sale.objects.create(total_amount=Decimal("0.00"), total_profit=Decimal("0.00"))

        SaleItem.objects.create(
            sale=sale,
            item=self.item,
            quantity=3,
            selling_price=self.item.unit_price,
            cost_price=self.item.cost_price,
        )

        total_amount = self.item.unit_price * 3
        total_profit = (self.item.unit_price - self.item.cost_price) * 3
        sale.total_amount = total_amount
        sale.total_profit = total_profit
        sale.save()

        refreshed = Sale.objects.get(pk=sale.pk)
        self.assertEqual(refreshed.total_amount, Decimal("300.75"))
        self.assertEqual(refreshed.total_profit, Decimal("90.45"))


class ApiBaseTestCase(TestCase):
    """Shared helpers for API tests."""

    def make_user(self, username, role=ROLE_ADMIN, password="pass1234"):
        ok, result = AdminAuthManager.create_admin_user(
            username=username,
            full_name=username.title(),
            email=f"{username}@test.local",
            password=password,
            role=role,
        )
        self.assertTrue(ok)
        return result

    def login(self, user, device_name="test-device"):
        client = APIClient()
        resp = client.post(
            "/api/auth/login/",
            {"username": user.username, "password": "pass1234", "device_name": device_name},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        client.credentials(HTTP_AUTHORIZATION=f"Token {resp.data['token']}")
        return client, resp.data


class ApiAuthTests(ApiBaseTestCase):
    def setUp(self):
        self.admin = self.make_user("adminuser", ROLE_ADMIN)

    def test_login_returns_token_and_role(self):
        client = APIClient()
        resp = client.post(
            "/api/auth/login/",
            {"username": "adminuser", "password": "pass1234", "device_name": "pc-1"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["token"])
        self.assertEqual(resp.data["user"]["role"], ROLE_ADMIN)

    def test_login_rejects_bad_password(self):
        resp = APIClient().post(
            "/api/auth/login/",
            {"username": "adminuser", "password": "nope"},
            format="json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_api_requires_token(self):
        resp = APIClient().get("/api/items/")
        self.assertEqual(resp.status_code, 401)

    def test_logout_revokes_token(self):
        client, resp = self.login(self.admin)
        out = client.post("/api/auth/logout/", {}, format="json")
        self.assertEqual(out.status_code, 200)
        again = client.get("/api/items/")
        self.assertEqual(again.status_code, 401)


class ApiRoleEnforcementTests(ApiBaseTestCase):
    def setUp(self):
        self.admin = self.make_user("adminuser", ROLE_ADMIN)
        self.cashier = self.make_user("cashier1", ROLE_CASHIER)
        self.category = Category.objects.create(name="Tyres", size_required=False)
        self.item = Item.objects.create(
            name="Tyre A",
            unit_price=Decimal("100.00"),
            cost_price=Decimal("70.00"),
            quantity_in_stock=Decimal("10.000"),
            category=self.category,
        )

    def test_cashier_cannot_create_item(self):
        client, _ = self.login(self.cashier)
        resp = client.post(
            "/api/items/",
            {"name": "Hacked", "unit_price": "1", "category": self.category.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_cashier_cannot_edit_item(self):
        client, _ = self.login(self.cashier)
        resp = client.patch(
            f"/api/items/{self.item.external_id}/",
            {"unit_price": "999"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.unit_price, Decimal("100.00"))

    def test_cashier_cannot_access_users(self):
        client, _ = self.login(self.cashier)
        self.assertEqual(client.get("/api/users/").status_code, 403)
        self.assertEqual(client.get("/api/auditlog/").status_code, 403)

    def test_cashier_does_not_see_cost_price(self):
        client, _ = self.login(self.cashier)
        resp = client.get("/api/items/")
        self.assertEqual(resp.status_code, 200)
        payload = resp.data["results"] if "results" in resp.data else resp.data
        first = payload[0] if isinstance(payload, list) else payload
        self.assertNotIn("cost_price", first)

    def test_admin_sees_cost_price(self):
        client, _ = self.login(self.admin)
        resp = client.get("/api/items/")
        payload = resp.data["results"] if "results" in resp.data else resp.data
        first = payload[0] if isinstance(payload, list) else payload
        self.assertIn("cost_price", first)

    def test_cashier_can_make_a_sale(self):
        client, _ = self.login(self.cashier)
        resp = client.post(
            "/api/sales/",
            {
                "external_id": "11111111-1111-1111-1111-111111111111",
                "items": [
                    {
                        "item_external_id": str(self.item.external_id),
                        "quantity": "2",
                        "selling_price": "100.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("8.000"))
        self.assertEqual(Sale.objects.count(), 1)
        # Server uses authoritative cost even though the cashier sent none.
        line = SaleItem.objects.get()
        self.assertEqual(line.cost_price, Decimal("70.00"))
        self.assertEqual(line.profit, Decimal("60.00"))

    def test_admin_cannot_deactivate_self(self):
        client, _ = self.login(self.admin)
        resp = client.patch(
            f"/api/users/{self.admin.external_id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class SyncEngineTests(ApiBaseTestCase):
    def setUp(self):
        self.admin = self.make_user("adminuser", ROLE_ADMIN)
        self.category = Category.objects.create(name="Batteries", size_required=False)
        self.item = Item.objects.create(
            name="Battery XL",
            unit_price=Decimal("500.00"),
            cost_price=Decimal("350.00"),
            quantity_in_stock=Decimal("10.000"),
            category=self.category,
        )

    def test_push_sale_is_idempotent(self):
        client, _ = self.login(self.admin)
        sale_external = "22222222-2222-2222-2222-222222222222"
        payload = {
            "device_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "sales": [
                {
                    "external_id": sale_external,
                    "items": [
                        {
                            "item_external_id": str(self.item.external_id),
                            "quantity": "2",
                            "selling_price": "500.00",
                        }
                    ],
                }
            ],
        }
        r1 = client.post("/api/sync/push/", payload, format="json")
        self.assertEqual(r1.status_code, 200, r1.data)
        self.assertEqual(r1.data["report"]["sales_created"], 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("8.000"))

        r2 = client.post("/api/sync/push/", payload, format="json")
        self.assertEqual(r2.data["report"]["sales_skipped"], 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("8.000"))
        self.assertEqual(Sale.objects.count(), 1)

    def test_pull_round_trip(self):
        client, _ = self.login(self.admin)
        pull = client.post(
            "/api/sync/pull/",
            {"device_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"},
            format="json",
        )
        self.assertEqual(pull.status_code, 200)
        self.assertEqual(len(pull.data["categories"]), 1)
        self.assertEqual(len(pull.data["items"]), 1)
        self.assertTrue(pull.data["server_time"])

    def test_pull_incremental_since(self):
        client, _ = self.login(self.admin)
        first = client.post(
            "/api/sync/pull/",
            {"device_id": "cccccccc-cccc-cccc-cccc-cccccccccccc"},
            format="json",
        )
        since = first.data["server_time"]

        Category.objects.create(name="Oil", size_required=False)

        second = client.post(
            "/api/sync/pull/",
            {"device_id": "cccccccc-cccc-cccc-cccc-cccccccccccc", "since": since},
            format="json",
        )
        names = [c["name"] for c in second.data["categories"]]
        self.assertIn("Oil", names)
        self.assertNotIn("Batteries", names)

    def test_stock_delta_accumulates(self):
        client, _ = self.login(self.admin)
        resp = client.post(
            f"/api/items/{self.item.external_id}/stock/",
            {"delta": "5"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("15.000"))

    def test_apply_changes_ignores_client_cost_for_admin_device(self):
        report = apply_changes(
            {
                "sales": [
                    {
                        "external_id": "33333333-3333-3333-3333-333333333333",
                        "items": [
                            {
                                "item_external_id": str(self.item.external_id),
                                "quantity": "1",
                                "selling_price": "500.00",
                                "cost_price": "999.99",
                            }
                        ],
                    }
                ]
            },
            caller_user=self.admin,
        )
        self.assertEqual(report["sales_created"], 1)
        line = SaleItem.objects.get()
        self.assertEqual(line.cost_price, Decimal("350.00"))

    def test_audit_log_records_login(self):
        self.login(self.admin)
        self.assertTrue(AuditLog.objects.filter(action="login").exists())


class StockAdjustmentSyncTests(ApiBaseTestCase):
    def setUp(self):
        self.admin = self.make_user("adminuser", ROLE_ADMIN)
        self.category = Category.objects.create(name="Oil Filters", size_required=False)
        self.item = Item.objects.create(
            name="Oil Filter F1",
            unit_price=Decimal("80.00"),
            cost_price=Decimal("50.00"),
            quantity_in_stock=Decimal("10.000"),
            category=self.category,
        )

    def _adjustment_payload(self, external_id, delta, item_ext=None):
        return {
            "device_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "stock_adjustments": [
                {
                    "external_id": external_id,
                    "item_external_id": str(item_ext or self.item.external_id),
                    "delta": delta,
                    "details": "test",
                    "updated_at": "2026-09-09T10:00:00+02:00",
                }
            ],
        }

    def test_push_stock_adjustment_is_idempotent(self):
        client, _ = self.login(self.admin)
        ext = "44444444-4444-4444-4444-444444444444"
        r1 = client.post("/api/sync/push/", self._adjustment_payload(ext, "5"), format="json")
        self.assertEqual(r1.status_code, 200, r1.data)
        self.assertEqual(r1.data["report"]["stock_adjustments"], 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("15.000"))

        r2 = client.post("/api/sync/push/", self._adjustment_payload(ext, "5"), format="json")
        self.assertEqual(r2.data["report"]["stock_adjustments_skipped"], 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("15.000"))
        self.assertEqual(StockAdjustment.objects.count(), 1)

    def test_pull_returns_recorded_adjustment(self):
        client, _ = self.login(self.admin)
        client.post(
            "/api/sync/push/",
            self._adjustment_payload("55555555-5555-5555-5555-555555555555", "-2"),
            format="json",
        )
        pull = client.post(
            "/api/sync/pull/",
            {"device_id": "dddddddd-dddd-dddd-dddd-dddddddddddd"},
            format="json",
        )
        self.assertEqual(len(pull.data["stock_adjustments"]), 1)
        self.assertEqual(pull.data["stock_adjustments"][0]["delta"], "-2.000")

    def test_apply_delta_and_skip_own_echo(self):
        # Simulates a desktop applying a pull that echoes back its own record:
        # delta must not be applied twice.
        ext = "66666666-6666-6666-6666-666666666666"
        report1 = apply_changes(
            {
                "stock_adjustments": [
                    {
                        "external_id": ext,
                        "item_external_id": str(self.item.external_id),
                        "delta": "3",
                    }
                ]
            },
            caller_user=None,
        )
        self.assertEqual(report1["stock_adjustments"], 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("13.000"))

        report2 = apply_changes(
            {
                "stock_adjustments": [
                    {
                        "external_id": ext,
                        "item_external_id": str(self.item.external_id),
                        "delta": "3",
                    }
                ]
            },
            caller_user=None,
        )
        self.assertEqual(report2["stock_adjustments_skipped"], 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("13.000"))

    def test_stock_api_endpoint_records_syncable_adjustment(self):
        client, _ = self.login(self.admin)
        resp = client.post(
            f"/api/items/{self.item.external_id}/stock/",
            {"delta": "7"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(StockAdjustment.objects.count(), 1)
        self.assertEqual(StockAdjustment.objects.get().delta, Decimal("7.000"))
