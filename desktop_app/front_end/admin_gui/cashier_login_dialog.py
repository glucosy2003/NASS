"""Dialog for cashier login before accessing the sales window."""

from PyQt5 import QtWidgets, QtCore, QtGui


class CashierLoginDialog(QtWidgets.QDialog):
    """Simple login dialog for cashiers. Returns the authenticated user on success."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cashier Login")
        self.setFixedSize(380, 250)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        self.authenticated_user = None

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

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)

        title = QtWidgets.QLabel("Cashier Login")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50; margin-bottom: 5px;")
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Enter your credentials to continue")
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 11px; color: #7f8c8d; margin-bottom: 15px;")
        layout.addWidget(subtitle)

        self.username_input = QtWidgets.QLineEdit()
        self.username_input.setPlaceholderText("Username")
        layout.addWidget(self.username_input)

        layout.addSpacing(5)

        pw_layout = QtWidgets.QHBoxLayout()
        pw_layout.setContentsMargins(0, 0, 0, 0)
        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        pw_layout.addWidget(self.password_input)
        show_pw = QtWidgets.QPushButton("\U0001f441")
        show_pw.setFixedWidth(32)
        show_pw.setCheckable(True)
        show_pw.setStyleSheet("QPushButton { border: 1px solid #ddd; border-radius: 3px; background: white; }")
        show_pw.toggled.connect(lambda checked: self.password_input.setEchoMode(
            QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
        ))
        pw_layout.addWidget(show_pw)
        pw_container = QtWidgets.QWidget()
        pw_container.setLayout(pw_layout)
        layout.addWidget(pw_container)

        layout.addSpacing(5)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("color: #e74c3c; font-size: 11px;")
        self.error_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.error_label)

        layout.addSpacing(10)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(10)

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
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

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
        login_btn.clicked.connect(self.do_login)
        self.password_input.returnPressed.connect(self.do_login)
        buttons.addWidget(login_btn)

        layout.addLayout(buttons)

    def do_login(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
        from sales.admin_auth import AdminAuthManager

        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            self.error_label.setText("Enter username and password.")
            return

        user = AdminAuthManager.authenticate_admin(username, password)
        if user is None:
            self.error_label.setText("Invalid username or password.")
            return
        if not user.is_active:
            self.error_label.setText("Account is deactivated.")
            return
        if user.role != "cashier":
            self.error_label.setText("This login is for cashier accounts only.")
            return

        self.authenticated_user = user
        self.accept()
