from PyQt5 import QtWidgets, QtCore
from decimal import Decimal, InvalidOperation

from sales.models import Item, Category, record_opening_stock


class AddItemDialog(QtWidgets.QDialog):
    item_saved = QtCore.pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)

        # Remove the "?" (context help button) from dialog
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)

        self.setWindowTitle("Add New Item")
        self.setFixedSize(450, 480)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Category dropdown (dynamic)
        self.category_combo = QtWidgets.QComboBox()
        layout.addWidget(self.category_combo)

        # Item Name
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("Item name")
        layout.addWidget(self.name_input)

        # Size
        self.size_input = QtWidgets.QLineEdit()
        self.size_input.setPlaceholderText("Size")
        layout.addWidget(self.size_input)

        # Unit Price (selling price)
        self.price_input = QtWidgets.QLineEdit()
        self.price_input.setPlaceholderText("Selling price (MK)")
        layout.addWidget(self.price_input)

        # Cost Price
        self.cost_input = QtWidgets.QLineEdit()
        self.cost_input.setPlaceholderText("Cost price (MK)")
        layout.addWidget(self.cost_input)

        # Quantity
        self.quantity_input = QtWidgets.QLineEdit()
        self.quantity_input.setPlaceholderText("Quantity in stock (e.g. 1, 0.5)")
        layout.addWidget(self.quantity_input)

        # Save button
        self.save_btn = QtWidgets.QPushButton("Save Item")
        layout.addWidget(self.save_btn)

        # Load categories dynamically
        self.load_categories()

        # Signals
        self.category_combo.currentIndexChanged.connect(self.toggle_size_field)
        self.save_btn.clicked.connect(self.save_item)

        # Keyboard navigation
        self.setup_keyboard_navigation()

        # Set tab order
        self.setTabOrder(self.category_combo, self.name_input)
        self.setTabOrder(self.name_input, self.size_input)
        self.setTabOrder(self.size_input, self.price_input)
        self.setTabOrder(self.price_input, self.cost_input)
        self.setTabOrder(self.cost_input, self.quantity_input)
        self.setTabOrder(self.quantity_input, self.save_btn)

        self.toggle_size_field()

    # ✅ Load categories from database
    def load_categories(self):
        self.category_combo.clear()
        self.categories = list(Category.objects.all().order_by("name"))
        for category in self.categories:
            self.category_combo.addItem(category.name)

    # Keyboard navigation
    def setup_keyboard_navigation(self):
        widgets = [
            self.category_combo,
            self.name_input,
            self.size_input,
            self.price_input,
            self.cost_input,
            self.quantity_input,
            self.save_btn,
        ]
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Down:
                self.focusNextChild()
                return True
            elif event.key() == QtCore.Qt.Key_Up:
                self.focusPreviousChild()
                return True
        return super().eventFilter(obj, event)

    # Enable/Disable size field based on category setting
    def toggle_size_field(self):
        index = self.category_combo.currentIndex()
        if index < 0 or not self.categories:
            self.size_input.setEnabled(False)
            return

        selected_category = self.categories[index]

        if selected_category.size_required:
            self.size_input.setEnabled(True)
            self.size_input.setPlaceholderText("Size (Required)")
        else:
            self.size_input.clear()
            self.size_input.setEnabled(False)
            self.size_input.setPlaceholderText("Size (Not required)")

    # Save item to database
    def save_item(self):
        name = self.name_input.text().strip()
        price = self.price_input.text().strip()
        cost = self.cost_input.text().strip()
        quantity = self.quantity_input.text().strip()
        size = self.size_input.text().strip()

        if not name or not price or not cost or not quantity:
            QtWidgets.QMessageBox.warning(
                self, "Error", "All required fields must be filled"
            )
            return

        try:
            decimal_price = Decimal(price)
            decimal_cost = Decimal(cost)
            decimal_quantity = Decimal(quantity)

            if decimal_price <= 0 or decimal_cost < 0:
                QtWidgets.QMessageBox.warning(
                    self, "Error", "Price and cost must be positive numbers"
                )
                return
            if decimal_quantity < 0:
                QtWidgets.QMessageBox.warning(
                    self, "Error", "Quantity cannot be negative"
                )
                return

        except (InvalidOperation, ValueError):
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                "Price, Cost, and Quantity must be numbers",
            )
            return

        selected_index = self.category_combo.currentIndex()
        if selected_index < 0:
            QtWidgets.QMessageBox.warning(self, "Error", "Please select a category")
            return

        selected_category = self.categories[selected_index]

        # Validate size if required
        if selected_category.size_required and not size:
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                f"Size is required for {selected_category.name}",
            )
            return

        try:
            item = Item.objects.create(
                name=name,
                category=selected_category,
                size=size if size else "",
                unit_price=decimal_price,
                cost_price=decimal_cost,
                quantity_in_stock=decimal_quantity,
            )
            # Record the opening stock as a delta so it syncs as part of the
            # single stock ledger (and replays cleanly on a fresh install).
            record_opening_stock(item, decimal_quantity)

            QtWidgets.QMessageBox.information(
                self, "Success", "Item added successfully"
            )
            self.item_saved.emit()
            self.name_input.clear()
            self.price_input.clear()
            self.cost_input.clear()
            self.quantity_input.clear()
            self.size_input.clear()
            self.toggle_size_field()
            self.name_input.setFocus()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
