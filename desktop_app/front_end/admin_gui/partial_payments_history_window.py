from PyQt5 import QtCore, QtWidgets
from sales.models import PartialPayment


class PartialPaymentsHistoryWindow(QtWidgets.QMainWindow):
    """Admin-only history report of all partial payments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Partial Payments History - NASS")
        self.resize(1000, 760)
        self.center_window()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout()
        central.setLayout(layout)

        title = QtWidgets.QLabel("Partial Payments History")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #2c3e50; margin-bottom: 8px;"
        )
        layout.addWidget(title)

        self.table_headers = [
            "Date",
            "Customer",
            "Item",
            "Qty",
            "Total (MK)",
            "Paid (MK)",
            "Balance (MK)",
            "Collected",
            "Status",
            "Phone",
        ]

        outstanding_label = QtWidgets.QLabel("Outstanding Balances")
        outstanding_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #c0392b; margin-top: 6px;"
        )
        layout.addWidget(outstanding_label)
        self.outstanding_table = self._create_table()
        layout.addWidget(self.outstanding_table)

        settled_label = QtWidgets.QLabel("Settled Payments")
        settled_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #27ae60; margin-top: 10px;"
        )
        layout.addWidget(settled_label)
        self.settled_table = self._create_table()
        layout.addWidget(self.settled_table)

        bottom = QtWidgets.QHBoxLayout()
        layout.addLayout(bottom)
        summary = QtWidgets.QLabel()
        summary.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        bottom.addWidget(summary)

        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_data)
        bottom.addWidget(refresh_btn)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)

        self.summary_label = summary
        self.load_data()

    def center_window(self):
        screen_geometry = QtWidgets.QApplication.primaryScreen().geometry()
        geometry = self.frameGeometry()
        geometry.moveCenter(screen_geometry.center())
        self.move(geometry.topLeft())

    def load_data(self):
        rows = list(
            PartialPayment.objects.filter(deleted=False).order_by("-created_at")
        )
        outstanding = [pp for pp in rows if pp.is_outstanding]
        settled = [pp for pp in rows if not pp.is_outstanding]
        outstanding_total = sum(pp.balance for pp in outstanding)

        self._populate_table(self.outstanding_table, outstanding)
        self._populate_table(self.settled_table, settled)

        self.summary_label.setText(
            f"{len(outstanding)} outstanding · MK {outstanding_total:,.2f} owed "
            f"· {len(settled)} settled"
        )

    def _create_table(self):
        table = QtWidgets.QTableWidget()
        table.setColumnCount(len(self.table_headers))
        table.setHorizontalHeaderLabels(self.table_headers)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setMinimumHeight(150)
        return table

    def _populate_table(self, table, rows):
        table.setRowCount(len(rows))
        for row, pp in enumerate(rows):
            values = [
                pp.created_at.strftime("%Y-%m-%d %H:%M"),
                pp.customer_name or "-",
                str(pp.item),
                self.fmt_qty(pp.quantity),
                f"MK {pp.total_amount:,.2f}",
                f"MK {pp.paid:,.2f}",
                f"MK {pp.balance:,.2f}",
                "Yes" if pp.collected else "No",
                pp.status,
                pp.phone or "-",
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QtWidgets.QTableWidgetItem(value))

    @staticmethod
    def fmt_qty(qty):
        text = format(qty, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
