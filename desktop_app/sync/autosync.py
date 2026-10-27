"""Auto-sync controller: periodic background sync + status signal.

Instantiated once per app run and wired to the main dashboard so both admins
and cashiers stay in sync whether or not they open any particular window.
"""

from datetime import datetime

from PyQt5 import QtCore

from sync.config import SyncConfig
from sync.workers import SyncThread


class AutoSync(QtCore.QObject):
    state_changed = QtCore.pyqtSignal(str)
    synced = QtCore.pyqtSignal(object)
    online_changed = QtCore.pyqtSignal(bool)
    syncing_changed = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = SyncConfig.load()
        self._thread = None
        self._last_result = None
        self._online = self.config.is_configured and self.config.last_sync_connected

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.start_sync)
        self._apply_interval()

    @property
    def online(self):
        return self._online

    def _set_online(self, value):
        if value != self._online:
            self._online = value
            self.online_changed.emit(value)

    def reload(self):
        self.config = SyncConfig.load()
        self._apply_interval()
        self._set_online(self.config.is_configured and self.config.last_sync_connected)
        self.state_changed.emit(self.status_text())

    def _apply_interval(self):
        minutes = max(1, self.config.auto_sync_minutes)
        self.timer.setInterval(minutes * 60 * 1000)

    # ------------------------------------------------------------------
    def start(self):
        if self.config.is_configured:
            self.timer.start()
        self.state_changed.emit(self.status_text())
        # Plug-and-play: finish the first full pull if a login exists but the
        # initial download hasn't happened yet (e.g. app closed mid-first-sync).
        if self.config.is_configured and not self.config.initial_pull_done:
            self.start_sync(mode="initial")

    def stop(self):
        self.timer.stop()

    def disconnect(self):
        self.timer.stop()
        self.config.clear_token()
        self.config.server_url = ""
        self.config.username = ""
        self.config.initial_pull_done = False
        self.config.last_sync_status = ""
        self.config.last_sync_at = None
        self.config.last_sync_connected = False
        self.config.save()
        self._set_online(False)
        self.state_changed.emit("Not connected to server")

    def start_sync(self, mode="sync"):
        if self._thread is not None and self._thread.isRunning():
            return
        if not self.config.is_configured:
            self._set_online(False)
            self.syncing_changed.emit(False)
            self.state_changed.emit("Not connected to server")
            return
        self.state_changed.emit("Syncing...")
        self.syncing_changed.emit(True)
        self._thread = SyncThread(self.config, mode=mode, parent=self)
        self._thread.finished_sync.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_done(self, result):
        self._last_result = result
        self.syncing_changed.emit(False)
        self._set_online(result.connected)
        self.reload()
        self.synced.emit(result)

    def _on_failed(self, message):
        self.syncing_changed.emit(False)
        self._set_online(False)
        self.state_changed.emit(f"Sync error: {message}")

    # ------------------------------------------------------------------
    def status_text(self):
        cfg = self.config
        if not cfg.is_configured:
            return "Not connected to server"
        status = cfg.last_sync_status or "Never synced"
        when = cfg.last_sync_at
        if when:
            try:
                dt = datetime.fromisoformat(when)
                when = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass
            return f"{status} · {when}"
        return status