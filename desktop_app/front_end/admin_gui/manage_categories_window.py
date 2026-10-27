from PyQt5 import QtWidgets, QtCore
from django.db import IntegrityError

from sales.models import Category, Item


class ManageCategoriesWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Remove the "?" (context help button) from dialog
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)

        self.setWindowTitle("Manage Categories")
        self.setFixedSize(600, 400)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Table
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Category Name", "Size Required", "Edit", "Delete"]
        )
        layout.addWidget(self.table)

        # Add Category Button
        self.add_btn = QtWidgets.QPushButton("➕ Add Category")
        self.add_btn.clicked.connect(self.add_category)
        layout.addWidget(self.add_btn)

        self.load_categories()

    def load_categories(self):
        self.table.setRowCount(0)
        categories = Category.objects.filter(deleted=False).order_by("name")

        for category in categories:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(category.name))

            size_text = "Yes" if category.size_required else "No"
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(size_text))

            edit_btn = QtWidgets.QPushButton("Edit")
            edit_btn.clicked.connect(lambda _, c=category: self.edit_category(c))
            self.table.setCellWidget(row, 2, edit_btn)

            delete_btn = QtWidgets.QPushButton("Delete")
            delete_btn.clicked.connect(lambda _, c=category: self.delete_category(c))
            self.table.setCellWidget(row, 3, delete_btn)

    def add_category(self):
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Category", "Category Name:"
        )
        if not ok or not name.strip():
            return

        size_required = (
            QtWidgets.QMessageBox.question(
                self,
                "Size Required?",
                "Should this category require size?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            == QtWidgets.QMessageBox.Yes
        )

        if Category.objects.filter(name__iexact=name.strip()).exists():
            QtWidgets.QMessageBox.warning(self, "Error", "Category already exists")
            return

        Category.objects.create(name=name.strip(), size_required=size_required)

        self.load_categories()

    def edit_category(self, category):
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Edit Category", "Category Name:", text=category.name
        )
        if not ok or not name.strip():
            return

        size_required = (
            QtWidgets.QMessageBox.question(
                self,
                "Size Required?",
                "Should this category require size?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            == QtWidgets.QMessageBox.Yes
        )

        if (
            Category.objects.filter(name__iexact=name.strip())
            .exclude(id=category.id)
            .exists()
        ):
            QtWidgets.QMessageBox.warning(self, "Error", "Category already exists")
            return

        category.name = name.strip()
        category.size_required = size_required
        try:
            category.save()
        except IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Error", "Category already exists")
            return

        self.load_categories()

    def delete_category(self, category):
        if Item.objects.filter(category=category, deleted=False).exists():
            QtWidgets.QMessageBox.warning(
                self, "Cannot Delete", "This category has items. Delete items first."
            )
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete '{category.name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )

        if reply == QtWidgets.QMessageBox.Yes:
            category.deleted = True
            category.save(update_fields=["deleted"])
            self.load_categories()
