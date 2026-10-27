"""Regression tests for three desktop-app fixes.

* Partial payments can be backdated like sales, and the table shows the
  chosen business date rather than the row's insertion time.
* Partial payments can be deleted: soft delete, payment rows soft-deleted,
  stock restored if the item had been collected, and a sync nudge.
* The admin dashboard "Recent Sales" table has a Delete button on EVERY row,
  styled plainly like the Service Management records table (not red), and the
  button survives a dashboard refresh.
* Low stock counting uses LOW_STOCK_THRESHOLD, never a hardcoded number.
"""

import contextlib
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DESKTOP_APP = _REPO_ROOT / "desktop_app"
if str(_DESKTOP_APP) not in sys.path:
    sys.path.insert(0, str(_DESKTOP_APP))

from django.test import TestCase  # noqa: E402
from django.utils import timezone  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402

from sales.models import (  # noqa: E402
    LOW_STOCK_THRESHOLD,
    Category,
    Item,
    PartialPayment,
    PaymentRecord,
    Sale,
    SaleItem,
    StockAdjustment,
)
from front_end.admin_gui.admin_dashboard_window import AdminDashboardWindow  # noqa: E402
from front_end.home_gui.partial_payments_window import (  # noqa: E402
    PartialPaymentsWindow,
)

_QAPP = None

_YES = QtWidgets.QMessageBox.Yes


def capture_errors():
    """Suppress modal popups but record any error dialog text.

    Windows report failures through QMessageBox.critical and carry on, which
    would turn a real crash into a silent assertion failure further down.
    """
    seen = []
    stack = contextlib.ExitStack()
    for name in ("information", "warning"):
        stack.enter_context(
            mock.patch.object(QtWidgets.QMessageBox, name, lambda *a, **k: None)
        )
    stack.enter_context(
        mock.patch.object(
            QtWidgets.QMessageBox,
            "critical",
            lambda *a, **k: seen.append(str(a[2]) if len(a) > 2 else str(a)),
        )
    )
    stack.enter_context(
        mock.patch.object(QtWidgets.QMessageBox, "question", lambda *a, **k: _YES)
    )
    return stack, seen


def qapp():
    """One shared QApplication for the whole test run."""
    global _QAPP
    if _QAPP is None:
        _QAPP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _QAPP


def quiet_messages():
    """Suppress the modal popups the windows raise."""
    return capture_errors()[0]


def make_item(name="Tyre 195", qty="20.000"):
    category, _ = Category.objects.get_or_create(
        name="Tyres", defaults={"size_required": False}
    )
    # Decimals, not strings: the window formats these in memory before a save,
    # and a freshly created instance keeps whatever type it was handed.
    return Item.objects.create(
        name=name,
        unit_price=Decimal("150.00"),
        cost_price=Decimal("100.00"),
        quantity_in_stock=Decimal(qty),
        category=category,
    )


def make_sale(item, quantity="1"):
    sale = Sale.objects.create(
        total_amount=Decimal("150.00"), total_profit=Decimal("50.00")
    )
    SaleItem.objects.create(
        sale=sale,
        item=item,
        quantity=Decimal(quantity),
        selling_price=Decimal("150.00"),
        cost_price=Decimal("100.00"),
    )
    return sale


class PartialPaymentBackdateTests(TestCase):
    def setUp(self):
        qapp()
        self.item = make_item()
        self.win = PartialPaymentsWindow()

    def tearDown(self):
        self.win.close()

    def _fill_form(self, paid="100.00", customer="Grace", qty="2"):
        self.win.item_combo.setEditText(self.win._display_name(self.item))
        self.win.qty_input.setText(qty)
        self.win.price_input.setText("150.00")
        self.win.paid_input.setText(paid)
        self.win.customer_input.setText(customer)

    def test_backdated_payment_date_is_persisted(self):
        chosen = timezone.localtime() - timedelta(days=3)
        self.win.payment_datetime.setDateTime(chosen.replace(tzinfo=None))
        self._fill_form()

        with mock.patch.object(
            QtWidgets.QMessageBox, "information", lambda *a, **k: None
        ):
            self.win.add_partial_payment()

        pp = PartialPayment.objects.get()
        self.assertAlmostEqual(pp.date.timestamp(), chosen.timestamp(), delta=90)
        # The deposit made at entry time shares the backdated day, so today's
        # and historical revenue totals both stay correct.
        deposit = PaymentRecord.objects.get(partial_payment=pp)
        self.assertAlmostEqual(deposit.date.timestamp(), chosen.timestamp(), delta=90)

    def test_table_shows_business_date_not_created_at(self):
        chosen = timezone.localtime() - timedelta(days=5)
        pp = PartialPayment.objects.create(
            item=self.item,
            quantity="1",
            unit_price="150.00",
            total_amount="150.00",
            date=chosen,
            customer_name="Grace",
        )
        self.win.refresh()

        shown = self.win.table.item(0, 0).text()
        expected = timezone.localtime(pp.date).strftime("%Y-%m-%d %H:%M")
        self.assertEqual(shown, expected)
        self.assertNotEqual(shown, pp.created_at.strftime("%Y-%m-%d %H:%M"))

    def test_defaults_to_now_when_untouched(self):
        self._fill_form()
        with mock.patch.object(
            QtWidgets.QMessageBox, "information", lambda *a, **k: None
        ):
            self.win.add_partial_payment()

        pp = PartialPayment.objects.get()
        self.assertAlmostEqual(
            pp.date.timestamp(), timezone.now().timestamp(), delta=300
        )


class PartialPaymentDeleteTests(TestCase):
    def setUp(self):
        qapp()
        self.item = make_item(qty="20.000")
        self.win = PartialPaymentsWindow()
        self.win.autosync = mock.Mock()

    def tearDown(self):
        self.win.close()

    def _delete_selected(self):
        self.win.refresh()
        self.win.table.selectRow(0)
        with mock.patch.object(
            QtWidgets.QMessageBox, "question", lambda *a, **k: _YES
        ), mock.patch.object(
            QtWidgets.QMessageBox, "information", lambda *a, **k: None
        ), mock.patch.object(
            QtWidgets.QMessageBox, "critical", lambda *a, **k: None
        ):
            self.win.delete_partial_payment()

    def test_deleting_collected_partial_payment_restores_stock(self):
        pp = PartialPayment.objects.create(
            item=self.item,
            quantity="2",
            unit_price="150.00",
            total_amount="300.00",
            customer_name="Grace",
            collected=True,
        )
        PaymentRecord.objects.create(partial_payment=pp, amount="100.00")
        # Emulate the collection having already drawn stock down.
        Item.objects.filter(pk=self.item.pk).update(quantity_in_stock=Decimal("18.000"))

        self._delete_selected()

        pp.refresh_from_db()
        self.assertTrue(pp.deleted, "must soft delete, not hard delete")
        self.assertIsNotNone(
            PartialPayment.objects.filter(pk=pp.pk).first(),
            "row must survive for sync",
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("20.000"))
        self.assertTrue(
            StockAdjustment.objects.filter(item=self.item, delta=Decimal("2")).exists()
        )

    def test_delete_soft_deletes_payment_records(self):
        pp = PartialPayment.objects.create(
            item=self.item,
            quantity="1",
            unit_price="150.00",
            total_amount="150.00",
            customer_name="Grace",
        )
        payment = PaymentRecord.objects.create(partial_payment=pp, amount="50.00")

        self._delete_selected()

        pp.refresh_from_db()
        payment.refresh_from_db()
        self.assertTrue(pp.deleted)
        self.assertTrue(payment.deleted)
        # Otherwise the deleted invoice still looks half-paid.
        self.assertEqual(pp.paid, Decimal("0"))
        self.assertEqual(pp.balance, pp.total_amount)

    def test_deleting_uncollected_partial_payment_leaves_stock_alone(self):
        pp = PartialPayment.objects.create(
            item=self.item,
            quantity="4",
            unit_price="150.00",
            total_amount="600.00",
            customer_name="Grace",
            collected=False,
        )

        self._delete_selected()

        pp.refresh_from_db()
        self.assertTrue(pp.deleted)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, Decimal("20.000"))

    def test_delete_removes_row_and_triggers_sync(self):
        PartialPayment.objects.create(
            item=self.item,
            quantity="1",
            unit_price="150.00",
            total_amount="150.00",
            customer_name="Grace",
        )
        self._delete_selected()

        self.assertEqual(self.win.table.rowCount(), 0)
        self.win.autosync.start_sync.assert_called()


class RecentSalesDeleteButtonTests(TestCase):
    def setUp(self):
        qapp()
        for idx in range(3):
            make_sale(make_item(name=f"Tyre {idx}"))
        self.win = AdminDashboardWindow()

    def tearDown(self):
        self.win.close()

    def test_every_recent_sales_row_has_a_delete_button(self):
        table = self.win.sales_table
        self.assertIsNotNone(table)
        self.assertEqual(table.columnCount(), 5)
        self.assertGreater(table.rowCount(), 0)
        for row in range(table.rowCount()):
            self.assertIsInstance(
                table.cellWidget(row, 4),
                QtWidgets.QPushButton,
                msg=f"row {row} has no Delete button",
            )

    def test_delete_button_survives_dashboard_refresh(self):
        # The button used to be added only on the first render, so a refresh
        # left rows without one.
        self.win.refresh_dashboard()
        table = self.win.sales_table
        for row in range(table.rowCount()):
            self.assertIsInstance(
                table.cellWidget(row, 4),
                QtWidgets.QPushButton,
                msg=f"row {row} lost its Delete button after refresh",
            )

    def test_delete_button_is_plain_not_red(self):
        button = self.win.sales_table.cellWidget(0, 4)
        self.assertEqual(button.text(), "Delete")
        self.assertNotIn("#e74c3c", button.styleSheet().lower())

    def test_deleting_a_row_restores_stock_and_triggers_sync(self):
        self.win.autosync = mock.Mock()
        table = self.win.sales_table
        # The table is ordered by -date, so read the sale id off the row we
        # are about to click rather than guessing it.
        sale = Sale.objects.get(pk=int(table.item(0, 0).text()))
        item = sale.items.first().item
        start = item.quantity_in_stock

        button = table.cellWidget(0, 4)
        stack, errors = capture_errors()
        with stack:
            button.click()
        self.assertEqual(errors, [], f"window reported an error: {errors}")

        sale.refresh_from_db()
        self.assertTrue(sale.deleted)
        item.refresh_from_db()
        self.assertEqual(item.quantity_in_stock, start + Decimal("1"))
        self.win.autosync.start_sync.assert_called()


class LowStockConsistencyTests(TestCase):
    """The website and the dashboard must agree on what 'low' means."""

    def setUp(self):
        qapp()
        threshold = LOW_STOCK_THRESHOLD
        make_item(name="Healthy", qty=str(threshold + 5))
        make_item(name="Exactly threshold", qty=str(threshold))
        make_item(name="Just below", qty=str(threshold - 1))
        make_item(name="Empty", qty="0")
        self.win = AdminDashboardWindow()

    def tearDown(self):
        self.win.close()

    def _card_text(self):
        label = self.win.stat_card_widgets.get("low_stock")
        self.assertIsNotNone(label, "low stock card label missing")
        return label.text()

    def test_initial_render_matches_shared_threshold(self):
        expected = Item.objects.filter(
            deleted=False, quantity_in_stock__lt=LOW_STOCK_THRESHOLD
        ).count()
        self.assertEqual(self._card_text(), str(expected))

    def test_refresh_matches_shared_threshold(self):
        self.win.refresh_dashboard()
        expected = Item.objects.filter(
            deleted=False, quantity_in_stock__lt=LOW_STOCK_THRESHOLD
        ).count()
        self.assertEqual(self._card_text(), str(expected))

    def test_threshold_is_not_hardcoded_in_the_refresh_path(self):
        source = (
            _REPO_ROOT
            / "desktop_app"
            / "front_end"
            / "admin_gui"
            / "admin_dashboard_window.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("quantity_in_stock__lt=5", source)
        self.assertIn("quantity_in_stock__lt=LOW_STOCK_THRESHOLD", source)


if __name__ == "__main__":
    import unittest

    unittest.main()