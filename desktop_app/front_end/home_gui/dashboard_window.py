from PyQt5 import QtWidgets, QtGui, QtCore
from styles import colors
from front_end.home_gui.sales_window import SalesWindow
from resource_paths import asset_path
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from django.conf import settings
from sales.admin_auth import AdminAuthManager
from sales.models import AdminUser

from sync.autosync import AutoSync
from sync.config import SyncConfig


class DashboardWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        # Window settings
        self.setWindowTitle(f"NASS v{settings.NASS_VERSION}")
        self.resize(800, 500)
        self.center_window()
        self.setStyleSheet(f"background-color: {colors.BACKGROUND_COLOR};")

        # Main layout
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout()
        central_widget.setLayout(layout)

        # Header label
        header = QtWidgets.QLabel("Welcome to")
        header.setAlignment(QtCore.Qt.AlignCenter)
        header.setStyleSheet(
            f"color: {colors.PRIMARY_COLOR}; font-size: 24px; font-weight: bold;"
        )
        layout.addWidget(header)

        # Logo
        logo_label = QtWidgets.QLabel()
        logo_pixmap = QtGui.QPixmap(asset_path("logo.png"))

        if not logo_pixmap.isNull():
            LOGO_WIDTH = 350
            scaled_pixmap = logo_pixmap.scaledToWidth(
                LOGO_WIDTH, QtCore.Qt.SmoothTransformation
            )
            logo_label.setPixmap(scaled_pixmap)

        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(logo_label)

        layout.addSpacing(30)

        # Buttons layout
        btn_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(btn_layout)

        # Make a Sale Button
        self.sales_btn = QtWidgets.QPushButton("Make a Sale")
        self.sales_btn.setStyleSheet(
            f"background-color: {colors.PRIMARY_COLOR}; color: white; padding: 10px; font-size: 16px;"
        )
        btn_layout.addWidget(self.sales_btn)
        self.sales_btn.clicked.connect(self.open_sales_window)

        # Admin Panel Button
        self.admin_btn = QtWidgets.QPushButton("Admin Panel")
        self.admin_btn.setStyleSheet(
            "background-color: #DC143C; color: white; padding: 10px; font-size: 16px;"
        )
        btn_layout.addWidget(self.admin_btn)
        self.admin_btn.clicked.connect(self.open_admin_panel)

        # -----------------------------
        # BACKGROUND AUTO-SYNC (no visible UI here)
        # -----------------------------
        self.autosync = AutoSync(self)
        self.autosync.start()
        QtCore.QTimer.singleShot(500, self.maybe_prompt_first_run)

    # ===============================
    # CENTER WINDOW
    # ===============================
    def center_window(self):
        screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    # ===============================
    # SYNC ACTIONS
    # ===============================
    def open_sync_settings(self):
        from front_end.sync_gui.sync_settings_dialog import SyncSettingsDialog

        dialog = SyncSettingsDialog(self, config=self.autosync.config)
        dialog.exec_()
        self.autosync.reload()
        self.autosync.start()

    def maybe_prompt_first_run(self):
        if self.autosync.config.is_configured:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Connect to server",
            "Connect this PC to the central NASS server?\n\n"
            "This restores all items, sales and accounts and keeps this "
            "device in sync. You can skip and this device will run offline "
            "only.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self.open_sync_settings()

    # ===============================
    # OPEN SALES WINDOW (requires cashier login if enabled)
    # ===============================
    def open_sales_window(self):
        from sales.models import AdminUser

        # Check if any cashier has desktop_password_required=True
        cashiers_need_login = AdminUser.objects.filter(
            role="cashier", is_active=True, deleted=False, desktop_password_required=True
        ).exists()

        current_user = None
        if cashiers_need_login:
            from front_end.admin_gui.cashier_login_dialog import CashierLoginDialog

            login_dialog = CashierLoginDialog(self)
            if login_dialog.exec_() != QtWidgets.QDialog.Accepted:
                return
            current_user = login_dialog.authenticated_user

        self.sales_window = SalesWindow(
            autosync=self.autosync,
            current_user=current_user,
        )

        # When sales window closes → show dashboard again
        self.sales_window.destroyed.connect(self.show)

        self.sales_window.show()

        # Hide dashboard instead of closing
        self.hide()

    # ===============================
    # OPEN ADMIN PANEL (WITH LOGIN)
    # ===============================
    def open_admin_panel(self):
        # First-run flow: require creating the first owner account in-app.
        if not AdminUser.objects.exists():
            from front_end.admin_gui.setup_owner_dialog import SetupOwnerDialog

            setup_dialog = SetupOwnerDialog(self)
            setup_dialog.exec_()

            if not AdminUser.objects.exists():
                QtWidgets.QMessageBox.warning(
                    self,
                    "Setup Required",
                    "You must create an owner account before using Admin Panel.",
                )
                return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Admin Login")
        dialog.setFixedSize(380, 250)
        dialog.setModal(True)

        dialog.setWindowFlags(
            dialog.windowFlags()
            & ~QtCore.Qt.WindowContextHelpButtonHint
            & ~QtCore.Qt.WindowMinMaxButtonsHint
        )

        screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
        dialog_geometry = dialog.frameGeometry()
        dialog_geometry.moveCenter(screen_geometry.center())
        dialog.move(dialog_geometry.topLeft())

        dialog.setStyleSheet("""
            QDialog {
                background-color: #f0f2f5;
            }
            QLineEdit {
                border: 1px solid #dcdde1;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
                background-color: white;
            }
            QLineEdit:focus {
                border: 1px solid #3498db;
            }
        """)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(30, 20, 30, 20)

        title = QtWidgets.QLabel("Admin Login")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50; margin-bottom: 5px;")
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Enter your credentials to continue")
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 11px; color: #7f8c8d; margin-bottom: 15px;")
        layout.addWidget(subtitle)

        username_input = QtWidgets.QLineEdit()
        username_input.setPlaceholderText("Username")
        layout.addWidget(username_input)

        layout.addSpacing(5)

        password_input = QtWidgets.QLineEdit()
        password_input.setPlaceholderText("Password")
        password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        pw_layout = QtWidgets.QHBoxLayout()
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.addWidget(password_input)
        show_pw = QtWidgets.QPushButton("👁")
        show_pw.setFixedWidth(32)
        show_pw.setCheckable(True)
        show_pw.setStyleSheet("QPushButton { border: 1px solid #ddd; border-radius: 3px; background: white; }")
        show_pw.toggled.connect(lambda checked: password_input.setEchoMode(
            QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
        ))
        pw_layout.addWidget(show_pw)
        pw_container = QtWidgets.QWidget()
        pw_container.setLayout(pw_layout)
        layout.addWidget(pw_container)

        layout.addSpacing(10)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(10)

        login_btn = QtWidgets.QPushButton("Login")
        login_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        login_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 8px 0px;
                font-size: 12px;
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #219a52; }
        """)
        button_layout.addWidget(login_btn)

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #555;
                padding: 8px 0px;
                font-size: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #d0d0d0; }
        """)
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        dialog.setLayout(layout)

        # ===============================
        # LOGIN ATTEMPT
        # ===============================
        def attempt_login():
            username = username_input.text().strip()
            password = password_input.text()

            if not username or not password:
                QtWidgets.QMessageBox.warning(
                    dialog, "Input Error", "Please enter username and password."
                )
                return

            admin_user = AdminAuthManager.authenticate_admin(username, password)

            if admin_user:
                if not admin_user.is_admin:
                    QtWidgets.QMessageBox.warning(
                        dialog,
                        "Access Denied",
                        "This account is a cashier and cannot open the Admin "
                        "Panel. Use 'Make a Sale' instead.",
                    )
                    password_input.clear()
                    return
                dialog.accept()

                from front_end.admin_gui.admin_dashboard_window import (
                    AdminDashboardWindow,
                )

                self.admin_dashboard_window = AdminDashboardWindow(
                    admin_user, autosync=self.autosync
                )

                # When admin window closes → show dashboard again
                self.admin_dashboard_window.destroyed.connect(self.show)

                self.admin_dashboard_window.show()

                # Hide dashboard
                self.hide()

            else:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Authentication Failed",
                    "Invalid username or password. Access denied.",
                )
                password_input.clear()
                password_input.setFocus()

        login_btn.clicked.connect(attempt_login)
        cancel_btn.clicked.connect(dialog.reject)
        password_input.returnPressed.connect(attempt_login)

        dialog.exec_()
