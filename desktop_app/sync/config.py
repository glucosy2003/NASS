"""Persistent per-device sync configuration.

Stored as JSON in %LOCALAPPDATA%\\NASS\\sync_config.json (same directory the
frozen app uses for its SQLite database). Only the API token is encrypted
(Windows DPAPI); everything else is non-secret metadata.
"""

import json
import os
import uuid
from pathlib import Path

from sync import profile
from sync.crypto import decode, encode

CONFIG_VERSION = 1


def config_dir():
    # NOTE: the folder name is profile-specific. The frozen (production) app
    # and the dev app must never read each other's server URL, API token or
    # sync cursors -- see sync/profile.py for what that used to cause.
    folder = profile.config_dir_name()
    app_data = os.getenv("LOCALAPPDATA")
    if app_data:
        directory = Path(app_data) / folder
    else:
        directory = Path.home() / f".{folder.lower()}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_path():
    return config_dir() / "sync_config.json"


def new_device_id():
    return str(uuid.uuid4())


class SyncConfig:
    def __init__(self):
        self.server_url = ""
        self.username = ""
        self.device_id = new_device_id()
        self.token = ""
        self.last_pull = None
        self.last_push = None
        self.initial_pull_done = False
        self.last_sync_status = ""
        self.last_sync_at = None
        self.last_sync_connected = False
        self.pending_full_push = False
        self.auto_sync_minutes = 1

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    @classmethod
    def load(cls):
        cfg = cls()
        path = config_path()
        if not path.exists():
            return cfg
        try:
            raw = json.loads(path.read_text("utf-8"))
        except (ValueError, OSError):
            return cfg
        if raw.get("config_version", 0) != CONFIG_VERSION:
            return cfg
        cfg.server_url = raw.get("server_url", "")
        cfg.username = raw.get("username", "")
        cfg.device_id = raw.get("device_id") or cfg.device_id
        cfg.token = raw.get("token", "")
        cfg.last_pull = raw.get("last_pull")
        cfg.last_push = raw.get("last_push")
        cfg.initial_pull_done = bool(raw.get("initial_pull_done", False))
        cfg.last_sync_status = raw.get("last_sync_status", "")
        cfg.last_sync_at = raw.get("last_sync_at")
        cfg.last_sync_connected = bool(raw.get("last_sync_connected", False))
        # Existing installs predate this flag; give them one full push so any
        # data stranded by the old push-cursor bug is eventually healed.
        cfg.pending_full_push = bool(raw.get("pending_full_push", True))
        cfg.auto_sync_minutes = int(raw.get("auto_sync_minutes", 1))
        return cfg

    def save(self):
        data = {
            "config_version": CONFIG_VERSION,
            "server_url": self.server_url,
            "username": self.username,
            "device_id": self.device_id,
            "token": self.token,
            "last_pull": self.last_pull,
            "last_push": self.last_push,
            "initial_pull_done": self.initial_pull_done,
            "last_sync_status": self.last_sync_status,
            "last_sync_at": self.last_sync_at,
            "last_sync_connected": self.last_sync_connected,
            "pending_full_push": self.pending_full_push,
            "auto_sync_minutes": self.auto_sync_minutes,
        }
        try:
            path = config_path()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), "utf-8")
            os.replace(tmp, path)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # token helpers
    # ------------------------------------------------------------------
    @property
    def token_plaintext(self):
        if not self.token:
            return ""
        try:
            return decode(self.token)
        except Exception:  # noqa: BLE001
            return ""

    def set_token(self, plaintext):
        self.token = encode(plaintext or "")

    @property
    def is_configured(self):
        return bool(self.server_url) and bool(self.token_plaintext)

    def clear_token(self):
        self.token = ""