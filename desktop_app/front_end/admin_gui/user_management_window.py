"""Admin window for managing user accounts (list, create, edit, activate/deactivate)."""

from PyQt5 import QtWidgets, QtCore, QtGui


class UserManagementWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Users - NASS")
        self.resize(900, 500)
        self.setModal(True)
        self.center_window()

        self.PRIMARY_DARK = "#2c3e50"
        self.ACCENT = "#3498db"
        self.SUCCESS = "#27ae60"
        self.DANGER = "#e74c3c"

        self.setStyleSheet("QDialog { background-color: #f5f6fa; }")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("User Accounts")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50;")
        header.addWidget(title)
        header.addStretch()

        add_btn = QtWidgets.QPushButton("+ Add User")
        add_btn.setStyleSheet(
            f"QPushButton {{ background-color: {self.SUCCESS}; color: white; "
            "padding: 8px 16px; border: none; border-radius: 4px; font-weight: bold; }"
            f"QPushButton:hover {{ background-color: #219a52; }}"
        )
        add_btn.clicked.connect(self.create_user)
        header.addWidget(add_btn)
        layout.addLayout(header)

        layout.addSpacing(10)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Username", "Full Name", "Role", "Desktop Login", "Status", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(55)
        self.table.setStyleSheet(
            "QTableWidget { background-color: white; border: 1px solid #ddd; gridline-color: #eee; }"
            "QHeaderView::section { background-color: #34495e; color: white; padding: 6px; border: none; font-weight: bold; }"
        )
        layout.addWidget(self.table)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setStyleSheet(
            "QPushButton { padding: 8px 20px; border: 1px solid #bdc3c7; border-radius: 4px; background: white; }"
            "QPushButton:hover { background-color: #ecf0f1; }"
        )
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=QtCore.Qt.AlignRight)

        self.reload_users()

    def center_window(self):
        frame = self.frameGeometry()
        center = QtWidgets.QDesktopWidget().availableGeometry().center()
        frame.moveCenter(center)
        self.move(frame.topLeft())

    def reload_users(self):
        from sales.models import AdminUser
        users = AdminUser.objects.filter(deleted=False).order_by("-created_at")
        self.table.setRowCount(len(users))
        for row, user in enumerate(users):
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(user.username))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(user.full_name or ""))

            role_item = QtWidgets.QTableWidgetItem("Admin" if user.role == "admin" else "Cashier")
            role_item.setForeground(QtGui.QColor(self.ACCENT if user.role == "admin" else self.SUCCESS))
            font = role_item.font()
            font.setBold(True)
            role_item.setFont(font)
            self.table.setItem(row, 2, role_item)

            if user.role == "cashier":
                login_text = "Required" if user.desktop_password_required else "Not Required"
                login_item = QtWidgets.QTableWidgetItem(login_text)
                login_item.setForeground(QtGui.QColor("#e67e22" if user.desktop_password_required else self.SUCCESS))
                self.table.setItem(row, 3, login_item)
            else:
                dash = QtWidgets.QTableWidgetItem("—")
                dash.setTextAlignment(QtCore.Qt.AlignCenter)
                self.table.setItem(row, 3, dash)

            status_item = QtWidgets.QTableWidgetItem("Active" if user.is_active else "Inactive")
            status_item.setForeground(QtGui.QColor(self.SUCCESS if user.is_active else self.DANGER))
            self.table.setItem(row, 4, status_item)

            actions_widget = QtWidgets.QWidget()
            actions_layout = QtWidgets.QGridLayout(actions_widget)
            actions_layout.setContentsMargins(4, 2, 4, 2)
            actions_layout.setSpacing(3)

            edit_btn = QtWidgets.QPushButton("Edit")
            edit_btn.setFixedHeight(26)
            edit_btn.setStyleSheet(
                "QPushButton { padding: 2px 8px; border: 1px solid #3498db; border-radius: 3px; color: #3498db; background: white; font-size: 11px; }"
                "QPushButton:hover { background-color: #ebf5fb; }"
            )
            edit_btn.clicked.connect(lambda _, u=user: self.edit_user(u))

            toggle_btn = QtWidgets.QPushButton("Deactivate" if user.is_active else "Activate")
            toggle_btn.setFixedHeight(26)
            toggle_btn.setStyleSheet(
                f"QPushButton {{ padding: 2px 8px; border: 1px solid {self.DANGER if user.is_active else self.SUCCESS}; "
                f"border-radius: 3px; color: {self.DANGER if user.is_active else self.SUCCESS}; background: white; font-size: 11px; }}"
                f"QPushButton:hover {{ background-color: {'#fdedec' if user.is_active else '#eafaf1'}; }}"
            )
            toggle_btn.clicked.connect(lambda _, u=user: self.toggle_user(u))

            if user.role == "cashier":
                toggle_login_btn = QtWidgets.QPushButton("Enable Login" if not user.desktop_password_required else "Disable Login")
                toggle_login_btn.setFixedHeight(26)
                toggle_login_btn.setStyleSheet(
                    f"QPushButton {{ padding: 2px 8px; border: 1px solid {'#e67e22' if not user.desktop_password_required else '#27ae60'}; "
                    f"border-radius: 3px; color: {'#e67e22' if not user.desktop_password_required else '#27ae60'}; background: white; font-size: 11px; }}"
                    f"QPushButton:hover {{ background-color: #fef9e7; }}"
                )
                toggle_login_btn.clicked.connect(lambda _, u=user: self._toggle_desktop_login(u))

                delete_btn = QtWidgets.QPushButton("Delete")
                delete_btn.setFixedHeight(26)
                delete_btn.setStyleSheet(
                    "QPushButton { padding: 2px 8px; border: 1px solid #e74c3c; border-radius: 3px; color: #e74c3c; background: white; font-size: 11px; }"
                    "QPushButton:hover { background-color: #fdedec; }"
                )
                delete_btn.clicked.connect(lambda _, u=user: self._delete_user(u))

                actions_layout.addWidget(edit_btn, 0, 0)
                actions_layout.addWidget(toggle_login_btn, 0, 1)
                actions_layout.addWidget(toggle_btn, 1, 0)
                actions_layout.addWidget(delete_btn, 1, 1)
            else:
                actions_layout.addWidget(edit_btn, 0, 0)
                actions_layout.addWidget(toggle_btn, 0, 1)

            self.table.setCellWidget(row, 5, actions_widget)

    def _toggle_desktop_login(self, user):
        user.desktop_password_required = not user.desktop_password_required
        user.save(update_fields=["desktop_password_required"])
        state = "REQUIRED" if user.desktop_password_required else "NOT REQUIRED"
        QtWidgets.QMessageBox.information(
            self, "Updated", f"Desktop login for '{user.username}' is now {state}."
        )
        self.reload_users()

    def _delete_user(self, user):
        current_user = self.parent().admin_user if hasattr(self.parent(), "admin_user") else None
        if current_user and user.id == current_user.id:
            QtWidgets.QMessageBox.warning(self, "Cannot delete", "You cannot delete your own account.")
            return

        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete",
            f"Permanently delete user '{user.username}'?\n\n"
            "This user will no longer appear in the app. "
            "Synced devices will also remove this user.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            user.deleted = True
            user.is_active = False
            user.save(update_fields=["deleted", "is_active"])
            self.reload_users()

    def create_user(self):
        from sales.admin_auth import AdminAuthManager
        from sales.models import ROLE_CHOICES

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Create User")
        dialog.resize(400, 380)
        dialog.setModal(True)
        dialog.setStyleSheet("QDialog { background-color: #f5f6fa; }")

        form = QtWidgets.QFormLayout(dialog)

        username_input = QtWidgets.QLineEdit()
        username_input.setPlaceholderText("Username")
        form.addRow("Username:", username_input)

        name_input = QtWidgets.QLineEdit()
        name_input.setPlaceholderText("Full Name")
        form.addRow("Full Name:", name_input)

        email_input = QtWidgets.QLineEdit()
        email_input.setPlaceholderText("Email (optional)")
        form.addRow("Email:", email_input)

        password_input = QtWidgets.QLineEdit()
        password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        password_input.setPlaceholderText("Password")
        pw_layout = QtWidgets.QHBoxLayout()
        pw_layout.addWidget(password_input)
        show_pw = QtWidgets.QPushButton("👁")
        show_pw.setFixedWidth(32)
        show_pw.setCheckable(True)
        show_pw.setStyleSheet("QPushButton { border: 1px solid #ddd; border-radius: 3px; background: white; }")
        show_pw.toggled.connect(lambda checked: password_input.setEchoMode(
            QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
        ))
        pw_layout.addWidget(show_pw)
        pw_widget = QtWidgets.QWidget()
        pw_widget.setLayout(pw_layout)
        form.addRow("Password:", pw_widget)

        confirm_input = QtWidgets.QLineEdit()
        confirm_input.setEchoMode(QtWidgets.QLineEdit.Password)
        confirm_input.setPlaceholderText("Confirm password")
        cf_layout = QtWidgets.QHBoxLayout()
        cf_layout.addWidget(confirm_input)
        show_cf = QtWidgets.QPushButton("👁")
        show_cf.setFixedWidth(32)
        show_cf.setCheckable(True)
        show_cf.setStyleSheet("QPushButton { border: 1px solid #ddd; border-radius: 3px; background: white; }")
        show_cf.toggled.connect(lambda checked: confirm_input.setEchoMode(
            QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
        ))
        cf_layout.addWidget(show_cf)
        cf_widget = QtWidgets.QWidget()
        cf_widget.setLayout(cf_layout)
        form.addRow("Confirm:", cf_widget)

        role_combo = QtWidgets.QComboBox()
        role_combo.addItems(["Cashier", "Admin"])
        form.addRow("Role:", role_combo)

        error_label = QtWidgets.QLabel("")
        error_label.setStyleSheet("color: #e74c3c; font-size: 11px;")
        form.addRow(error_label)

        buttons = QtWidgets.QHBoxLayout()
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        save_btn = QtWidgets.QPushButton("Create")
        save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {self.SUCCESS}; color: white; padding: 8px 16px; border: none; border-radius: 4px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #219a52; }}"
        )
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        form.addRow(buttons)

        def do_create():
            username = username_input.text().strip()
            full_name = name_input.text().strip()
            email = email_input.text().strip()
            password = password_input.text()
            confirm = confirm_input.text()
            role = "admin" if role_combo.currentIndex() == 1 else "cashier"

            if not username or not password:
                error_label.setText("Username and password are required.")
                return
            if len(password) < 4:
                error_label.setText("Password must be at least 4 characters.")
                return
            if password != confirm:
                error_label.setText("Passwords do not match.")
                return

            ok, result = AdminAuthManager.create_admin_user(
                username=username, full_name=full_name, email=email or None,
                password=password, role=role,
            )
            if ok:
                dialog.accept()
                self.reload_users()
            else:
                error_label.setText(str(result))

        save_btn.clicked.connect(do_create)
        dialog.exec_()

    def edit_user(self, user):
        from sales.admin_auth import AdminAuthManager

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Edit: {user.username}")
        dialog.resize(400, 280)
        dialog.setModal(True)
        dialog.setStyleSheet("QDialog { background-color: #f5f6fa; }")

        form = QtWidgets.QFormLayout(dialog)

        name_input = QtWidgets.QLineEdit(user.full_name or "")
        name_input.setPlaceholderText("Full Name")
        form.addRow("Full Name:", name_input)

        email_input = QtWidgets.QLineEdit(user.email or "")
        email_input.setPlaceholderText("Email (optional)")
        form.addRow("Email:", email_input)

        role_combo = QtWidgets.QComboBox()
        role_combo.addItems(["Cashier", "Admin"])
        role_combo.setCurrentIndex(0 if user.role == "cashier" else 1)
        form.addRow("Role:", role_combo)

        password_input = QtWidgets.QLineEdit()
        password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        password_input.setPlaceholderText("Leave blank to keep current")
        form.addRow("New Password:", password_input)

        error_label = QtWidgets.QLabel("")
        error_label.setStyleSheet("color: #e74c3c; font-size: 11px;")
        form.addRow(error_label)

        buttons = QtWidgets.QHBoxLayout()
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {self.ACCENT}; color: white; padding: 8px 16px; border: none; border-radius: 4px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #2980b9; }}"
        )
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        form.addRow(buttons)

        def do_save():
            full_name = name_input.text().strip()
            email = email_input.text().strip()
            role = "admin" if role_combo.currentIndex() == 1 else "cashier"
            new_password = password_input.text()

            if email and email != (user.email or ""):
                from sales.models import AdminUser
                if AdminUser.objects.filter(email=email).exclude(id=user.id).exists():
                    error_label.setText("Email already in use.")
                    return

            user.full_name = full_name
            user.email = email or None
            user.role = role
            if new_password:
                if len(new_password) < 4:
                    error_label.setText("Password must be at least 4 characters.")
                    return
                user.set_password(new_password)
            user.save()
            dialog.accept()
            self.reload_users()

        save_btn.clicked.connect(do_save)
        dialog.exec_()

    def toggle_user(self, user):
        current_user = self.parent().admin_user if hasattr(self.parent(), "admin_user") else None
        if current_user and user.id == current_user.id:
            QtWidgets.QMessageBox.warning(self, "Cannot deactivate", "You cannot deactivate your own account.")
            return

        action = "deactivate" if user.is_active else "activate"
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm", f"{action.title()} user '{user.username}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            user.is_active = not user.is_active
            user.save(update_fields=["is_active"])
            self.reload_users()
