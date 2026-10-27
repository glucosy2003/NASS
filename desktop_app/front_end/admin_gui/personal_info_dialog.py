from PyQt5 import QtWidgets, QtCore
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from sales.admin_auth import AdminAuthManager
from django.utils import timezone


class PersonalInfoDialog(QtWidgets.QDialog):
    def __init__(self, admin_user, parent=None):
        super().__init__(parent)

        # Remove the "?" (context help button) from dialog
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)

        self.admin_user = admin_user

        self.setWindowTitle("Personal Information - NASS")
        self.resize(450, 400)
        self.setModal(True)

        # Center the dialog
        self.center_window()

        # Main layout
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Title
        title = QtWidgets.QLabel("Personal Information")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; margin-bottom: 20px; color: #2c3e50;"
        )
        layout.addWidget(title)

        # Create scroll area for better layout
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout()
        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)

        # Form layout
        form_layout = QtWidgets.QFormLayout()
        form_layout.setSpacing(15)

        # Username (read-only)
        username_label = QtWidgets.QLabel("Username:")
        self.username_display = QtWidgets.QLineEdit()
        self.username_display.setText(admin_user.username)
        self.username_display.setReadOnly(True)
        self.username_display.setStyleSheet(
            "background-color: #ecf0f1; color: #7f8c8d;"
        )
        form_layout.addRow(username_label, self.username_display)

        # Full Name (editable)
        fullname_label = QtWidgets.QLabel("Full Name:")
        self.fullname_input = QtWidgets.QLineEdit()
        self.fullname_input.setText(admin_user.full_name or "")
        self.fullname_input.setPlaceholderText("Enter your full name")
        form_layout.addRow(fullname_label, self.fullname_input)

        # Email (editable)
        email_label = QtWidgets.QLabel("Email:")
        self.email_input = QtWidgets.QLineEdit()
        self.email_input.setText(admin_user.email or "")
        self.email_input.setPlaceholderText("Enter your email address")
        form_layout.addRow(email_label, self.email_input)

        scroll_layout.addLayout(form_layout)

        # Account Information Section
        info_group = QtWidgets.QGroupBox("Account Information")
        info_layout = QtWidgets.QVBoxLayout()

        # Created date
        created_label = QtWidgets.QLabel()
        created_date = (
            timezone.localtime(admin_user.created_at).strftime("%Y-%m-%d %H:%M:%S")
            if admin_user.created_at
            else "N/A"
        )
        created_label.setText(f"<b>Account Created:</b> {created_date}")
        created_label.setStyleSheet("color: #2c3e50; font-size: 12px;")
        info_layout.addWidget(created_label)

        # Last login
        last_login_label = QtWidgets.QLabel()
        last_login_date = (
            timezone.localtime(admin_user.last_login).strftime("%Y-%m-%d %H:%M:%S")
            if admin_user.last_login
            else "Never"
        )
        last_login_label.setText(f"<b>Last Login:</b> {last_login_date}")
        last_login_label.setStyleSheet("color: #2c3e50; font-size: 12px;")
        info_layout.addWidget(last_login_label)

        # Password changed date
        pwd_changed_label = QtWidgets.QLabel()
        pwd_changed_date = (
            timezone.localtime(admin_user.last_password_changed).strftime("%Y-%m-%d %H:%M:%S")
            if admin_user.last_password_changed
            else "N/A"
        )
        pwd_changed_label.setText(f"<b>Last Password Change:</b> {pwd_changed_date}")
        pwd_changed_label.setStyleSheet("color: #2c3e50; font-size: 12px;")
        info_layout.addWidget(pwd_changed_label)

        # Active status
        status_label = QtWidgets.QLabel()
        status_text = "Active" if admin_user.is_active else "Inactive"
        status_color = "#27ae60" if admin_user.is_active else "#e74c3c"
        status_label.setText(
            f"<b>Account Status:</b> <span style='color: {status_color}; font-weight: bold;'>{status_text}</span>"
        )
        status_label.setStyleSheet("color: #2c3e50; font-size: 12px;")
        info_layout.addWidget(status_label)

        info_group.setLayout(info_layout)
        scroll_layout.addWidget(info_group)

        scroll_layout.addStretch()

        layout.addWidget(scroll_area)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        save_btn = QtWidgets.QPushButton("Save Changes")
        save_btn.setStyleSheet(
            "background-color: #3498db; color: white; padding: 8px 20px; border-radius: 4px; font-weight: bold;"
        )
        save_btn.clicked.connect(self.save_info)
        button_layout.addWidget(save_btn)

        cancel_btn = QtWidgets.QPushButton("Close")
        cancel_btn.setStyleSheet(
            "background-color: #95a5a6; color: white; padding: 8px 20px; border-radius: 4px;"
        )
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

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

    def save_info(self):
        """Save personal information updates"""
        full_name = self.fullname_input.text().strip()
        email = self.email_input.text().strip()

        # Validation
        if email and "@" not in email:
            QtWidgets.QMessageBox.warning(
                self, "Validation Error", "Please enter a valid email address."
            )
            return

        # Update using backend
        success, message = AdminAuthManager.update_admin_info(
            self.admin_user,
            full_name=full_name if full_name else None,
            email=email if email else None,
        )

        if success:
            QtWidgets.QMessageBox.information(self, "Success", message)
            self.accept()
        else:
            QtWidgets.QMessageBox.warning(self, "Error", message)
