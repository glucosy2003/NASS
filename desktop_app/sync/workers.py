"""Background workers that run sync passes off the GUI thread."""

from PyQt5 import QtCore

from sync.manager import SyncManager


class SyncThread(QtCore.QThread):
    """Runs one sync pass in a worker thread. `mode` is 'sync' or 'initial'."""

    finished_sync = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, config, mode="sync", parent=None):
        super().__init__(parent)
        self.config = config
        self.mode = mode

    def run(self):
        try:
            manager = SyncManager(self.config)
            if self.mode == "initial":
                result = manager.initial_pull()
            else:
                result = manager.run()
            self.finished_sync.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))