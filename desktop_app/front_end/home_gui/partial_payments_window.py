from datetime import datetime
from decimal import Decimal, InvalidOperation

from PyQt5 import QtCore, QtWidgets

from django.db import transaction
from django.utils import timezone

from sales.models import Item, PartialPayment, PaymentRecord, StockAdjustment


class PartialPaymentsWindow(QtWidgets.QMainWindow):
    """Create and manage partial (layaway) payments.

    Money is stored as append-only PaymentRecords; the PartialPayment header
    only holds the item/qty/price and workflow flags (collected, deleted), so
    multi-device sync never clobbers a payment.
    """

    def __init__(self, prefill=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Partial Payments - NASS")
        self.resize(900, 560)
        self.center_window()

        self.prefill = prefill or {}
        self.outstanding = []

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout()
        central.setLayout(layout)

        title = QtWidgets.QLabel("Partial Payments")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #2c3e50; margin-bottom: 8px;"
        )
        layout.addWidget(title)

        note = QtWidgets.QLabel(
            "Customer pays part of the total; the balance stays outstanding "
            "until settled. Stock is reduced only when the item is collected."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        layout.addWidget(note)

        # ===== New partial payment entry =====
        form = QtWidgets.QHBoxLayout()
        layout.addLayout(form)

        self.item_combo = QtWidgets.QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.item_combo.setMinimumWidth(300)
        self.item_combo.setCompleter(None)
        if self.item_combo.lineEdit() is not None:
            self.item_combo.lineEdit().setPlaceholderText("Search item")
        form.addWidget(self.item_combo)

        self.qty_input = QtWidgets.QLineEdit()
        self.qty_input.setPlaceholderText("Qty")
        self.qty_input.setFixedWidth(70)
        form.addWidget(self.qty_input)

        self.price_input = QtWidgets.QLineEdit()
        self.price_input.setPlaceholderText("Unit price")
        self.price_input.setFixedWidth(100)
        form.addWidget(self.price_input)

        self.paid_input = QtWidgets.QLineEdit()
        self.paid_input.setPlaceholderText("Amount paid")
        self.paid_input.setFixedWidth(110)
        form.addWidget(self.paid_input)

        self.collected_check = QtWidgets.QCheckBox("Collected now")
        form.addWidget(self.collected_check)

        add_btn = QtWidgets.QPushButton("Add Partial Payment")
        add_btn.setStyleSheet(
            "background-color: #90EE90; color: #2c3e50; padding: 8px 14px; "
            "font-weight: bold; border: none; border-radius: 4px;"
        )
        add_btn.clicked.connect(self.add_partial_payment)
        form.addWidget(add_btn)

        # Customer / phone row
        details_row = QtWidgets.QHBoxLayout()
        layout.addLayout(details_row)
        details_row.addWidget(QtWidgets.QLabel("Customer:"))
        self.customer_input = QtWidgets.QLineEdit()
        self.customer_input.setPlaceholderText("required")
        details_row.addWidget(self.customer_input)
        details_row.addWidget(QtWidgets.QLabel("Phone:"))
        self.phone_input = QtWidgets.QLineEdit()
        self.phone_input.setPlaceholderText("(optional)")
        details_row.addWidget(self.phone_input)
        details_row.addStretch()

        # Backdating: a layaway is often entered after the fact, exactly like a
        # sale. Same control and same aware-datetime handling as sales_window.
        payment_date_label = QtWidgets.QLabel("Payment Date:")
        payment_date_label.setStyleSheet("font-size: 13px; color: #2c3e50;")
        details_row.addWidget(payment_date_label)
        self.payment_datetime = QtWidgets.QDateTimeEdit(
            QtCore.QDateTime.currentDateTime()
        )
        self.payment_datetime.setCalendarPopup(True)
        self.payment_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        details_row.addWidget(self.payment_datetime)

        # ===== Outstanding list =====
        list_label = QtWidgets.QLabel("Outstanding Payments")
        list_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; margin-top: 10px;"
        )
        layout.addWidget(list_label)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            [
                "Date",
                "Customer",
                "Phone",
                "Item",
                "Qty",
                "Total (MK)",
                "Paid (MK)",
                "Balance (MK)",
                "Collected",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch
        )
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        layout.addWidget(self.table)

        # ===== Actions =====
        actions = QtWidgets.QHBoxLayout()
        layout.addLayout(actions)

        self.record_payment_btn = QtWidgets.QPushButton("💰 Record Payment")
        self.record_payment_btn.clicked.connect(self.record_payment)
        actions.addWidget(self.record_payment_btn)

        self.collect_btn = QtWidgets.QPushButton("📦 Collect Item")
        self.collect_btn.clicked.connect(self.collect_item)
        actions.addWidget(self.collect_btn)

        self.settle_btn = QtWidgets.QPushButton("✅ Settle Invoice")
        self.settle_btn.clicked.connect(self.settle_invoice)
        actions.addWidget(self.settle_btn)

        self.delete_btn = QtWidgets.QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete_partial_payment)
        actions.addWidget(self.delete_btn)

        actions.addStretch()

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        actions.addWidget(close_btn)

        self.load_items()
        self.refresh()

    # ------------------------------------------------------------------
    def center_window(self):
        screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
        geometry = self.frameGeometry()
        geometry.moveCenter(screen_geometry.center())
        self.move(geometry.topLeft())

    def load_items(self):
        self.items = list(Item.objects.filter(deleted=False).select_related("category"))
        self.items_by_display = {self._display_name(i): i for i in self.items}
        self.item_combo.clear()
        self.item_combo.addItems([self._display_name(i) for i in self.items])
        self.item_combo.setCurrentIndex(-1)

        prefill_item = self.prefill.get("item")
        if prefill_item is not None:
            display = self._display_name(prefill_item)
            self.item_combo.setEditText(display)
            self.price_input.setText(f"{prefill_item.unit_price:.2f}")
            qty = self.prefill.get("qty")
            if qty:
                self.qty_input.setText(self.format_quantity(qty))
            else:
                self.qty_input.setText("1")

        self.item_combo.currentIndexChanged.connect(self._on_item_picked)

    def _display_name(self, item):
        price_text = f"MK {item.unit_price:,.2f}"
        if item.size:
            return f"{item.name} - {item.size} ({price_text})"
        return f"{item.name} ({price_text})"

    def _on_item_picked(self, index):
        if 0 <= index < len(self.items):
            self.price_input.setText(f"{self.items[index].unit_price:.2f}")

    def _resolve_item(self):
        text = self.item_combo.currentText().strip()
        direct = self.items_by_display.get(text)
        if direct:
            return direct
        for item in self.items:
            if self._display_name(item).lower() == text.lower():
                return item
        return None

    def parse_quantity(self, text):
        cleaned = text.strip()
        if not cleaned:
            raise ValueError
        qty = Decimal(cleaned)
        if qty <= 0:
            raise ValueError
        return qty

    def parse_money(self, text):
        cleaned = text.replace("MK", "").replace(",", "").strip()
        if not cleaned:
            raise ValueError
        value = Decimal(cleaned)
        if value < 0:
            raise ValueError
        return value

    def format_quantity(self, qty):
        text = format(qty, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    def _selected_payment_datetime(self):
        """Return the chosen payment date as a timezone-aware datetime."""
        selected = self.payment_datetime.dateTime().toPyDateTime()
        if not selected:
            selected = timezone.localtime()
        return (
            timezone.make_aware(selected)
            if timezone.is_naive(selected)
            else selected
        )

    @staticmethod
    def _format_dt(value):
        if value is None:
            return "-"
        if timezone.is_naive(value):
            value = timezone.make_aware(value)
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")

    def _trigger_sync(self):
        """Nudge the autosync engine, if this window was given one."""
        if getattr(self, "autosync", None) is not None:
            self.autosync.start_sync()

    # ------------------------------------------------------------------
    def add_partial_payment(self):
        item = self._resolve_item()
        if item is None:
            QtWidgets.QMessageBox.warning(self, "Error", "Select an item.")
            return
        customer_name = self.customer_input.text().strip()
        if not customer_name:
            QtWidgets.QMessageBox.warning(self, "Error", "Customer name is required.")
            return
        try:
            qty = self.parse_quantity(self.qty_input.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Enter a valid quantity (e.g. 1, 0.5)."
            )
            return
        try:
            unit_price = Decimal(self.price_input.text().strip())
            if unit_price < 0:
                raise ValueError
        except (ValueError, InvalidOperation):
            QtWidgets.QMessageBox.warning(self, "Error", "Enter a valid unit price.")
            return

        paid = Decimal("0")
        if self.paid_input.text().strip():
            try:
                paid = self.parse_money(self.paid_input.text())
            except ValueError:
                QtWidgets.QMessageBox.warning(
                    self, "Error", "Enter a valid amount paid."
                )
                return

        total = unit_price * qty
        if paid > total:
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                f"Amount paid (MK {paid:,.2f}) is more than the total "
                f"(MK {total:,.2f}).",
            )
            return

        collected = self.collected_check.isChecked()

        try:
            payment_time = self._selected_payment_datetime()
            with transaction.atomic():
                pp = PartialPayment.objects.create(
                    item=item,
                    quantity=qty,
                    unit_price=unit_price,
                    total_amount=total,
                    date=payment_time,
                    customer_name=customer_name[:150],
                    phone=self.phone_input.text().strip()[:50],
                    collected=collected,
                )
                if paid > 0:
                    PaymentRecord.objects.create(
                        date=payment_time,
                        partial_payment=pp,
                        amount=paid,
                    )
                if collected:
                    self._reduce_stock(item, -qty)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not save partial payment: {exc}"
            )
            return

        self.item_combo.setEditText("")
        self.qty_input.clear()
        self.paid_input.clear()
        self.customer_input.clear()
        self.phone_input.clear()
        self.collected_check.setChecked(False)
        self.refresh()
        status = "Settled" if paid >= total else "Outstanding"
        QtWidgets.QMessageBox.information(
            self, "Saved", f"Partial payment saved ({status})."
        )

    def _reduce_stock(self, item, delta):
        """Reduce (or restore) stock and record a syncable adjustment."""
        item_obj = Item.objects.select_for_update().get(pk=item.pk)
        item_obj.quantity_in_stock += delta
        item_obj.save()
        StockAdjustment.objects.create(
            item=item_obj,
            delta=delta,
            details=(
                "Partial payment collected"
                if delta < 0
                else "Partial payment cancelled"
            ),
        )

    # ------------------------------------------------------------------
    def refresh(self):
        self.outstanding = list(
            PartialPayment.objects.filter(deleted=False).prefetch_related("payments")
        )
        self.table.setRowCount(0)
        for row, pp in enumerate(self.outstanding):
            self.table.insertRow(row)
            self.table.setItem(
                row,
                0,
                # pp.date is the backdatable business date; created_at is just
                # the DB row insertion time and ignored the user's choice.
                QtWidgets.QTableWidgetItem(self._format_dt(pp.date)),
            )
            self.table.setItem(
                row, 1, QtWidgets.QTableWidgetItem(pp.customer_name or "-")
            )
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(pp.phone or "-"))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(str(pp.item)))
            self.table.setItem(
                row, 4, QtWidgets.QTableWidgetItem(self.format_quantity(pp.quantity))
            )
            self.table.setItem(
                row, 5, QtWidgets.QTableWidgetItem(f"MK {pp.total_amount:,.2f}")
            )
            self.table.setItem(row, 6, QtWidgets.QTableWidgetItem(f"MK {pp.paid:,.2f}"))
            self.table.setItem(
                row, 7, QtWidgets.QTableWidgetItem(f"MK {pp.balance:,.2f}")
            )
            self.table.setItem(
                row,
                8,
                QtWidgets.QTableWidgetItem("Yes" if pp.collected else "No"),
            )
        if self.outstanding:
            self.table.selectRow(0)

    def _selected_pp(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.outstanding):
            return self.outstanding[row]
        return None

    def record_payment(self):
        pp = self._selected_pp()
        if pp is None:
            QtWidgets.QMessageBox.warning(
                self, "Nothing selected", "Select an outstanding payment first."
            )
            return

        balance = pp.balance
        if balance <= 0:
            QtWidgets.QMessageBox.information(
                self, "Already settled", "This invoice is fully paid."
            )
            return

        amount, ok = QtWidgets.QInputDialog.getDouble(
            self,
            "Record Payment",
            f"Amount to record for balance MK {balance:,.2f}:",
            float(balance) if balance < 10000 else 0.0,
            0.0,
            1000000000.0,
            2,
        )
        if not ok or amount <= 0:
            return

        try:
            with transaction.atomic():
                self._add_payment(pp, Decimal(str(amount)))
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not record payment: {exc}"
            )
            return
        self.refresh()

    def _add_payment(self, pp, amount):
        PaymentRecord.objects.create(
            date=timezone.now(),
            partial_payment=pp,
            amount=amount,
        )

    def collect_item(self):
        pp = self._selected_pp()
        if pp is None:
            QtWidgets.QMessageBox.warning(
                self, "Nothing selected", "Select a payment first."
            )
            return
        if pp.collected:
            QtWidgets.QMessageBox.information(
                self, "Already collected", "This item is already marked as collected."
            )
            return

        answer = QtWidgets.QMessageBox.question(
            self,
            "Confirm collection",
            f"Mark '{pp.item}' (qty {self.format_quantity(pp.quantity)}) as "
            "collected?\n\nStock will be reduced by this quantity.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return

        try:
            with transaction.atomic():
                pp_obj = PartialPayment.objects.select_for_update().get(pk=pp.pk)
                self._reduce_stock(pp_obj.item, -pp_obj.quantity)
                pp_obj.collected = True
                pp_obj.save()
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not update item: {exc}"
            )
            return
        self.refresh()

    def settle_invoice(self):
        pp = self._selected_pp()
        if pp is None:
            QtWidgets.QMessageBox.warning(
                self, "Nothing selected", "Select an outstanding payment first."
            )
            return
        balance = pp.balance
        if balance <= 0:
            QtWidgets.QMessageBox.information(
                self, "Already settled", "This invoice is fully paid."
            )
            return

        answer = QtWidgets.QMessageBox.question(
            self,
            "Settle invoice",
            f"Record the remaining balance of MK {balance:,.2f} to settle this "
            "invoice now?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return

        try:
            with transaction.atomic():
                self._add_payment(pp, balance)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not settle invoice: {exc}"
            )
            return
        self.refresh()
        QtWidgets.QMessageBox.information(
            self, "Settled", "Invoice settled. Balance is now MK 0.00."
        )

    def delete_partial_payment(self):
        """Soft-delete a layaway, undoing any stock it had already consumed.

        Nothing is hard-deleted: the row keeps its `deleted` flag and a fresh
        `updated_at` so the change propagates to the server and other devices
        instead of silently reappearing on the next pull.
        """
        pp = self._selected_pp()
        if pp is None:
            QtWidgets.QMessageBox.warning(
                self, "Nothing selected", "Select a payment first."
            )
            return

        paid = pp.paid
        balance = pp.balance
        stock_note = ""
        if pp.collected:
            stock_note = (
                f"\n\nThis item was already collected, so stock of "
                f"{self.format_quantity(pp.quantity)} will be restored."
            )

        answer = QtWidgets.QMessageBox.question(
            self,
            "Confirm delete",
            f"Delete partial payment for '{pp.customer_name or pp.item}' "
            f"(MK {pp.total_amount:,.2f})?\n\n"
            f"Recorded: MK {paid:,.2f} | Balance: MK {balance:,.2f}."
            f"{stock_note}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return

        try:
            with transaction.atomic():
                pp_obj = PartialPayment.objects.select_for_update().get(pk=pp.pk)
                if pp_obj.collected:
                    self._reduce_stock(pp_obj.item, pp_obj.quantity)
                # Soft-delete the money rows too, otherwise pp.paid keeps
                # counting them and the invoice still looks partly settled.
                PaymentRecord.objects.filter(
                    partial_payment=pp_obj, deleted=False
                ).update(deleted=True, updated_at=timezone.now())
                pp_obj.deleted = True
                pp_obj.save()
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not delete partial payment: {exc}"
            )
            return

        self.refresh()
        self._trigger_sync()
        QtWidgets.QMessageBox.information(
            self,
            "Deleted",
            "Partial payment deleted"
            + (" and stock restored." if pp.collected else ".")
            + " Queued for sync.",
        )
