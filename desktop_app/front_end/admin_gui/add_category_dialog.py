from PyQt5 import QtWidgets, QtCore
from sales.models import Category


class AddCategoryDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Remove the "?" (context help button) from dialog
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("Add New Category")
        self.setFixedSize(350, 180)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        label = QtWidgets.QLabel("Category Name:")
        layout.addWidget(label)

        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("Enter category name")
        layout.addWidget(self.name_input)

        layout.addStretch()

        btn_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(btn_layout)

        save_btn = QtWidgets.QPushButton("Save")
        cancel_btn = QtWidgets.QPushButton("Cancel")

        save_btn.clicked.connect(self.save_category)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)

    def save_category(self):
        name = self.name_input.text().strip()

        if not name:
            QtWidgets.QMessageBox.warning(self, "Error", "Category name required")
            return

        if Category.objects.filter(name__iexact=name).exists():
            QtWidgets.QMessageBox.warning(self, "Error", "Category already exists")
            return

        Category.objects.create(name=name)
        QtWidgets.QMessageBox.information(
            self, "Success", "Category added successfully"
        )
        self.accept()
