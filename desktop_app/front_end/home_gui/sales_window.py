from PyQt5 import QtWidgets, QtCore, QtGui
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from sales.models import (
    Item,
    Sale,
    SaleItem,
    record_stock_delta,
    sale_stock_external_id,
)


class OutOfStockDialog(QtWidgets.QDialog):
    def __init__(self, item_name, available_stock):
        super().__init__()
        self.setWindowTitle("Out of Stock Alert")
        self.setFixedSize(450, 200)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        message = QtWidgets.QLabel(
            f"⚠ '{item_name}' has insufficient stock ({available_stock}).\n\n"
            "Do you want to continue?\n"
            "This will create negative stock."
        )
        message.setWordWrap(True)
        message.setStyleSheet("font-size: 13px;")
        layout.addWidget(message)

        btn_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(btn_layout)

        confirm_btn = QtWidgets.QPushButton("Confirm")
        cancel_btn = QtWidgets.QPushButton("Cancel")

        confirm_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(confirm_btn)
        btn_layout.addWidget(cancel_btn)


class SalesWindow(QtWidgets.QMainWindow):
    def __init__(self, autosync=None, current_user=None):
        super().__init__()

        self.autosync = autosync
        self.current_user = current_user
        self.setWindowTitle("Sales Entry - NASS")
        self.resize(900, 500)
        self.center_window()

        font = QtGui.QFont("Segoe UI", 11)
        self.setFont(font)

        self.current_sale_items = []

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout()
        central.setLayout(layout)

        # ===== SHOP NAME HEADER =====
        shop_header = QtWidgets.QLabel("REAL GENERAL SUPPLIERS")
        shop_header.setAlignment(QtCore.Qt.AlignCenter)
        shop_header.setStyleSheet(
            """
            QLabel {
                font-size: 28px;
                font-weight: bold;
                color: #2c3e50;
                padding: 10px;
                background-color: #ecf0f1;
                border-radius: 8px;
                margin-bottom: 10px;
            }
        """
        )
        layout.addWidget(shop_header)

        title = QtWidgets.QLabel("Sales Entry")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #7f8c8d; margin-bottom: 10px;"
        )
        layout.addWidget(title)

        # Sale date (back-datable: missed sales are recorded on their real day),
        # aligned far left, just above the item search box
        date_row = QtWidgets.QHBoxLayout()
        date_label = QtWidgets.QLabel("Sale Date:")
        date_label.setStyleSheet("font-size: 13px; color: #2c3e50;")
        date_row.addWidget(date_label)
        self.sale_datetime = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
        self.sale_datetime.setCalendarPopup(True)
        self.sale_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        date_row.addWidget(self.sale_datetime)
        date_row.addStretch()

        # Partial Pay: a plain button (like the Close button), aligned with the
        # Sale Date row on the far right.
        self.partial_btn = QtWidgets.QPushButton("Partial Pay")
        self.partial_btn.clicked.connect(self.open_partial_payment)
        date_row.addWidget(self.partial_btn)
        layout.addLayout(date_row)

        form_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(form_layout)

        # Item dropdown
        self.item_combo = QtWidgets.QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.item_combo.setMinimumWidth(400)
        if self.item_combo.lineEdit() is not None:
            self.item_combo.lineEdit().setPlaceholderText("Search item")
        self.item_combo.setCompleter(None)
        form_layout.addWidget(self.item_combo)

        self.qty_input = QtWidgets.QLineEdit()
        self.qty_input.setPlaceholderText("Quantity")
        self.qty_input.setFixedWidth(150)
        form_layout.addWidget(self.qty_input)

        # ===== FADE GREEN ADD TO SALE BUTTON =====
        add_btn = QtWidgets.QPushButton("Add to Sale")
        add_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #90EE90;  /* Light green */
                color: #2c3e50;
                padding: 8px 20px;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #7CCD7C;  /* Slightly darker green on hover */
            }
            QPushButton:pressed {
                background-color: #6BBE6B;  /* Even darker when pressed */
            }
        """
        )
        form_layout.addWidget(add_btn)
        add_btn.clicked.connect(self.add_item_to_sale)

        # ===== TABLE =====
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Item", "Size", "Qty", "Unit Price (MK)", "Subtotal (MK)", "Remove"]
        )

        self.table.setStyleSheet(
            """
            QTableWidget {
                font-size: 14px;
            }
            QHeaderView::section {
                font-size: 14px;
                font-weight: bold;
                padding: 6px;
            }
        """
        )

        self.table.verticalHeader().setDefaultSectionSize(45)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)  # Item
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)  # Size
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)  # Qty
        header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeToContents
        )  # Unit Price
        header.setSectionResizeMode(
            4, QtWidgets.QHeaderView.ResizeToContents
        )  # Subtotal
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)  # Remove
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.table.itemChanged.connect(self.handle_item_changed)

        # Total label (MK only)
        self.total_label = QtWidgets.QLabel("Total: MK 0.00")
        self.total_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: black;"
        )
        layout.addWidget(self.total_label)

        # ===== GREEN COMPLETE SALE BUTTON =====
        complete_btn = QtWidgets.QPushButton("Complete Sale")
        complete_btn.setMaximumHeight(32)
        complete_btn.setMinimumWidth(300)
        complete_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #90EE90;  /* Bright green */
                color: #2c3e50;
                font-size: 16px;
                font-weight: bold;
                padding: 4px 8px; 
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #27ae60;  /* Darker green on hover */
            }
            QPushButton:pressed {
                background-color: #229954;  /* Even darker when pressed */
            }
        """
        )

        complete_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Fixed
        )

        layout.addWidget(complete_btn, 0, QtCore.Qt.AlignCenter)
        complete_btn.clicked.connect(self.complete_sale)

        self.item_combo.activated.connect(self._on_item_selected)
        self.item_combo.currentIndexChanged.connect(self._on_item_selected)

        self.load_items()

        # Live clock: keep the Sale Date field tracking "now" while the window
        # stays open, but never override a date the user is actively editing.
        self.live_clock_timer = QtCore.QTimer(self)
        self.live_clock_timer.timeout.connect(self._tick_live_clock)
        self.live_clock_timer.start(1000)

        # Do not highlight the Sale Date on open (avoids accidental date edits).
        self.sale_datetime.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.sale_datetime.clearFocus()
        date_edit = self.sale_datetime.lineEdit()
        if date_edit is not None:
            date_edit.deselect()

    def _tick_live_clock(self):
        if self.sale_datetime.hasFocus():
            return
        calendar = self.sale_datetime.calendarWidget()
        if calendar is not None and calendar.isVisible():
            return
        # Only update the time portion; preserve the date the user selected
        # so that backdated sales are not overwritten to today.
        current_time = QtCore.QTime.currentTime()
        current_dt = self.sale_datetime.dateTime()
        current_dt.setTime(current_time)
        self.sale_datetime.setDateTime(current_dt)

    def open_partial_payment(self):
        """Open the Partial Payments window, prefilled from a lone cart row."""
        from front_end.home_gui.partial_payments_window import PartialPaymentsWindow

        prefill = None
        if len(self.current_sale_items) == 1:
            row_data = self.current_sale_items[0]
            prefill = {
                "item": row_data["item"],
                "qty": row_data["qty"],
                "unit_price": row_data.get("unit_price", row_data["item"].unit_price),
            }
        else:
            # Carry the item combo selection over when it points at something.
            item = self._resolve_typed_item()
            if item is not None:
                prefill = {"item": item}

        if not hasattr(self, "partial_payments_window") or self.partial_payments_window.isHidden():
            self.partial_payments_window = PartialPaymentsWindow(prefill=prefill, parent=self)
            self.partial_payments_window.show()
        else:
            self.partial_payments_window.show()
            self.partial_payments_window.raise_()

    def center_window(self):
        """Center the window on the screen"""
        screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    def _selected_sale_datetime(self):
        """Return the chosen sale date as a timezone-aware datetime."""
        selected = self.sale_datetime.dateTime().toPyDateTime()
        if not selected:
            selected = timezone.localtime()
        return timezone.make_aware(selected) if timezone.is_naive(selected) else selected

    def load_items(self):
        """Load items into combo box"""
        self.items = list(Item.objects.filter(deleted=False).select_related("category"))
        self.items_by_display = {self._display_name(i): i for i in self.items}
        self.filtered_items = list(self.items)
        self.item_combo.clear()

        # Use completer popup for matching without auto-filling text.
        display_items = [self._display_name(i) for i in self.items]
        self.completer = QtWidgets.QCompleter(display_items)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.completer.setFilterMode(QtCore.Qt.MatchContains)
        self.completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.completer.activated.connect(self._on_completer_activated)
        self.item_combo.lineEdit().setCompleter(self.completer)

    def add_item_to_sale(self):
        try:
            qty = self.parse_quantity(self.qty_input.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Enter valid quantity (e.g. 1, 0.5, 0.25)"
            )
            return
        index = self.item_combo.currentIndex()
        if index < 0:
            item = self._resolve_typed_item()
            if item is None and hasattr(self, "_last_selected_item"):
                item = self._last_selected_item
            if item is None:
                QtWidgets.QMessageBox.warning(
                    self, "Error", "Select an item from the list"
                )
                return
        else:
            item = self.filtered_items[index]

        if qty > item.quantity_in_stock:
            dialog = OutOfStockDialog(item.name, item.quantity_in_stock)
            if dialog.exec_() != QtWidgets.QDialog.Accepted:
                return

        self.current_sale_items.append(
            {"item": item, "qty": qty, "unit_price": item.unit_price}
        )
        self.refresh_table()
        self.qty_input.clear()
        self.item_combo.setCurrentIndex(-1)
        self.item_combo.setEditText("")
        self._last_selected_item = None

    def _display_name(self, item):
        price_text = f"MK {item.unit_price:,.2f}"
        stock_text = f"[{item.quantity_in_stock:.0f} in stock]"
        if item.size:
            return f"{item.name} - {item.size} ({price_text}) {stock_text}"
        return f"{item.name} ({price_text}) {stock_text}"

    def _on_completer_activated(self, text):
        item = self.items_by_display.get(text)
        if item:
            self._last_selected_item = item

    def _resolve_typed_item(self):
        typed = self.item_combo.currentText().strip()
        if not typed:
            return None
        direct = self.items_by_display.get(typed)
        if direct:
            return direct
        if len(self.filtered_items) == 1:
            return self.filtered_items[0]
        for item in self.filtered_items:
            if self._display_name(item).lower() == typed.lower():
                return item
        return None

    def _on_item_selected(self, index):
        if index >= 0 and index < len(self.filtered_items):
            self._last_selected_item = self.filtered_items[index]

    def parse_quantity(self, text):
        cleaned = text.strip()
        if cleaned == "":
            raise ValueError
        try:
            qty = Decimal(cleaned)
        except InvalidOperation:
            raise ValueError
        if qty <= 0:
            raise ValueError
        return qty

    def parse_money(self, text):
        cleaned = text.replace("MK", "").replace(",", "").strip()
        if cleaned == "":
            raise ValueError
        try:
            value = Decimal(cleaned)
        except InvalidOperation:
            raise ValueError
        if value <= 0:
            raise ValueError
        return value

    def format_quantity(self, qty):
        text = format(qty, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    def refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        total = Decimal("0.00")

        for row_data in self.current_sale_items:
            item = row_data["item"]
            qty = row_data["qty"]
            unit_price = row_data.get("unit_price", item.unit_price)
            subtotal = unit_price * qty
            total += subtotal

            row = self.table.rowCount()
            self.table.insertRow(row)

            item_name = QtWidgets.QTableWidgetItem(item.name)
            item_name.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            self.table.setItem(row, 0, item_name)

            size_item = QtWidgets.QTableWidgetItem(item.size or "")
            size_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            self.table.setItem(row, 1, size_item)

            qty_item = QtWidgets.QTableWidgetItem(self.format_quantity(qty))
            qty_item.setFlags(
                QtCore.Qt.ItemIsSelectable
                | QtCore.Qt.ItemIsEnabled
                | QtCore.Qt.ItemIsEditable
            )
            self.table.setItem(row, 2, qty_item)

            price_item = QtWidgets.QTableWidgetItem(f"MK {unit_price:,.2f}")
            price_item.setFlags(
                QtCore.Qt.ItemIsSelectable
                | QtCore.Qt.ItemIsEnabled
                | QtCore.Qt.ItemIsEditable
            )
            self.table.setItem(row, 3, price_item)

            subtotal_item = QtWidgets.QTableWidgetItem(f"MK {subtotal:,.2f}")
            subtotal_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            self.table.setItem(row, 4, subtotal_item)

            remove_btn = QtWidgets.QPushButton("Remove")
            remove_btn.setMinimumHeight(30)
            remove_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #D3D3D3 ;
                    color: white;
                    border: none;
                    border-radius: 3px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                }
            """
            )
            remove_btn.clicked.connect(lambda _, r=row: self.remove_row(r))
            self.table.setCellWidget(row, 5, remove_btn)

        self.total_label.setText(f"Total: MK {total:,.2f}")
        self.table.blockSignals(False)

    def handle_item_changed(self, item):
        row = item.row()
        if row < 0 or row >= len(self.current_sale_items):
            return

        if item.column() == 2:
            try:
                new_qty = self.parse_quantity(item.text())
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "Error", "Invalid quantity")
                self.refresh_table()
                return

            selected_item = self.current_sale_items[row]["item"]
            if new_qty > selected_item.quantity_in_stock:
                dialog = OutOfStockDialog(
                    selected_item.name, selected_item.quantity_in_stock
                )
                if dialog.exec_() != QtWidgets.QDialog.Accepted:
                    self.refresh_table()
                    return

            self.current_sale_items[row]["qty"] = new_qty
            self.refresh_table()

        if item.column() == 3:
            try:
                new_price = self.parse_money(item.text())
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "Error", "Invalid unit price")
                self.refresh_table()
                return

            self.current_sale_items[row]["unit_price"] = new_price
            self.refresh_table()

    def remove_row(self, row):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm",
            "Remove this item from sale?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.current_sale_items.pop(row)
            self.refresh_table()

    def complete_sale(self):
        if not self.current_sale_items:
            QtWidgets.QMessageBox.warning(self, "Error", "No items in sale")
            return

        try:
            with transaction.atomic():
                sale = Sale.objects.create(
                    date=self._selected_sale_datetime(),
                    total_amount=Decimal("0.00"),
                    total_profit=Decimal("0.00"),
                )
                total = Decimal("0.00")
                total_profit = Decimal("0.00")

                for row_data in self.current_sale_items:
                    item = Item.objects.select_for_update().get(pk=row_data["item"].pk)
                    qty = row_data["qty"]

                    selling_price = row_data.get("unit_price", item.unit_price)
                    cost_price = item.cost_price
                    line_total = selling_price * qty
                    line_profit = (selling_price - cost_price) * qty

                    si = SaleItem.objects.create(
                        sale=sale,
                        item=item,
                        quantity=qty,
                        selling_price=selling_price,
                        cost_price=cost_price,
                        profit=line_profit,
                    )

                    # Deterministic sale delta: every device derives the SAME
                    # adjustment id from the SaleItem id, so stock can never be
                    # double-applied when this sale is synced back to us.
                    record_stock_delta(
                        item,
                        -qty,
                        sale_stock_external_id(si.external_id),
                        details=f"Sale #{sale.id}",
                    )

                    total += line_total
                    total_profit += line_profit

                sale.total_amount = total
                sale.total_profit = total_profit
                sale.save()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Sale Failed", f"Could not complete sale: {e}"
            )
            return

        QtWidgets.QMessageBox.information(self, "Success", "Sale completed")

        self.current_sale_items.clear()
        self.refresh_table()
        self.load_items()
