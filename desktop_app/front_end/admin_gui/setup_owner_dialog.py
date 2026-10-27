from PyQt5 import QtWidgets, QtCore

from sales.models import AdminUser


class SetupOwnerDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Initial Setup - Create Owner Account")
        self.setModal(True)
        self.setFixedSize(460, 320)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)

        self.center_window()
        self.build_ui()

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        title = QtWidgets.QLabel("Set Up First Admin Account")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(title)

        note = QtWidgets.QLabel(
            "No admin account exists yet.\nCreate the owner password to unlock Admin Panel.\nUsername is fixed as: admin"
        )
        note.setAlignment(QtCore.Qt.AlignCenter)
        note.setStyleSheet("color: #7f8c8d; margin-bottom: 10px;")
        layout.addWidget(note)

        form = QtWidgets.QFormLayout()
        form.setSpacing(10)

        self.full_name_input = QtWidgets.QLineEdit()
        self.full_name_input.setPlaceholderText("Full name")
        form.addRow("Full Name:", self.full_name_input)

        self.email_input = QtWidgets.QLineEdit()
        self.email_input.setPlaceholderText("Email (optional)")
        form.addRow("Email:", self.email_input)

        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password_input.setPlaceholderText("Password (min 4 characters)")
        form.addRow("Password:", self.password_input)

        self.confirm_password_input = QtWidgets.QLineEdit()
        self.confirm_password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.confirm_password_input.setPlaceholderText("Confirm password")
        form.addRow("Confirm Password:", self.confirm_password_input)

        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()

        create_btn = QtWidgets.QPushButton("Create Owner Account")
        create_btn.setStyleSheet(
            "background-color: #27ae60; color: white; padding: 8px 16px; font-weight: bold;"
        )
        create_btn.clicked.connect(self.create_owner_account)
        buttons.addWidget(create_btn)

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        layout.addStretch()
        layout.addLayout(buttons)

    def center_window(self):
        if self.parent():
            center_point = self.parent().geometry().center()
        else:
            center_point = QtWidgets.QApplication.primaryScreen().geometry().center()
        geometry = self.frameGeometry()
        geometry.moveCenter(center_point)
        self.move(geometry.topLeft())

    def create_owner_account(self):
        if AdminUser.objects.exists():
            QtWidgets.QMessageBox.information(
                self, "Already Configured", "An admin account already exists."
            )
            self.accept()
            return

        full_name = self.full_name_input.text().strip()
        username = "admin"
        email = self.email_input.text().strip() or None
        password = self.password_input.text()
        confirm_password = self.confirm_password_input.text()

        if not full_name:
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Full name is required.")
            return

        if len(password) < 4:
            QtWidgets.QMessageBox.warning(
                self, "Validation Error", "Password must be at least 4 characters."
            )
            return

        if password != confirm_password:
            QtWidgets.QMessageBox.warning(
                self, "Validation Error", "Passwords do not match."
            )
            return

        if email and "@" not in email:
            QtWidgets.QMessageBox.warning(
                self, "Validation Error", "Please enter a valid email address."
            )
            return

        if AdminUser.objects.filter(username=username).exists():
            QtWidgets.QMessageBox.warning(
                self, "Validation Error", "Admin account already exists."
            )
            return

        if email and AdminUser.objects.filter(email=email).exists():
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Email already in use.")
            return

        try:
            admin_user = AdminUser(
                username=username,
                full_name=full_name,
                email=email,
                is_active=True,
            )
            admin_user.set_password(password)
            admin_user.save()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Save Failed",
                f"Could not create owner account.\n\n{e}",
            )
            return

        QtWidgets.QMessageBox.information(
            self, "Success", "Owner account created. You can now log in."
        )
        self.accept()
