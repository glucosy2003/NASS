from PyQt5 import QtWidgets, QtCore
from sales.models import Sale, SaleItem, record_sale_restore
from decimal import Decimal
from datetime import datetime
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone


class ProfitLossWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__()
        self.dashboard = parent

        self.setWindowTitle("Profit / Loss Summary - NASS")
        self.resize(900, 600)
        self.center_window()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout()
        central.setLayout(layout)

        # Title
        title = QtWidgets.QLabel("Profit / Loss Summary")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 22px; font-weight: bold; margin: 10px; color: green;"
        )
        layout.addWidget(title)

        # Filter layout
        filter_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(filter_layout)

        filter_layout.addWidget(QtWidgets.QLabel("From:"))
        self.from_date = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.from_date.setCalendarPopup(True)
        filter_layout.addWidget(self.from_date)

        filter_layout.addWidget(QtWidgets.QLabel("To:"))
        self.to_date = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.to_date.setCalendarPopup(True)
        filter_layout.addWidget(self.to_date)

        filter_btn = QtWidgets.QPushButton("Filter")
        filter_btn.clicked.connect(self.load_sales)
        filter_layout.addWidget(filter_btn)

        # Delete period button
        delete_btn = QtWidgets.QPushButton("Delete Period")
        delete_btn.setToolTip(
            "Delete all sales (and related sale items) in the selected date range"
        )
        delete_btn.clicked.connect(self.delete_period_data)
        filter_layout.addWidget(delete_btn)

        # Export button
        export_btn = QtWidgets.QPushButton("Export Report")
        export_btn.setToolTip("Export sales report to spreadsheet")
        export_btn.clicked.connect(self.open_export_window)
        filter_layout.addWidget(export_btn)

        # Table for sales summary
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            [
                "Sale ID",
                "Date",
                "Item",
                "Size",
                "Quantity",
                "Unit Price (MK)",
                "Item Total (MK)",
                "Profit (MK)",
                "Loss (MK)",
                "Delete",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch
        )
        self.table.verticalHeader().setDefaultSectionSize(40)
        layout.addWidget(self.table)

        # Total summary
        self.total_summary_label = QtWidgets.QLabel(
            "Total Items Sold: 0 | Total Amount: MK 0.00 | Total Profit: MK 0.00 | Total Loss: MK 0.00"
        )
        self.total_summary_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; margin-top: 10px; background-color: #E8F5E9; color: #008000; padding: 10px; border-radius: 5px;"
        )
        layout.addWidget(self.total_summary_label)

        self.load_sales()

    def center_window(self):
        """Center the window on the screen"""
        screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    def load_sales(self):
        """Load sales from DB filtered by date (timezone-aware)"""
        from_dt = timezone.make_aware(
            datetime.combine(self.from_date.date().toPyDate(), datetime.min.time())
        )
        to_dt = timezone.make_aware(
            datetime.combine(self.to_date.date().toPyDate(), datetime.max.time())
        )

        # Try to detect the correct reverse accessor dynamically
        # Common default: 'saleitem_set', or custom related_name
        reverse_accessor = None
        if hasattr(Sale, "saleitem_set"):
            reverse_accessor = "saleitem_set"
        else:
            # fallback: take the first ForeignKey from SaleItem pointing to Sale
            for f in SaleItem._meta.fields:
                if f.get_internal_type() == "ForeignKey" and f.related_model == Sale:
                    reverse_accessor = f.related_query_name()
                    break
            if not reverse_accessor:
                reverse_accessor = "saleitem_set"  # final fallback

        saleitems_prefetch = Prefetch(
            reverse_accessor,
            queryset=SaleItem.objects.select_related("item"),
            to_attr="prefetched_saleitems",
        )

        sales = (
            Sale.objects.filter(deleted=False, date__range=(from_dt, to_dt))
            .prefetch_related(saleitems_prefetch)
            .order_by("-date")
        )

        self.table.setRowCount(0)
        total_amount = Decimal(0)
        total_profit = Decimal(0)
        total_loss = Decimal(0)
        total_items_sold = Decimal(0)

        for sale in sales:
            sale_items = getattr(sale, "prefetched_saleitems", None)
            if sale_items is None:
                sale_items = list(
                    SaleItem.objects.filter(sale=sale).select_related("item")
                )

            sale_start_row = self.table.rowCount()
            for si in sale_items:
                row = self.table.rowCount()
                self.table.insertRow(row)

                item_obj = getattr(si, "item", None)
                item_name = (
                    getattr(item_obj, "name", None)
                    or getattr(item_obj, "title", None)
                    or str(item_obj)
                    if item_obj is not None
                    else str(getattr(si, "item_id", "(unknown)"))
                )
                item_size = (
                    getattr(item_obj, "size", "") if item_obj is not None else ""
                )

                qty = si.quantity or Decimal(0)
                unit_price = si.selling_price or Decimal(0)
                item_total = unit_price * qty
                profit = si.profit or Decimal(0)
                profit_value = profit if profit >= 0 else Decimal(0)
                loss_value = (-profit) if profit < 0 else Decimal(0)

                self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(sale.id)))
                self.table.setItem(
                    row,
                    1,
                    QtWidgets.QTableWidgetItem(
                        timezone.localtime(sale.date).strftime("%Y-%m-%d %H:%M")
                    ),
                )
                self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(item_name)))
                self.table.setItem(
                    row, 3, QtWidgets.QTableWidgetItem(str(item_size or ""))
                )
                self.table.setItem(
                    row, 4, QtWidgets.QTableWidgetItem(self.format_quantity(qty))
                )
                self.table.setItem(
                    row, 5, QtWidgets.QTableWidgetItem(f"MK {unit_price:,.2f}")
                )
                self.table.setItem(
                    row, 6, QtWidgets.QTableWidgetItem(f"MK {item_total:,.2f}")
                )
                self.table.setItem(
                    row, 7, QtWidgets.QTableWidgetItem(f"MK {profit_value:,.2f}")
                )
                self.table.setItem(
                    row, 8, QtWidgets.QTableWidgetItem(f"MK {loss_value:,.2f}")
                )

                total_amount += item_total
                total_profit += profit_value
                total_loss += loss_value
                total_items_sold += qty

            if sale_items:
                delete_btn = QtWidgets.QPushButton("Delete")
                delete_btn.setFixedSize(62, 26)
                delete_btn.setToolTip(f"Delete sale #{sale.id} and restore stock")
                delete_btn.setStyleSheet(
                    "QPushButton { background-color: #e74c3c; color: white; "
                    "border: none; border-radius: 3px; font-size: 11px; }"
                    "QPushButton:hover { background-color: #c0392b; }"
                )
                delete_btn.clicked.connect(lambda _, s=sale: self.delete_sale(s))
                self.table.setCellWidget(sale_start_row, 9, delete_btn)
                if len(sale_items) > 1:
                    self.table.setSpan(sale_start_row, 9, len(sale_items), 1)

        self.total_summary_label.setText(
            f"Total Items Sold: {self.format_quantity(total_items_sold)} | Total Amount: MK {total_amount:,.2f} | Total Profit: MK {total_profit:,.2f} | Total Loss: MK {total_loss:,.2f}"
        )

    def delete_sale(self, sale):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Delete sale #{sale.id} (MK {sale.total_amount:,.2f})?\n\n"
            "Stock for each item will be restored.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        try:
            with transaction.atomic():
                sale = Sale.objects.select_for_update().get(pk=sale.pk)
                if sale.deleted:
                    return
                # Deterministic restore deltas (same ids on every device) so a
                # synced delete restores stock exactly once.
                record_sale_restore(sale)
                for sale_item in sale.items.select_related("item").filter(
                    deleted=False
                ):
                    sale_item.deleted = True
                    sale_item.save(update_fields=["deleted", "updated_at"])
                sale.deleted = True
                sale.save(update_fields=["deleted", "updated_at"])
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Deletion Failed", f"Could not delete sale: {exc}"
            )
            return

        self.load_sales()
        if self.dashboard is not None:
            self.dashboard.refresh_dashboard()
        QtWidgets.QMessageBox.information(
            self, "Deleted", f"Sale #{sale.id} deleted. Stock restored."
        )

    def delete_period_data(self):
        """Delete all Sale and related SaleItem data in the selected date range, with confirmation."""
        from_dt = timezone.make_aware(
            datetime.combine(self.from_date.date().toPyDate(), datetime.min.time())
        )
        to_dt = timezone.make_aware(
            datetime.combine(self.to_date.date().toPyDate(), datetime.max.time())
        )

        sales_qs = Sale.objects.filter(deleted=False, date__range=(from_dt, to_dt))
        sale_count = sales_qs.count()
        if sale_count == 0:
            QtWidgets.QMessageBox.information(
                self, "Nothing to delete", "No sales found in the selected date range."
            )
            return

        saleitems_count = SaleItem.objects.filter(sale__in=sales_qs).count()

        msg = (
            f"You're about to delete {sale_count} sale(s) and {saleitems_count} sale item(s)\n"
            f"from {timezone.localtime(from_dt).strftime('%Y-%m-%d %H:%M')} "
            f"to {timezone.localtime(to_dt).strftime('%Y-%m-%d %H:%M')}.\n\n"
            "This action cannot be undone. Are you sure?"
        )

        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Deletion",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )

        if reply != QtWidgets.QMessageBox.Yes:
            return

        try:
            with transaction.atomic():
                for sale in sales_qs.select_for_update():
                    record_sale_restore(sale)
                    for sale_item in sale.items.filter(deleted=False):
                        sale_item.deleted = True
                        sale_item.save(update_fields=["deleted", "updated_at"])
                    sale.deleted = True
                    sale.save(update_fields=["deleted", "updated_at"])
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Deletion Failed", f"An error occurred while deleting: {e}"
            )
            return

        QtWidgets.QMessageBox.information(
            self,
            "Deleted",
            f"Deleted {sale_count} sale(s) and {saleitems_count} sale item(s).",
        )
        self.load_sales()

    def open_export_window(self):
        """Open the export window for spreadsheet export"""
        from .export_window import ExportWindow

        self.export_window = ExportWindow()
        self.export_window.show()

    def format_quantity(self, qty):
        text = format(qty, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
