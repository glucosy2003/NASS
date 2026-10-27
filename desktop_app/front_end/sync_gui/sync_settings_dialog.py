"""Sync settings dialog: Connect or Disconnect from central server.

Two states:
- Disconnected: show connect form (server URL, username, password, device name)
- Connected: show connection status + Disconnect button (requires admin password)
"""

from PyQt5 import QtCore, QtWidgets, QtGui

from sync import profile
from sync.client import ApiError, NASSClient, NotAuthenticated
from sync.config import SyncConfig
from sync.profile import ProfileViolation
from sync.workers import SyncThread


class SyncSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, config=None, admin_user=None):
        super().__init__(parent)
        self.config = config or SyncConfig.load()
        self.admin_user = admin_user
        self._thread = None

        self.setWindowTitle("Sync Settings - NASS")
        self.setModal(True)
        self.setFixedSize(480, 470)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)

        self.setStyleSheet("""
            QDialog { background-color: #f0f2f5; }
            QLineEdit {
                border: 1px solid #dcdde1;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
                background-color: white;
            }
            QLineEdit:focus { border: 1px solid #3498db; }
        """)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(25, 20, 25, 20)
        self.main_layout.setSpacing(10)

        self._build_ui()

        if self.config.is_configured:
            self._show_connected()
        else:
            self._show_disconnected()

    # ------------------------------------------------------------------
    # UI builders
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.title_label = QtWidgets.QLabel()
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        self.main_layout.addWidget(self.title_label)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.main_layout.addWidget(self.status_label)

        self.main_layout.addSpacing(5)

        # --- Connected state widgets ---
        self.connected_frame = QtWidgets.QFrame()
        self.connected_frame.setStyleSheet("QFrame { background: white; border: 1px solid #ddd; border-radius: 6px; }")
        connected_layout = QtWidgets.QVBoxLayout(self.connected_frame)
        connected_layout.setContentsMargins(15, 15, 15, 15)

        self.server_info = QtWidgets.QLabel()
        self.server_info.setWordWrap(True)
        self.server_info.setStyleSheet("font-size: 12px; color: #2c3e50;")
        connected_layout.addWidget(self.server_info)

        connected_layout.addSpacing(10)

        self.disconnect_btn = QtWidgets.QPushButton("Disconnect from Server")
        self.disconnect_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.disconnect_btn.setFixedHeight(36)
        self.disconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #c0392b; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.disconnect_btn.clicked.connect(self._disconnect)
        connected_layout.addWidget(self.disconnect_btn)

        self.main_layout.addWidget(self.connected_frame)

        # --- Disconnected state: connect form ---
        self.connect_frame = QtWidgets.QFrame()
        self.connect_frame.setStyleSheet("QFrame { background: white; border: 1px solid #ddd; border-radius: 6px; }")
        frame_layout = QtWidgets.QVBoxLayout(self.connect_frame)
        frame_layout.setContentsMargins(15, 15, 15, 15)
        frame_layout.setSpacing(8)

        form_layout = QtWidgets.QFormLayout()
        form_layout.setSpacing(8)

        self.server_input = QtWidgets.QLineEdit()
        self.server_input.setPlaceholderText(profile.default_server_url())
        # Pre-fill the server this build is allowed to talk to, so the correct
        # host is one click away instead of being typed from memory.
        if not self.config.server_url:
            self.server_input.setText(profile.default_server_url())
        form_layout.addRow("Server URL:", self.server_input)

        self.device_input = QtWidgets.QLineEdit()
        self.device_input.setPlaceholderText("e.g. Front counter PC")
        form_layout.addRow("Device name:", self.device_input)

        frame_layout.addLayout(form_layout)

        # Two connection modes: existing account login or one-time code.
        self.mode_tabs = QtWidgets.QTabWidget()
        self.mode_tabs.setStyleSheet(
            "QTabBar::tab { padding: 6px 14px; font-size: 12px; }"
        )

        # --- Tab 1: account login ---
        login_tab = QtWidgets.QWidget()
        login_layout = QtWidgets.QFormLayout(login_tab)
        login_layout.setContentsMargins(4, 10, 4, 4)
        login_layout.setSpacing(8)

        self.username_input = QtWidgets.QLineEdit()
        self.username_input.setPlaceholderText("Server username")
        login_layout.addRow("Username:", self.username_input)

        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password_input.setPlaceholderText("Server password")
        pw_layout = QtWidgets.QHBoxLayout()
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.addWidget(self.password_input)
        show_pw = QtWidgets.QPushButton("\U0001f441")
        show_pw.setFixedWidth(32)
        show_pw.setCheckable(True)
        show_pw.setStyleSheet("QPushButton { border: 1px solid #ddd; border-radius: 3px; background: white; }")
        show_pw.toggled.connect(lambda checked: self.password_input.setEchoMode(
            QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
        ))
        pw_layout.addWidget(show_pw)
        pw_widget = QtWidgets.QWidget()
        pw_widget.setLayout(pw_layout)
        login_layout.addRow("Password:", pw_widget)

        self.mode_tabs.addTab(login_tab, "Account")

        # --- Tab 2: connection hash from the server console ---
        pairing_tab = QtWidgets.QWidget()
        pairing_layout = QtWidgets.QFormLayout(pairing_tab)
        pairing_layout.setContentsMargins(4, 10, 4, 4)
        pairing_layout.setSpacing(8)

        self.code_input = QtWidgets.QLineEdit()
        self.code_input.setPlaceholderText("NASS-XXXX... (from the server console)")
        pairing_layout.addRow("Connection hash:", self.code_input)

        hash_hint = QtWidgets.QLabel(
            "Ask your server operator to run a Bash console on PythonAnywhere:\n"
            '    python manage.py generate_connection_hash --label "My Shop"\n'
            "and paste the printed hash here. Your desktop account connects "
            "automatically — no password to type."
        )
        hash_hint.setWordWrap(True)
        hash_hint.setStyleSheet("font-size: 11px; color: #7f8c8d;")
        pairing_layout.addRow("", hash_hint)

        self.mode_tabs.addTab(pairing_tab, "Connection Hash")
        self.mode_tabs.setCurrentIndex(1)

        frame_layout.addWidget(self.mode_tabs)

        self.main_layout.addWidget(self.connect_frame)

        # --- Bottom buttons ---
        self.btn_layout = QtWidgets.QHBoxLayout()
        self.btn_layout.setSpacing(8)

        self.test_btn = QtWidgets.QPushButton("Test Connection")
        self.test_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.test_btn.setFixedHeight(36)
        self.test_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #3498db;
                padding: 8px 12px;
                font-size: 12px;
                border: 1px solid #3498db;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #ebf5fb; }
            QPushButton:disabled { color: #bdc3c7; border-color: #bdc3c7; }
        """)
        self.test_btn.clicked.connect(self._test_connection)
        self.btn_layout.addWidget(self.test_btn)

        self.btn_layout.addStretch()

        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.cancel_btn.setFixedHeight(36)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #555;
                padding: 8px 16px;
                font-size: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #ecf0f1; }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        self.btn_layout.addWidget(self.cancel_btn)

        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.connect_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.connect_btn.setFixedHeight(36)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #219a52; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.connect_btn.clicked.connect(self._connect)
        self.btn_layout.addWidget(self.connect_btn)

        self.main_layout.addLayout(self.btn_layout)

        self.password_input.returnPressed.connect(self._connect)

    # ------------------------------------------------------------------
    # State switching
    # ------------------------------------------------------------------
    def _show_connected(self):
        self.title_label.setText("Connected to Server")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #27ae60;")
        self.status_label.setText("Sync is active. Data is automatically synchronized.")
        self.status_label.setStyleSheet("font-size: 12px; color: #7f8c8d;")

        server = self.config.server_url
        device = self.config.device_id
        last = self.config.last_sync_at or "Never"
        if last and last != "Never":
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(last)
                last = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass
        self.server_info.setText(
            f"<b>Server:</b> {server}<br>"
            f"<b>Device:</b> {device}<br>"
            f"<b>Last sync:</b> {last}"
        )

        self.connected_frame.show()
        self.connect_frame.hide()
        self.test_btn.hide()
        self.connect_btn.hide()
        self.cancel_btn.show()

    def _show_disconnected(self):
        self.title_label.setText("Connect to Server")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        if profile.is_development():
            # Never let a developer mistake this build for the shop build.
            self.status_label.setText(
                "DEVELOPMENT BUILD - syncs to your own sandbox server only. "
                "The production server is blocked."
            )
            self.status_label.setStyleSheet("font-size: 12px; color: #e67e22;")
        else:
            self.status_label.setText("Enter your server details to enable sync.")
            self.status_label.setStyleSheet("font-size: 12px; color: #7f8c8d;")

        self.connected_frame.hide()
        self.connect_frame.show()
        self.test_btn.show()
        self.connect_btn.show()
        self.cancel_btn.show()

    def _set_busy(self, busy):
        for w in (self.test_btn, self.connect_btn, self.cancel_btn, self.disconnect_btn):
            w.setEnabled(not busy)

    def _set_status(self, text, error=False):
        color = "#e74c3c" if error else "#27ae60" if not error else "#7f8c8d"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setText(text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _test_connection(self):
        url = self.server_input.text().strip()
        if not url:
            self._set_status("Enter a server URL first.", error=True)
            return
        self._set_busy(True)
        self._set_status("Testing connection...")
        try:
            health = NASSClient(server_url=url).health()
            status = health.get("status", "?")
            self._set_status(f"Server reachable ({status})")
        except ProfileViolation as exc:
            self._set_status(str(exc).splitlines()[0], error=True)
        except ApiError as exc:
            self._set_status(f"Connection failed: {exc}", error=True)
        finally:
            self._set_busy(False)

    def _connect(self):
        url = self.server_input.text().strip()
        device = self.device_input.text().strip() or "NASS"

        if not url:
            self._set_status("Server URL is required.", error=True)
            return

        pairing_mode = self.mode_tabs.currentIndex() == 1
        if pairing_mode:
            self._pair_with_hash(url, device)
            return

        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self._set_status("Username and password are required.", error=True)
            return

        self._set_busy(True)
        self._set_status("Logging in...")
        try:
            client = NASSClient(server_url=url)
            resp = client.login(username, password, device_name=device)
        except ProfileViolation as exc:
            self._set_status(str(exc).splitlines()[0], error=True)
            self._set_busy(False)
            return
        except NotAuthenticated:
            self._set_status("Invalid username or password.", error=True)
            self._set_busy(False)
            return
        except ApiError as exc:
            self._set_status(f"Login failed: {exc}", error=True)
            self._set_busy(False)
            return

        self._store_credentials(url, username, resp, device)

    def _pair_with_hash(self, url, device):
        connection_hash = self.code_input.text().strip()
        if not connection_hash:
            self._set_status("Connection hash is required.", error=True)
            return
        if self.admin_user is None:
            self._set_status("Could not find the local admin account to pair with.", error=True)
            return

        self._set_busy(True)
        self._set_status("Pairing with server...")
        try:
            client = NASSClient(server_url=url)
            resp = client.pair(
                connection_hash,
                self.admin_user.username,
                password_hash=self.admin_user.password_hash,
                device_name=device,
            )
        except ProfileViolation as exc:
            self._set_status(str(exc).splitlines()[0], error=True)
            self._set_busy(False)
            return
        except ApiError as exc:
            self._set_status(f"Pairing failed: {exc}", error=True)
            self._set_busy(False)
            return

        username = resp.get("username") or self.admin_user.username
        self._store_credentials(url, username, resp, device)

    def _store_credentials(self, url, username, resp, device):
        self.config.server_url = url
        self.config.username = username
        self.config.set_token(resp["token"])
        self.config.device_id = resp.get("device_id") or self.config.device_id
        self.config.initial_pull_done = False
        # Pairing establishes a brand-new device identity on the server.
        # Any old push cursor is meaningless now: force a FULL push on the next
        # sync so the entire dataset (categories, items, stock adjustments,
        # sales, payments, services, expenses, users) reaches the server —
        # not just rows newer than the previous desktop-local cursor.
        self.config.last_push = None
        self.config.save()

        self._set_status("Downloading data from server...")
        self._thread = SyncThread(self.config, mode="initial", parent=self)
        self._thread.finished_sync.connect(self._on_connect_done)
        self._thread.failed.connect(self._on_connect_failed)
        self._thread.start()

    def _on_connect_done(self, result):
        self.config = SyncConfig.load()
        if result.ok:
            self._set_status("Connected and data restored successfully.")
            self.accept()
        else:
            self._set_status("Connected with errors: " + "; ".join(result.errors[:3]), error=True)
            self._set_busy(False)
            self._show_connected()

    def _on_connect_failed(self, message):
        self.config = SyncConfig.load()
        self._set_status(f"Connection failed: {message}", error=True)
        self._set_busy(False)

    def _disconnect(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Confirm Disconnect")
        dialog.setFixedSize(360, 180)
        dialog.setModal(True)
        dialog.setStyleSheet("QDialog { background-color: #f0f2f5; }")

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(25, 20, 25, 20)

        warning = QtWidgets.QLabel("Enter your admin password to disconnect from the server.")
        warning.setWordWrap(True)
        warning.setStyleSheet("font-size: 12px; color: #2c3e50; margin-bottom: 10px;")
        layout.addWidget(warning)

        pw_layout = QtWidgets.QHBoxLayout()
        pw_input = QtWidgets.QLineEdit()
        pw_input.setEchoMode(QtWidgets.QLineEdit.Password)
        pw_input.setPlaceholderText("Admin password")
        pw_layout.addWidget(pw_input)
        show_pw = QtWidgets.QPushButton("\U0001f441")
        show_pw.setFixedWidth(32)
        show_pw.setCheckable(True)
        show_pw.setStyleSheet("QPushButton { border: 1px solid #ddd; border-radius: 3px; background: white; }")
        show_pw.toggled.connect(lambda checked: pw_input.setEchoMode(
            QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
        ))
        pw_layout.addWidget(show_pw)
        layout.addLayout(pw_layout)

        error_label = QtWidgets.QLabel("")
        error_label.setStyleSheet("color: #e74c3c; font-size: 11px;")
        layout.addWidget(error_label)

        btn_layout = QtWidgets.QHBoxLayout()
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setStyleSheet("padding: 6px 16px; border: 1px solid #ddd; border-radius: 4px; background: white;")
        cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel)

        confirm = QtWidgets.QPushButton("Disconnect")
        confirm.setStyleSheet("background-color: #e74c3c; color: white; padding: 6px 16px; border: none; border-radius: 4px; font-weight: bold;")
        btn_layout.addWidget(confirm)
        layout.addLayout(btn_layout)

        def do_disconnect():
            from sales.admin_auth import AdminAuthManager
            password = pw_input.text()
            if not password:
                error_label.setText("Password is required.")
                return
            if self.admin_user is None:
                error_label.setText("No admin user found.")
                return
            user = AdminAuthManager.authenticate_admin(
                self.admin_user.username, password
            )
            if user is None:
                error_label.setText("Invalid password.")
                return
            if not user.is_admin:
                error_label.setText("Only admin accounts can disconnect.")
                return
            dialog.accept()

        confirm.clicked.connect(do_disconnect)
        pw_input.returnPressed.connect(do_disconnect)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        # Perform disconnect
        from front_end.home_gui.dashboard_window import DashboardWindow
        main_window = self.parent()
        while main_window and not isinstance(main_window, DashboardWindow):
            main_window = main_window.parent() if hasattr(main_window, 'parent') else None

        if main_window and hasattr(main_window, 'autosync') and main_window.autosync:
            main_window.autosync.disconnect()
            self.config = main_window.autosync.config
        else:
            self.config.clear_token()
            self.config.server_url = ""
            self.config.username = ""
            self.config.initial_pull_done = False
            self.config.last_sync_status = ""
            self.config.last_sync_at = None
            self.config.save()

        self._show_disconnected()
        self._set_status("Disconnected from server.")
