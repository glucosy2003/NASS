import sys
import os

# -----------------------------
# 1. Configure Django FIRST
# -----------------------------

if getattr(sys, "frozen", False):
    runtime_roots = [
        getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)),
        os.path.dirname(sys.executable),
    ]
else:
    runtime_roots = [os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))]

for root in runtime_roots:
    if os.path.isdir(root) and root not in sys.path:
        sys.path.insert(0, root)

for root in runtime_roots:
    backend_path = os.path.join(root, "backend")
    if os.path.isdir(backend_path) and backend_path not in sys.path:
        sys.path.insert(0, backend_path)
        break

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nass_backend.settings")

import django
django.setup()

# ----------------------------------------------------------------------
# 1b. Keep the local SQLite schema up to date with the models.
#
#     `migrate` is idempotent, so old installs upgrade cleanly instead of
#     crashing on new fields. Before any pending migration runs, the database
#     is snapshotted to %LOCALAPPDATA%\NASS\backups\ and the snapshot is
#     verified. If the migration fails the GUI is NOT started: opening a
#     window on a half-migrated shop database is far worse than a clear
#     error and an obvious rollback file.
# ----------------------------------------------------------------------
from startup_db import DatabaseSafetyError, prepare_database


def _fatal(message):
    """Show an error the user can actually see.

    The app is built with console=False, so print() goes nowhere. Use a
    native Win32 message box, which works before PyQt is imported.
    """
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # 0x10 = MB_ICONERROR
            0,
            message,
            "NASS - database update problem",
            0x10,
        )
    except Exception:  # noqa: BLE001
        print(message)


try:
    prepare_database()
except DatabaseSafetyError as exc:
    _fatal(str(exc))
    sys.exit(1)

# -----------------------------
# 2. Now import PyQt & GUI
# -----------------------------

from PyQt5 import QtWidgets, QtGui
from resource_paths import asset_path
from front_end.home_gui.dashboard_window import DashboardWindow


def _run_stock_repair():
    """--rebuild-stock: reconcile the local stock ledger to the shop's real
    quantities and force a full push so the server ends up with the same data.

    Uses the same native message box as _fatal() (the app is console=False).
    """
    from sales.stock_repair import record_openings, recompute_cache
    from sync.config import SyncConfig

    try:
        opened = record_openings()
        recalc = recompute_cache()
        config = SyncConfig.load()
        config.pending_full_push = True
        config.save()
        message = (
            "NASS stock repair complete.\n\n"
            f"Items checked:            {opened['items']}\n"
            f"Opening balances added:   {opened['opening_created']}\n"
            f"Opening balances fixed:   {opened['opening_updated']}\n"
            f"Quantities recomputed:    {recalc['recomputed']}\n\n"
            "The desktop's stock is now the source of truth. Before syncing "
            "this PC, run on the PythonAnywhere server:\n\n"
            "    python manage.py rebuild_stock --reset\n\n"
            "then sync from this desktop so the full ledger is pushed once."
        )
        flags = 0x40  # MB_ICONINFORMATION
    except Exception as exc:  # noqa: BLE001
        message = f"NASS stock repair FAILED.\n\n{exc}"
        flags = 0x10  # MB_ICONERROR
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "NASS - Stock repair", flags)
    except Exception:  # noqa: BLE001
        print(message)


def main():
    if "--rebuild-stock" in sys.argv:
        _run_stock_repair()
        return

    app = QtWidgets.QApplication(sys.argv)

    # Set application icon (shown in title bar, taskbar, and Alt-Tab)
    icon_path = asset_path("logo.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QtGui.QIcon(icon_path))

    window = DashboardWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
