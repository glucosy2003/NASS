from PyQt5 import QtWidgets, QtCore, QtGui
from decimal import Decimal

from styles import colors
from sales.models import Item, Category, StockAdjustment
from front_end.admin_gui.add_item_dialog import AddItemDialog
from front_end.admin_gui.add_category_dialog import AddCategoryDialog
from front_end.admin_gui.manage_categories_window import ManageCategoriesWindow


class StockWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Stock Management - NASS")
        self.resize(1100, 600)
        self.center_window()

        Category.create_default_categories()

        self.setStyleSheet(
            f"""
            QMainWindow {{
                background-color: {colors.BACKGROUND_COLOR};
            }}
        """
        )

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout()
        central_widget.setLayout(layout)

        header = QtWidgets.QLabel("Stock Management")
        header.setAlignment(QtCore.Qt.AlignCenter)
        header.setStyleSheet(
            f"color: {colors.PRIMARY_COLOR}; font-size: 22px; font-weight: bold; margin: 10px;"
        )
        layout.addWidget(header)

        top_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(top_layout)

        # 🔎 Search Bar (Bigger Font)
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search items...")
        self.search_input.setStyleSheet("font-size: 14px; padding: 6px;")
        self.search_input.textChanged.connect(self.filter_items_global)
        top_layout.addWidget(self.search_input)

        # Manage categories button (top-right, beside search)
        self.manage_categories_btn = QtWidgets.QPushButton("🗂 Manage Categories")
        self.manage_categories_btn.clicked.connect(self.open_manage_categories)
        top_layout.addWidget(self.manage_categories_btn)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)

        btn_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(btn_layout)

        self.add_item_btn = QtWidgets.QPushButton("➕ Add Item")
        self.add_item_btn.clicked.connect(self.open_add_item_dialog)
        btn_layout.addWidget(self.add_item_btn)

        btn_layout.addStretch()

        self.tables = {}
        self.load_categories()

    def load_categories(self):
        self.tabs.clear()
        self.tables.clear()

        categories = Category.objects.filter(deleted=False).order_by("name")

        for category in categories:
            table = QtWidgets.QTableWidget()
            # NEW: include Cost Price column (kept search-compatible by using header lookups)
            table.setColumnCount(7)
            table.setHorizontalHeaderLabels(
                [
                    "Item Name",
                    "Size",
                    "Cost Price (MK)",
                    "Unit Price (MK)",
                    "Quantity",
                    "Update",
                    "Delete",
                ]
            )

            # 🔤 Bigger Table Font
            table.setStyleSheet(
                """
                QTableWidget {
                    font-size: 14px;
                }
                QHeaderView::section {
                    font-size: 14px;
                    font-weight: bold;
                }
            """
            )

            table.setEditTriggers(
                QtWidgets.QAbstractItemView.DoubleClicked
                | QtWidgets.QAbstractItemView.SelectedClicked
                | QtWidgets.QAbstractItemView.EditKeyPressed
            )
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
            table.verticalHeader().setDefaultSectionSize(40)

            table.itemChanged.connect(self.handle_item_changed)
            self.tabs.addTab(table, category.name)
            # Keep mapping by category id (same as before)
            self.tables[category.id] = table

        self.load_items()

    def center_window(self):
        """Center the window on the screen"""
        screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    def load_items(self):
        for category_id, table in self.tables.items():
            table.blockSignals(True)
            table.setRowCount(0)
            items = Item.objects.filter(category_id=category_id, deleted=False)

            for item in items:
                row = table.rowCount()
                table.insertRow(row)

                # Prepare table items (strings). Keep formatting consistent.
                name_item = QtWidgets.QTableWidgetItem(item.name)
                size_item = QtWidgets.QTableWidgetItem(item.size or "")
                cost_item = QtWidgets.QTableWidgetItem(
                    f"MK {item.cost_price:,.2f}"
                )
                price_item = QtWidgets.QTableWidgetItem(
                    f"MK {item.unit_price:,.2f}"
                )
                qty_item = QtWidgets.QTableWidgetItem(
                    self.format_quantity(item.quantity_in_stock)
                )

                name_item.setFlags(
                    QtCore.Qt.ItemIsSelectable
                    | QtCore.Qt.ItemIsEnabled
                    | QtCore.Qt.ItemIsEditable
                )
                size_item.setFlags(
                    QtCore.Qt.ItemIsSelectable
                    | QtCore.Qt.ItemIsEnabled
                    | QtCore.Qt.ItemIsEditable
                )
                for it in (name_item, size_item):
                    it.setData(QtCore.Qt.UserRole, item.id)

                table.setItem(row, 0, name_item)
                table.setItem(row, 1, size_item)
                table.setItem(row, 2, cost_item)  # cost column
                table.setItem(row, 3, price_item)  # unit price column (index shifted)
                table.setItem(row, 4, qty_item)

                update_btn = QtWidgets.QPushButton("Update")
                update_btn.clicked.connect(lambda _, i=item: self.update_item(i))
                table.setCellWidget(row, 5, update_btn)

                delete_btn = QtWidgets.QPushButton("Delete")
                delete_btn.clicked.connect(lambda _, i=item: self.delete_item(i))
                table.setCellWidget(row, 6, delete_btn)
            table.blockSignals(False)

        # Reapply filter after reload (preserves previous behavior)
        self.filter_items_global(self.search_input.text())

    # 🌍 GLOBAL SEARCH (ALL TABS, ALL FIELDS)
    def filter_items_global(self, text):
        search_text = text.strip().lower()
        first_match_tab_index = -1

        # Determine which column indices correspond to headers we care about.
        # This makes the search resilient to adding/removing columns.
        for tab_index in range(self.tabs.count()):
            table = self.tabs.widget(tab_index)
            table_has_match = False

            # Build mapping of header->index for this table
            header_to_index = {}
            for col in range(table.columnCount()):
                header = (
                    table.horizontalHeaderItem(col).text().strip().lower()
                    if table.horizontalHeaderItem(col)
                    else ""
                )
                header_to_index[header] = col

            # find indices safely (fallback to known defaults if headers missing)
            name_idx = header_to_index.get("item name", 0)
            size_idx = header_to_index.get("size", 1)
            cost_idx = header_to_index.get("cost price (mk)", 2)
            price_idx = header_to_index.get("unit price (mk)", 3)
            qty_idx = header_to_index.get("quantity", 4)

            for row in range(table.rowCount()):
                # Safely read each cell (some might be None)
                def safe_text(r, c):
                    it = table.item(r, c)
                    return it.text().lower() if it and it.text() is not None else ""

                name = safe_text(row, name_idx)
                size = safe_text(row, size_idx)
                cost = safe_text(row, cost_idx)
                price = safe_text(row, price_idx)
                quantity = safe_text(row, qty_idx)

                if search_text == "":
                    table.setRowHidden(row, False)
                    table_has_match = True
                else:
                    matches = (
                        search_text in name
                        or (size and search_text in size)
                        or (cost and search_text in cost)
                        or (price and search_text in price)
                        or (quantity and search_text in quantity)
                    )
                    table.setRowHidden(row, not matches)
                    if matches:
                        table_has_match = True

            if table_has_match and first_match_tab_index == -1:
                first_match_tab_index = tab_index

        if first_match_tab_index != -1:
            self.tabs.setCurrentIndex(first_match_tab_index)

    def open_add_item_dialog(self):
        dialog = AddItemDialog(self)
        dialog.item_saved.connect(self.load_items)
        if dialog.exec_():
            self.load_items()

    def open_add_category_dialog(self):
        dialog = AddCategoryDialog(self)
        if dialog.exec_():
            self.load_categories()

    def update_item(self, item):
        """
        Updated behavior: allow admin to edit Selling Price (unit_price),
        Cost Price (cost_price), and add Quantity in one flow.
        This keeps previous 'add stock' behavior while letting admin fix prices.
        """

        # Ask for new unit price (pre-filled)
        price, ok_price = self.get_double_input(
            "Update Selling Price",
            "Unit Price (MK):",
            float(item.unit_price),
            0,
            9999999,
            2,
        )
        if not ok_price:
            return

        # Ask for new cost price (pre-filled). Default to existing.
        cost, ok_cost = self.get_double_input(
            "Update Cost Price",
            "Cost Price (MK):",
            float(item.cost_price) if item.cost_price is not None else 0.0,
            0,
            9999999,
            2,
        )
        if not ok_cost:
            return

        # Ask for quantity to add (preserves previous behavior)
        qty, ok_qty = self.get_double_input(
            "Add Stock", "Quantity to add:", 0, -999999, 999999, 3
        )
        if not ok_qty:
            return

        # Apply updates
        try:
            item.unit_price = Decimal(str(price))
            item.cost_price = Decimal(str(cost))
            delta = Decimal(str(qty))
            if delta != 0:
                item.quantity_in_stock += delta
            item.save()
            if delta != 0:
                # Sync-safe: record the additive change (after the local save)
                # so it reaches the central server and other devices exactly once.
                StockAdjustment.objects.create(
                    item=item, delta=delta, details="Manual stock update"
                )
            self.load_items()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to update item: {e}")

    def format_quantity(self, qty):
        text = format(qty, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    def get_double_input(self, title, label, value, min_value, max_value, decimals):
        dialog = QtWidgets.QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setInputMode(QtWidgets.QInputDialog.DoubleInput)
        dialog.setDoubleDecimals(decimals)
        dialog.setDoubleRange(min_value, max_value)
        dialog.setDoubleValue(value)
        dialog.setWindowFlags(
            dialog.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
        ok = dialog.exec_() == QtWidgets.QDialog.Accepted
        return dialog.doubleValue(), ok

    def handle_item_changed(self, item):
        if item is None:
            return
        if item.column() not in (0, 1):
            return

        item_id = item.data(QtCore.Qt.UserRole)
        if not item_id:
            return

        new_text = item.text().strip()
        if item.column() == 0 and not new_text:
            QtWidgets.QMessageBox.warning(self, "Error", "Item name cannot be empty")
            self.reload_item_cell(item, item_id)
            return

        field = "name" if item.column() == 0 else "size"
        label = "name" if field == "name" else "size"
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirm Update",
            f"Update item {label} to '{new_text}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            self.reload_item_cell(item, item_id)
            return

        try:
            db_item = Item.objects.get(pk=item_id)
            if field == "name":
                db_item.name = new_text
            else:
                db_item.size = new_text
            db_item.save()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to update: {e}")
            self.reload_item_cell(item, item_id)

    def reload_item_cell(self, table_item, item_id):
        try:
            db_item = Item.objects.get(pk=item_id)
        except Exception:
            return
        table = table_item.tableWidget()
        if table is None:
            return
        row = table_item.row()
        table.blockSignals(True)
        if table_item.column() == 0:
            table_item.setText(db_item.name)
        else:
            table_item.setText(db_item.size or "")
        table.blockSignals(False)

    def delete_item(self, item):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete '{item.name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )

        if reply == QtWidgets.QMessageBox.Yes:
            # Soft-delete so the removal syncs to the server/other devices.
            item.deleted = True
            item.save()
            self.load_items()

    def open_manage_categories(self):
        dialog = ManageCategoriesWindow(self)
        if dialog.exec_():
            self.load_categories()
