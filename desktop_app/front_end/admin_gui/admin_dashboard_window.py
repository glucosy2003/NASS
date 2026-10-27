from PyQt5 import QtWidgets, QtCore, QtGui
from styles import colors
from front_end.admin_gui.stock_window import StockWindow
from front_end.admin_gui.profit_loss_window import ProfitLossWindow
from resource_paths import asset_path
import logging
import sys
import os
from datetime import datetime, timedelta

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from sales.admin_auth import AdminAuthManager
from sales.models import (
    AdminUser,
    Item,
    LOW_STOCK_THRESHOLD,
    PartialPayment,
    PaymentRecord,
    Sale,
    SaleItem,
    ServiceEntry,
)
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count, Q

logger = logging.getLogger(__name__)


class AdminDashboardWindow(QtWidgets.QMainWindow):
    def __init__(self, admin_user=None, autosync=None):
        super().__init__()

        self.admin_user = admin_user
        self.autosync = autosync

        # Store references to updatable widgets
        self.stat_cards = {}
        self.sales_table = None
        self.low_stock_items_container = None
        self.alerts_section = None
        self.stat_card_widgets = {}  # Store stat card value labels for updates

        # Window settings
        self.setWindowTitle(f"Admin Panel - NASS v{settings.NASS_VERSION}")
        self.resize(1000, 700)
        self.center_window()

        # Professional color scheme - minimal and clean
        self.PRIMARY_DARK = "#2c3e50"  # Dark blue-gray
        self.PRIMARY_LIGHT = "#34495e"  # Lighter blue-gray
        self.ACCENT = "#3498db"  # Soft blue for accents
        self.TEXT_LIGHT = "#ecf0f1"  # Off-white text
        self.TEXT_DARK = "#2c3e50"  # Dark text
        self.BORDER_COLOR = "#bdc3c7"  # Light gray border

        # Set window background
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: #f5f6fa;
            }}
        """)

        # Main widget and horizontal layout
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        central_widget.setLayout(main_layout)

        # ========== LEFT PANEL (scrollable menu) ==========
        left_panel = QtWidgets.QWidget()
        left_panel.setFixedWidth(262)
        left_panel.setStyleSheet(f"""
            QWidget {{
                background-color: {self.PRIMARY_DARK};
                border-right: 2px solid {self.BORDER_COLOR};
            }}
        """)

        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_panel.setLayout(left_layout)

        # Scroll area so the whole menu fits even on short/maximized windows.
        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        left_scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {self.PRIMARY_DARK};
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background: {self.PRIMARY_DARK};
            }}
            QScrollBar:vertical {{
                background: {self.PRIMARY_LIGHT};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background: {self.ACCENT};
                border-radius: 5px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)
        left_scroll.viewport().setAutoFillBackground(False)
        left_layout.addWidget(left_scroll)

        left_content = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_content)
        left_layout.setContentsMargins(15, 20, 15, 20)
        left_layout.setSpacing(8)
        left_scroll.setWidget(left_content)

        # Admin Profile Section
        profile_label = QtWidgets.QLabel("ADMIN")
        profile_label.setAlignment(QtCore.Qt.AlignCenter)
        profile_label.setStyleSheet(f"""
            QLabel {{
                color: {self.TEXT_LIGHT};
                font-size: 16px;
                font-weight: bold;
                padding: 10px 0;
                border-bottom: 2px solid {self.ACCENT};
                margin-bottom: 15px;
            }}
        """)
        left_layout.addWidget(profile_label)

        # Admin icon/avatar (simple representation)
        admin_icon = QtWidgets.QLabel()
        admin_icon.setFixedSize(70, 70)
        admin_icon.setStyleSheet(f"""
            QLabel {{
                background-color: {self.ACCENT};
                border-radius: 35px;
                padding: 2px;
            }}
        """)
        admin_icon.setAlignment(QtCore.Qt.AlignCenter)

        # Load logo for avatar
        logo_pixmap = QtGui.QPixmap(asset_path("logo.png"))
        if not logo_pixmap.isNull():
            # Scale logo to fit the circular avatar (66x66 to account for padding)
            scaled_logo = logo_pixmap.scaled(
                QtCore.QSize(66, 66),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            admin_icon.setPixmap(scaled_logo)
        else:
            # Fallback to initial "A" if logo not found
            admin_icon.setText("A")
            admin_icon.setStyleSheet(f"""
                QLabel {{
                    background-color: {self.ACCENT};
                    border-radius: 35px;
                    color: {self.TEXT_LIGHT};
                    font-size: 32px;
                    font-weight: bold;
                }}
            """)

        # Center icon container
        icon_wrapper = QtWidgets.QHBoxLayout()
        icon_wrapper.addStretch()
        icon_wrapper.addWidget(admin_icon)
        icon_wrapper.addStretch()
        icon_wrapper.setSpacing(0)

        left_layout.addLayout(icon_wrapper)

        # Admin name - use actual admin user info if available
        admin_name_text = "Administrator"
        if self.admin_user:
            admin_name_text = self.admin_user.full_name or self.admin_user.username

        admin_name = QtWidgets.QLabel(admin_name_text)
        admin_name.setAlignment(QtCore.Qt.AlignCenter)
        admin_name.setStyleSheet(f"""
            QLabel {{
                color: {self.TEXT_LIGHT};
                font-size: 14px;
                font-weight: bold;
                margin-top: 15px;
                margin-bottom: 5px;
            }}
        """)
        left_layout.addWidget(admin_name)

        # Admin email
        if self.admin_user and self.admin_user.email:
            admin_email = QtWidgets.QLabel(self.admin_user.email)
            admin_email.setAlignment(QtCore.Qt.AlignCenter)
            admin_email.setStyleSheet(f"""
                QLabel {{
                    color: {self.ACCENT};
                    font-size: 10px;
                    font-weight: normal;
                    margin-bottom: 20px;
                }}
            """)
            left_layout.addWidget(admin_email)
        else:
            left_layout.addSpacing(20)

        # ===== NAVIGATION BUTTONS SECTION =====
        # Separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setStyleSheet(
            f"background-color: {self.BORDER_COLOR}; max-height: 1px; margin: 5px 0;"
        )
        left_layout.addWidget(separator)

        # Navigation label
        nav_label = QtWidgets.QLabel("MENU")
        nav_label.setStyleSheet(f"""
            QLabel {{
                color: {self.TEXT_LIGHT};
                font-size: 11px;
                font-weight: bold;
                padding: 8px 0;
                letter-spacing: 0.5px;
            }}
        """)
        left_layout.addWidget(nav_label)

        # Stock Management Button (existing)
        self.stock_btn = self.create_nav_button("📦 Stock Management")
        self.stock_btn.clicked.connect(self.open_stock_window)
        left_layout.addWidget(self.stock_btn)

        # Service Management Button
        self.service_btn = self.create_nav_button("🔧 Service Management")
        self.service_btn.clicked.connect(self.open_service_management)
        left_layout.addWidget(self.service_btn)

        # Expenses Button (separate)
        self.expenses_btn = self.create_nav_button("💰 Expenses")
        self.expenses_btn.clicked.connect(self.open_expenses)
        left_layout.addWidget(self.expenses_btn)

        # Reports Button (existing)
        self.reports_btn = self.create_nav_button("📊 Sales Reports")
        self.reports_btn.clicked.connect(self.open_profit_loss_window)
        left_layout.addWidget(self.reports_btn)

        # Partial Payments History Button
        self.partial_payments_btn = self.create_nav_button("💳 Partial Payments")
        self.partial_payments_btn.clicked.connect(self.open_partial_payments_history)
        left_layout.addWidget(self.partial_payments_btn)

        # Manage Users Button
        self.users_btn = self.create_nav_button("👥 Manage Users")
        self.users_btn.clicked.connect(self.open_user_management)
        left_layout.addWidget(self.users_btn)

        # Sync section
        separator_sync = QtWidgets.QFrame()
        separator_sync.setFrameShape(QtWidgets.QFrame.HLine)
        separator_sync.setStyleSheet(
            f"background-color: {self.BORDER_COLOR}; max-height: 1px; margin: 5px 0;"
        )
        left_layout.addWidget(separator_sync)

        self.sync_indicator = QtWidgets.QLabel("...")
        self.sync_indicator.setAlignment(QtCore.Qt.AlignCenter)
        self.sync_indicator.setStyleSheet(
            f"color: {self.ACCENT}; font-size: 11px; padding: 4px 6px;"
        )
        left_layout.addWidget(self.sync_indicator)

        self.sync_settings_btn = self.create_nav_button("🌐 Sync Settings")
        self.sync_settings_btn.clicked.connect(self.open_sync_settings)
        left_layout.addWidget(self.sync_settings_btn)

        if self.autosync is not None:
            self._syncing = False
            self.autosync.online_changed.connect(self._set_online_indicator)
            self.autosync.syncing_changed.connect(self._set_syncing_indicator)
            self._set_online_indicator(self.autosync.online)

        # Separator for account section
        separator2 = QtWidgets.QFrame()
        separator2.setFrameShape(QtWidgets.QFrame.HLine)
        separator2.setStyleSheet(
            f"background-color: {self.BORDER_COLOR}; max-height: 1px; margin: 5px 0;"
        )
        left_layout.addWidget(separator2)

        # Account Settings label
        account_label = QtWidgets.QLabel("ACCOUNT")
        account_label.setStyleSheet(f"""
            QLabel {{
                color: {self.TEXT_LIGHT};
                font-size: 11px;
                font-weight: bold;
                padding: 8px 0;
                letter-spacing: 0.5px;
            }}
        """)
        left_layout.addWidget(account_label)

        # ===== DUMMY BUTTONS =====
        # Change Password Button
        self.change_password_btn = self.create_nav_button("🔑 Change Password")
        self.change_password_btn.clicked.connect(self.open_change_password_dialog)
        left_layout.addWidget(self.change_password_btn)

        # Personal Info Button
        self.personal_info_btn = self.create_nav_button("👤 Personal Info")
        self.personal_info_btn.clicked.connect(self.open_personal_info_dialog)
        left_layout.addWidget(self.personal_info_btn)

        # About the System Button (dummy)
        self.about_system_btn = self.create_nav_button("ℹ️ About the System")
        self.about_system_btn.clicked.connect(self.show_about_dialog)
        left_layout.addWidget(self.about_system_btn)

        left_layout.addStretch()

        # Logout button at bottom
        self.logout_btn = self.create_nav_button("🚪 Logout", is_logout=True)
        self.logout_btn.clicked.connect(self.close)
        left_layout.addWidget(self.logout_btn)

        # ========== RIGHT CONTENT AREA ==========
        content_area = QtWidgets.QWidget()
        content_area.setStyleSheet("""
            QWidget {
                background-color: #f5f6fa;
            }
        """)

        self.content_layout = QtWidgets.QVBoxLayout()
        self.content_layout.setContentsMargins(30, 30, 30, 30)
        content_area.setLayout(self.content_layout)

        # Welcome header in content area
        welcome_header = QtWidgets.QLabel(
            getattr(settings, "SHOP_NAME", "My Shop")
        )
        welcome_header.setStyleSheet("""
            QLabel {
                color: #2c3e50;
                font-size: 28px;
                font-weight: bold;
                padding-bottom: 20px;
                border-bottom: 2px solid #bdc3c7;
            }
        """)
        self.content_layout.addWidget(welcome_header)

        # Admin info section if user is logged in
        if self.admin_user:
            admin_info_layout = QtWidgets.QHBoxLayout()
            admin_info_layout.setSpacing(20)

            # Welcome message
            welcome_msg = QtWidgets.QLabel(
                f"Welcome , {self.admin_user.full_name or self.admin_user.username}!"
            )
            welcome_msg.setStyleSheet(
                "color: #2c3e50; font-size: 16px; font-weight: bold;"
            )
            admin_info_layout.addWidget(welcome_msg)

            admin_info_layout.addStretch()

            # Last login info
            if self.admin_user.last_login:
                last_login_text = self.format_local_datetime(
                    self.admin_user.last_login, "%Y-%m-%d %H:%M:%S"
                )
                last_login_label = QtWidgets.QLabel(f"Last login: {last_login_text}")
                last_login_label.setStyleSheet("color: #7f8c8d; font-size: 12px;")
                admin_info_layout.addWidget(last_login_label)

            self.content_layout.addLayout(admin_info_layout)
            self.content_layout.addSpacing(20)

        # Stats cards (for visual appeal)
        stats_layout = QtWidgets.QHBoxLayout()
        stats_layout.setSpacing(20)

        # Get real data from database
        total_products = Item.objects.filter(deleted=False).count()
        low_stock_items = Item.objects.filter(
            deleted=False, quantity_in_stock__lt=LOW_STOCK_THRESHOLD
        ).count()

        # Today's sales
        local_now = timezone.localtime()
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        today_sales = (
            Sale.objects.filter(
                deleted=False, date__gte=today_start, date__lt=tomorrow_start
            ).aggregate(total=Sum("total_amount"))["total"]
            or 0
        )
        today_partial_cash = (
            PaymentRecord.objects.filter(
                deleted=False,
                partial_payment__deleted=False,
                date__gte=today_start,
                date__lt=tomorrow_start,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        today_sales += today_partial_cash

        # Today's service income
        today_service_income = (
            ServiceEntry.objects.filter(
                deleted=False, date__gte=today_start, date__lt=tomorrow_start
            ).aggregate(total=Sum("total_amount"))["total"]
            or 0
        )

        # Create stat cards with real data
        self.stat_card_widgets = {}

        total_products_card = self.create_stat_card(
            "Total Products", str(total_products), "#3498db"
        )
        stats_layout.addWidget(total_products_card)
        # Store the value label from the card
        card_labels = total_products_card.findChildren(QtWidgets.QLabel)
        if len(card_labels) > 1:
            self.stat_card_widgets["total_products"] = card_labels[1]

        low_stock_card = self.create_stat_card(
            "Low Stock Items", str(low_stock_items), "#e74c3c"
        )
        stats_layout.addWidget(low_stock_card)
        card_labels = low_stock_card.findChildren(QtWidgets.QLabel)
        if len(card_labels) > 1:
            self.stat_card_widgets["low_stock"] = card_labels[1]

        today_service_card = self.create_stat_card(
            "Today's Service Income", f"MK {today_service_income:,.2f}", "#f39c12"
        )
        stats_layout.addWidget(today_service_card)
        card_labels = today_service_card.findChildren(QtWidgets.QLabel)
        if len(card_labels) > 1:
            self.stat_card_widgets["today_service_income"] = card_labels[1]

        today_sales_card = self.create_stat_card(
            "Today's Sales", f"MK {today_sales:,.2f}", "#27ae60"
        )
        stats_layout.addWidget(today_sales_card)
        card_labels = today_sales_card.findChildren(QtWidgets.QLabel)
        if len(card_labels) > 1:
            self.stat_card_widgets["today_sales"] = card_labels[1]

        self.content_layout.addLayout(stats_layout)

        # Alerts row: Low Stock (left) + Outstanding Payments (right)
        outstanding_pps = [
            pp
            for pp in PartialPayment.objects.filter(deleted=False).order_by(
                "created_at"
            )
            if pp.is_outstanding
        ]
        outstanding_total = sum(pp.balance for pp in outstanding_pps)

        if low_stock_items > 0 or outstanding_pps:
            alerts_row = QtWidgets.QHBoxLayout()
            alerts_row.setSpacing(20)
            self.content_layout.addLayout(alerts_row)

            # ----- Low Stock card -----
            if low_stock_items > 0:
                low_card = QtWidgets.QFrame()
                low_card.setStyleSheet("""
                    QFrame {
                        background-color: white;
                        border-radius: 8px;
                        border: 1px solid #bdc3c7;
                    }
                """)
                low_card.setLayout(QtWidgets.QVBoxLayout())
                low_card.layout().setContentsMargins(15, 12, 15, 12)
                low_card.layout().setSpacing(6)

                low_title = QtWidgets.QLabel("⚠️ Low Stock Alerts")
                low_title.setStyleSheet(
                    "color: #e74c3c; font-size: 15px; font-weight: bold; border: none;"
                )
                low_card.layout().addWidget(low_title)

                low_stock_list = Item.objects.filter(
                    deleted=False, quantity_in_stock__lt=LOW_STOCK_THRESHOLD
                ).order_by("quantity_in_stock")[:5]
                for item in low_stock_list:
                    item_label = item.name
                    if item.size:
                        item_label = f"{item_label} ({item.size})"
                    item_info = QtWidgets.QLabel(
                        f"• {item_label} - "
                        f"{self.format_quantity(item.quantity_in_stock)} unit(s) remaining"
                    )
                    item_info.setStyleSheet(
                        "color: #e67e22; font-size: 12px; border: none;"
                    )
                    low_card.layout().addWidget(item_info)

                view_all_btn = QtWidgets.QPushButton("View All")
                view_all_btn.setMaximumWidth(120)
                view_all_btn.clicked.connect(self.open_all_low_stock_dialog)
                low_card.layout().addWidget(view_all_btn, 0, QtCore.Qt.AlignLeft)
                alerts_row.addWidget(low_card)

            # ----- Outstanding Payments card -----
            if outstanding_pps:
                out_card = QtWidgets.QFrame()
                out_card.setStyleSheet("""
                    QFrame {
                        background-color: white;
                        border-radius: 8px;
                        border: 1px solid #bdc3c7;
                    }
                """)
                out_card.setLayout(QtWidgets.QVBoxLayout())
                out_card.layout().setContentsMargins(15, 12, 15, 12)
                out_card.layout().setSpacing(6)

                out_title = QtWidgets.QLabel("💳 Outstanding Payments")
                out_title.setStyleSheet(
                    "color: #e67e22; font-size: 15px; font-weight: bold; border: none;"
                )
                out_card.layout().addWidget(out_title)

                for pp in outstanding_pps[:5]:
                    who = pp.customer_name or str(pp.item)
                    out_info = QtWidgets.QLabel(
                        f"• {who} - MK {pp.balance:,.2f} "
                        f"({self.format_quantity(pp.quantity)})"
                    )
                    out_info.setStyleSheet(
                        "color: #c0392b; font-size: 12px; border: none;"
                    )
                    out_card.layout().addWidget(out_info)

                view_pps_btn = QtWidgets.QPushButton("View All")
                view_pps_btn.setMaximumWidth(120)
                view_pps_btn.clicked.connect(self.open_partial_payments_history)
                out_card.layout().addWidget(view_pps_btn, 0, QtCore.Qt.AlignLeft)
                alerts_row.addWidget(out_card)

            alerts_row.addStretch()
            self.content_layout.addSpacing(20)

        # Recent Sales Section
        recent_sales_label = QtWidgets.QLabel("📊 Recent Sales")
        recent_sales_label.setStyleSheet("""
            QLabel {
                color: #2c3e50;
                font-size: 16px;
                font-weight: bold;
                margin-top: 20px;
                margin-bottom: 10px;
            }
        """)
        self.content_layout.addWidget(recent_sales_label)

        # Recent sales table
        recent_sales = Sale.objects.filter(deleted=False).order_by("-date")[:5]

        if recent_sales:
            sales_table = QtWidgets.QTableWidget()
            sales_table.setColumnCount(5)
            sales_table.setHorizontalHeaderLabels(
                ["Sale ID", "Date", "Items", "Amount (MK)", "Actions"]
            )
            sales_table.setRowCount(len(recent_sales))
            sales_table.horizontalHeader().setSectionResizeMode(
                QtWidgets.QHeaderView.Stretch
            )
            sales_table.horizontalHeader().setSectionResizeMode(
                4, QtWidgets.QHeaderView.ResizeToContents
            )
            sales_table.setMaximumHeight(200)

            self._populate_sales_table(sales_table, recent_sales)
            self.content_layout.addWidget(sales_table)
            self.sales_table = sales_table  # Store reference for updates
        else:
            no_sales = QtWidgets.QLabel("No sales recorded yet")
            no_sales.setStyleSheet(
                "color: #7f8c8d; font-size: 12px; font-style: italic;"
            )
            self.content_layout.addWidget(no_sales)

        self.content_layout.addStretch()

        # Sales Entry — admin access to the sales window, bottom right
        sales_entry_bar = QtWidgets.QHBoxLayout()
        sales_entry_bar.addStretch()
        sales_entry_btn = QtWidgets.QPushButton("➕ Sales Entry")
        sales_entry_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 20px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2c9b56;
            }
        """)
        sales_entry_btn.clicked.connect(self.open_sales_entry_admin)
        sales_entry_bar.addWidget(sales_entry_btn)
        self.content_layout.addLayout(sales_entry_bar)

        # Add panels to main layout
        main_layout.addWidget(left_panel)
        main_layout.addWidget(content_area)

        # Set up auto-refresh timer (refresh every 30 seconds)
        self.refresh_timer = QtCore.QTimer()
        self.refresh_timer.timeout.connect(self.refresh_dashboard)
        self.refresh_timer.start(30000)  # 30000 milliseconds = 30 seconds

    def create_nav_button(self, text, is_logout=False):
        """Helper method to create consistent navigation buttons"""
        btn = QtWidgets.QPushButton(text)

        if is_logout:
            hover_color = "#c0392b"
            normal_color = "#e74c3c"
        else:
            hover_color = self.PRIMARY_LIGHT
            normal_color = "transparent"

        btn.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 10px 12px;
                border: none;
                border-radius: 4px;
                color: {self.TEXT_LIGHT};
                font-size: 13px;
                font-weight: normal;
                background-color: {normal_color};
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {self.ACCENT};
            }}
        """)
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        return btn

    def create_stat_card(self, title, value, color):
        """Create a statistic card for the dashboard"""
        card = QtWidgets.QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border-radius: 8px;
                border: 1px solid {self.BORDER_COLOR};
            }}
        """)
        card.setFixedHeight(100)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        card.setLayout(layout)

        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet(
            "color: #7f8c8d; font-size: 12px; font-weight: normal; border: none;"
        )

        value_label = QtWidgets.QLabel(value)
        value_label.setStyleSheet(
            f"color: {color}; font-size: 24px; font-weight: bold; border: none;"
        )

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addStretch()

        return card

    def show_dummy_message(self):
        """Show a message for dummy buttons"""
        sender = self.sender()
        button_text = sender.text().split(" ", 1)[-1]  # Remove emoji if present

        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Information)
        msg.setWindowTitle("Feature Coming Soon")
        msg.setText(f"The '{button_text}' feature is under development.")
        msg.setInformativeText(
            "This is a placeholder button for demonstration purposes."
        )
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
        msg.exec_()

    def open_change_password_dialog(self):
        """Open the change password dialog"""
        if not self.admin_user:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Admin user not authenticated. Please login again."
            )
            return

        from front_end.admin_gui.change_password_dialog import ChangePasswordDialog

        dialog = ChangePasswordDialog(self.admin_user, self)
        dialog.exec_()

    def open_personal_info_dialog(self):
        """Open the personal information dialog"""
        if not self.admin_user:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Admin user not authenticated. Please login again."
            )
            return

        # Refresh admin user data from database
        from sales.models import AdminUser

        self.admin_user = AdminUser.objects.get(id=self.admin_user.id)

        from front_end.admin_gui.personal_info_dialog import PersonalInfoDialog

        dialog = PersonalInfoDialog(self.admin_user, self)
        if dialog.exec_():
            # Refresh admin user data after changes
            self.admin_user = AdminUser.objects.get(id=self.admin_user.id)

    def show_about_dialog(self):
        """Show about system information with manual"""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("About NASS")
        dialog.setFixedSize(520, 500)
        dialog.setModal(True)
        dialog.setStyleSheet("QDialog { background-color: #f0f2f5; }")

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 15, 20, 15)

        tabs = QtWidgets.QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #ddd; background: white; }
            QTabBar::tab { padding: 8px 16px; margin-right: 2px; }
            QTabBar::tab:selected { background: #3498db; color: white; }
        """)

        # --- About tab ---
        about_page = QtWidgets.QWidget()
        about_layout = QtWidgets.QVBoxLayout(about_page)
        about_layout.setContentsMargins(20, 20, 20, 20)

        logo = QtWidgets.QLabel("NASS")
        logo.setAlignment(QtCore.Qt.AlignCenter)
        logo.setStyleSheet(
            "font-size: 32px; font-weight: bold; color: #2c3e50; margin-bottom: 5px;"
        )
        about_layout.addWidget(logo)

        subtitle = QtWidgets.QLabel("Nasimango Auto-Stocking System")
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #7f8c8d; margin-bottom: 15px;")
        about_layout.addWidget(subtitle)

        from django.conf import settings

        version = getattr(settings, "NASS_VERSION", "1.0.1")

        info = QtWidgets.QLabel(
            f"<b>Version:</b> {version}<br><br>"
            f"<b>Shop:</b> {getattr(settings, 'SHOP_NAME', 'My Shop')}<br><br>"
            f"<b>Developer:</b> NASS contributors<br><br>"
            f"<b>&copy; 2026</b> All rights reserved."
        )
        info.setWordWrap(True)
        info.setStyleSheet("font-size: 12px; line-height: 1.6; color: #2c3e50;")
        about_layout.addWidget(info)
        about_layout.addStretch()
        tabs.addTab(about_page, "About")

        # --- Manual tab ---
        manual_page = QtWidgets.QWidget()
        manual_layout = QtWidgets.QVBoxLayout(manual_page)
        manual_layout.setContentsMargins(20, 15, 20, 15)

        manual_text = QtWidgets.QTextEdit()
        manual_text.setReadOnly(True)
        manual_text.setStyleSheet(
            "QTextEdit { background: white; border: none; font-size: 12px; color: #2c3e50; }"
        )
        manual_text.setHtml("""
        <h3 style="color:#2c3e50;">Quick Guide</h3>

        <h4 style="color:#3498db;">Getting Started</h4>
        <ol>
            <li>Open the app and log in with your admin account</li>
            <li>Set up your items under <b>Stock Management</b></li>
            <li>Start making sales under <b>Sales Entry</b></li>
        </ol>

        <h4 style="color:#3498db;">Admin Panel</h4>
        <ul>
            <li><b>Stock Management</b> — Add, edit, delete items and categories</li>
            <li><b>Sales Entry</b> — Record sales with item search and quantity</li>
            <li><b>Services</b> — Record service entries and track payments</li>
            <li><b>Expenses</b> — Track daily expenses with dates</li>
            <li><b>Reports</b> — View sales with profit/loss breakdown</li>
            <li><b>Manage Users</b> — Create cashiers, set login requirements</li>
        </ul>

        <h4 style="color:#3498db;">Cashier Accounts</h4>
        <ul>
            <li>Admin creates cashier accounts under <b>Manage Users</b></li>
            <li>By default, cashiers can sell without entering a password</li>
            <li>Admin can enable password login per cashier if needed</li>
            <li>Cashiers cannot access the admin panel</li>
        </ul>

        <h4 style="color:#3498db;">Sync (Online Backup)</h4>
        <ul>
            <li>Go to <b>Sync Settings</b> in the admin panel</li>
            <li>Enter server URL, username, and password to connect</li>
            <li>Data syncs automatically every minute</li>
            <li>To disconnect, click <b>Disconnect</b> in Sync Settings</li>
            <li>To change server, disconnect first then connect to new one</li>
        </ul>

        <h4 style="color:#3498db;">Tips</h4>
        <ul>
            <li>Sales can be back-dated for missed entries</li>
            <li>Partial payments are tracked automatically</li>
            <li>Low stock items appear on the admin dashboard</li>
            <li>All data is stored locally on your computer</li>
        </ul>
        """)
        manual_layout.addWidget(manual_text)
        tabs.addTab(manual_page, "Manual")

        layout.addWidget(tabs)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setFixedHeight(32)
        close_btn.setStyleSheet("""
            QPushButton { background-color: #95a5a6; color: white; padding: 6px 20px; border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #7f8c8d; }
        """)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=QtCore.Qt.AlignRight)

        dialog.exec_()

    def center_window(self):
        """Center the window on the screen"""
        screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    def open_stock_window(self):
        if not hasattr(self, "stock_window") or self.stock_window.isHidden():
            self.stock_window = StockWindow()
            self.stock_window.show()
            self.stock_window.raise_()

    def open_sales_entry_admin(self):
        from front_end.home_gui.sales_window import SalesWindow

        if not hasattr(self, "sales_window") or self.sales_window.isHidden():
            self.sales_window = SalesWindow(autosync=self.autosync)
            self.sales_window.show()
            self.sales_window.raise_()

    def _set_syncing_indicator(self, syncing):
        if syncing:
            self.sync_indicator.setText("⏳ Syncing…")
            self.sync_indicator.setStyleSheet(
                "color: #2980b9; font-size: 11px; padding: 4px 6px; font-weight: bold;"
            )
        elif self.autosync is not None:
            self._set_online_indicator(self.autosync.online)

    def _set_online_indicator(self, online):
        if self.autosync is None or not self.autosync.config.is_configured:
            text, color = "○ Not connected", "#7f8c8d"
        elif online:
            when = self.autosync.config.last_sync_at
            suffix = ""
            if when:
                try:
                    dt = datetime.fromisoformat(when)
                    suffix = " · " + timezone.localtime(dt).strftime("%H:%M")
                except (ValueError, TypeError):
                    pass
            text, color = f"● Sync active{suffix}", "#27ae60"
        elif self.autosync.config.last_sync_at is None:
            text, color = "○ Waiting for first sync", "#7f8c8d"
        else:
            text, color = "○ Sync inactive", "#c0392b"
        self.sync_indicator.setText(text)
        self.sync_indicator.setStyleSheet(
            f"color: {color}; font-size: 11px; padding: 4px 6px; font-weight: bold;"
        )

    def open_sync_settings(self):
        from front_end.sync_gui.sync_settings_dialog import SyncSettingsDialog

        dialog = SyncSettingsDialog(
            self,
            config=self.autosync.config if self.autosync else None,
            admin_user=self.admin_user,
        )
        dialog.exec_()
        if self.autosync is not None:
            self.autosync.reload()
            self.autosync.start()

    def open_profit_loss_window(self):
        if (
            not hasattr(self, "profit_loss_window")
            or self.profit_loss_window.isHidden()
        ):
            self.profit_loss_window = ProfitLossWindow(parent=self)
            self.profit_loss_window.show()
            self.profit_loss_window.raise_()

    def open_partial_payments_history(self):
        if (
            not hasattr(self, "partial_payments_history")
            or self.partial_payments_history.isHidden()
        ):
            from front_end.admin_gui.partial_payments_history_window import (
                PartialPaymentsHistoryWindow,
            )

            self.partial_payments_history = PartialPaymentsHistoryWindow()
            self.partial_payments_history.show()
            self.partial_payments_history.raise_()

    def open_service_management(self):
        from front_end.home_gui.service_management_window import (
            ServiceManagementWindow,
        )

        if not hasattr(self, "service_window") or self.service_window.isHidden():
            self.service_window = ServiceManagementWindow(
                admin_user=self.admin_user, autosync=self.autosync
            )
            self.service_window.show()
            self.service_window.raise_()

    def open_expenses(self):
        from front_end.home_gui.expenses_window import ExpenseWindow

        if not hasattr(self, "expenses_window") or self.expenses_window.isHidden():
            self.expenses_window = ExpenseWindow()
            self.expenses_window.show()
            self.expenses_window.raise_()

    def open_user_management(self):
        from front_end.admin_gui.user_management_window import UserManagementWindow

        dialog = UserManagementWindow(self)
        dialog.exec_()

    def refresh_dashboard(self):
        """Refresh dashboard data from database without restarting window"""
        try:
            # Get fresh data from database
            total_products = Item.objects.filter(deleted=False).count()
            # Must stay identical to the initial render and to the website's
            # admin dashboard. This used to hardcode 5, which silently
            # disagreed with LOW_STOCK_THRESHOLD the moment that changed.
            low_stock_items = Item.objects.filter(
                deleted=False, quantity_in_stock__lt=LOW_STOCK_THRESHOLD
            ).count()

            # Today's sales
            local_now = timezone.localtime()
            today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow_start = today_start + timedelta(days=1)
            today_sales = (
                Sale.objects.filter(
                    deleted=False, date__gte=today_start, date__lt=tomorrow_start
                ).aggregate(total=Sum("total_amount"))["total"]
                or 0
            )
            today_partial_cash = (
                PaymentRecord.objects.filter(
                    deleted=False,
                    partial_payment__deleted=False,
                    date__gte=today_start,
                    date__lt=tomorrow_start,
                ).aggregate(total=Sum("amount"))["total"]
                or 0
            )
            today_sales += today_partial_cash

            # Today's service income
            today_service_income = (
                ServiceEntry.objects.filter(
                    deleted=False, date__gte=today_start, date__lt=tomorrow_start
                ).aggregate(total=Sum("total_amount"))["total"]
                or 0
            )

            # Update stat card values if they exist
            if "total_products" in self.stat_card_widgets:
                self.stat_card_widgets["total_products"].setText(str(total_products))

            if "low_stock" in self.stat_card_widgets:
                self.stat_card_widgets["low_stock"].setText(str(low_stock_items))

            if "today_service_income" in self.stat_card_widgets:
                self.stat_card_widgets["today_service_income"].setText(
                    f"MK {today_service_income:,.2f}"
                )

            if "today_sales" in self.stat_card_widgets:
                self.stat_card_widgets["today_sales"].setText(f"MK {today_sales:,.2f}")

            # Update recent sales table
            if self.sales_table:
                # Clear table
                self.sales_table.setRowCount(0)

                # Get fresh sales data
                recent_sales = Sale.objects.filter(deleted=False).order_by("-date")[:5]

                self.sales_table.setRowCount(len(recent_sales))
                self._populate_sales_table(self.sales_table, recent_sales)
        except Exception:
            logger.exception("Dashboard refresh failed")

    def get_sale_items_text(self, sale):
        sale_items = sale.items.select_related("item").all()
        names = []
        for si in sale_items:
            if not si.item:
                names.append("(unknown)")
                continue
            label = si.item.name
            if si.item.size:
                label = f"{label} ({si.item.size})"
            names.append(label)
        return ", ".join(names) if names else "(no items)"

    def _populate_sales_table(self, sales_table, recent_sales):
        """Fill the Recent Sales table, including a Delete button on every row.

        Both the first render and refresh_dashboard() go through here. Keeping
        one copy is what stops the button from silently vanishing on refresh.
        """
        for row, sale in enumerate(recent_sales):
            sales_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(sale.id)))
            sales_table.setItem(
                row,
                1,
                QtWidgets.QTableWidgetItem(
                    self.format_local_datetime(sale.date, "%Y-%m-%d %H:%M")
                ),
            )
            sales_table.setItem(
                row, 2, QtWidgets.QTableWidgetItem(self.get_sale_items_text(sale))
            )
            sales_table.setItem(
                row, 3, QtWidgets.QTableWidgetItem(f"MK {sale.total_amount:,.2f}")
            )
            # Plain button, matching the Service Management records table.
            delete_btn = QtWidgets.QPushButton("Delete")
            delete_btn.setFixedHeight(24)
            delete_btn.clicked.connect(
                lambda checked=False, s=sale, t=sales_table, r=row: self._delete_sale(
                    s, t, r
                )
            )
            sales_table.setCellWidget(row, 4, delete_btn)

    def _trigger_sync(self):
        """Nudge the autosync engine after a local change."""
        if getattr(self, "autosync", None) is not None:
            self.autosync.start_sync()

    def _delete_sale(self, sale, table_widget, row):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete sale #{sale.id} (MK {sale.total_amount:,.2f})?\n\n"
            "Stock for each item will be restored.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            with transaction.atomic():
                from sales.models import record_sale_restore

                # Deterministic restore deltas (same adjustment ids on every
                # device), so synced sale-deletes restore stock exactly once.
                record_sale_restore(sale)
                for si in sale.items.all():
                    si.deleted = True
                    si.save()
                sale.deleted = True
                sale.save()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not delete sale: {exc}"
            )
            return

        # Re-render from the database instead of guessing the new row order,
        # so the remaining rows keep their correct Delete buttons.
        if table_widget is getattr(self, "sales_table", None):
            self.refresh_dashboard()
        else:
            table_widget.removeRow(row)
        self._trigger_sync()
        QtWidgets.QMessageBox.information(
            self, "Deleted", f"Sale #{sale.id} deleted. Stock restored."
        )

    def open_all_low_stock_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowFlags(
            dialog.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
        dialog.setWindowTitle("All Low Stock Items")
        dialog.resize(520, 420)

        layout = QtWidgets.QVBoxLayout(dialog)
        table = QtWidgets.QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Item", "Size", "Quantity"])
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        low_stock_items = Item.objects.filter(
                deleted=False, quantity_in_stock__lt=LOW_STOCK_THRESHOLD
            ).order_by("quantity_in_stock", "name")
        table.setRowCount(low_stock_items.count())

        for row, item in enumerate(low_stock_items):
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(item.name))
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(item.size or ""))
            table.setItem(
                row,
                2,
                QtWidgets.QTableWidgetItem(
                    self.format_quantity(item.quantity_in_stock)
                ),
            )

        layout.addWidget(table)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec_()

    def format_local_datetime(self, dt, fmt="%Y-%m-%d %H:%M:%S"):
        if not dt:
            return ""
        try:
            return timezone.localtime(dt).strftime(fmt)
        except Exception:
            return dt.strftime(fmt)

    def format_quantity(self, qty):
        text = format(qty, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    def closeEvent(self, event):
        """Stop the refresh timer when window is closed"""
        if hasattr(self, "refresh_timer"):
            self.refresh_timer.stop()
        event.accept()
