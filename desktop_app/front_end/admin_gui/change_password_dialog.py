from PyQt5 import QtWidgets, QtCore, QtGui
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from sales.admin_auth import AdminAuthManager


class ChangePasswordDialog(QtWidgets.QDialog):
    def __init__(self, admin_user, parent=None):
        super().__init__(parent)

        # Remove the "?" (context help button) from dialog
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)

        self.admin_user = admin_user

        self.setWindowTitle("Change Password - NASS")
        self.resize(400, 300)
        self.setModal(True)

        # Center the dialog
        self.center_window()

        # Main layout
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Title
        title = QtWidgets.QLabel("Change Password")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; margin-bottom: 20px; color: #2c3e50;"
        )
        layout.addWidget(title)

        # Form layout
        form_layout = QtWidgets.QFormLayout()
        form_layout.setSpacing(15)

        # Current Password
        current_pwd_label = QtWidgets.QLabel("Current Password:")
        self.current_pwd_input = QtWidgets.QLineEdit()
        self.current_pwd_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.current_pwd_input.setPlaceholderText("Enter your current password")
        form_layout.addRow(current_pwd_label, self.current_pwd_input)

        # New Password
        new_pwd_label = QtWidgets.QLabel("New Password:")
        self.new_pwd_input = QtWidgets.QLineEdit()
        self.new_pwd_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.new_pwd_input.setPlaceholderText("Enter new password (min 4 characters)")
        form_layout.addRow(new_pwd_label, self.new_pwd_input)

        # Confirm New Password
        confirm_pwd_label = QtWidgets.QLabel("Confirm New Password:")
        self.confirm_pwd_input = QtWidgets.QLineEdit()
        self.confirm_pwd_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.confirm_pwd_input.setPlaceholderText("Confirm your new password")
        form_layout.addRow(confirm_pwd_label, self.confirm_pwd_input)

        layout.addLayout(form_layout)

        # Password strength indicator
        self.strength_label = QtWidgets.QLabel()
        self.strength_label.setStyleSheet(
            "color: #95a5a6; font-size: 12px; margin-top: 10px;"
        )
        self.new_pwd_input.textChanged.connect(self.check_password_strength)
        layout.addWidget(self.strength_label)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        save_btn = QtWidgets.QPushButton("Change Password")
        save_btn.setStyleSheet(
            "background-color: #27ae60; color: white; padding: 8px 20px; border-radius: 4px; font-weight: bold;"
        )
        save_btn.clicked.connect(self.change_password)
        button_layout.addWidget(save_btn)

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "background-color: #95a5a6; color: white; padding: 8px 20px; border-radius: 4px;"
        )
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addStretch()
        layout.addLayout(button_layout)

    def center_window(self):
        """Center dialog on parent window or screen"""
        if self.parent():
            parent_geometry = self.parent().geometry()
            center_point = parent_geometry.center()
        else:
            screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
            center_point = screen_geometry.center()

        dialog_geometry = self.frameGeometry()
        dialog_geometry.moveCenter(center_point)
        self.move(dialog_geometry.topLeft())

    def check_password_strength(self):
        """Check and display password strength"""
        password = self.new_pwd_input.text()

        if not password:
            self.strength_label.setText("")
            return

        strength = "Weak"
        color = "#e74c3c"  # Red

        if len(password) >= 8:
            strength = "Fair"
            color = "#f39c12"  # Orange

        if (
            len(password) >= 12
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            strength = "Strong"
            color = "#27ae60"  # Green

        self.strength_label.setText(f"Password Strength: {strength}")
        self.strength_label.setStyleSheet(
            f"color: {color}; font-size: 12px; margin-top: 10px; font-weight: bold;"
        )

    def change_password(self):
        """Handle password change"""
        current_pwd = self.current_pwd_input.text()
        new_pwd = self.new_pwd_input.text()
        confirm_pwd = self.confirm_pwd_input.text()

        # Validation
        if not current_pwd or not new_pwd or not confirm_pwd:
            QtWidgets.QMessageBox.warning(
                self, "Validation Error", "Please fill in all fields."
            )
            return

        if new_pwd != confirm_pwd:
            QtWidgets.QMessageBox.warning(
                self, "Validation Error", "New passwords do not match."
            )
            return

        # Change password using backend
        success, message = AdminAuthManager.change_password(
            self.admin_user, current_pwd, new_pwd
        )

        if success:
            QtWidgets.QMessageBox.information(self, "Success", message)
            self.accept()
        else:
            QtWidgets.QMessageBox.warning(self, "Error", message)
