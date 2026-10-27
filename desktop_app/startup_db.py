"""Startup database safety for the desktop app.

Updating NASS means running new Django migrations against the shop's live
SQLite database in ``%LOCALAPPDATA%\\NASS\\nass.sqlite3``. The installer only
replaces program files, so this is the single point where an update can
destroy a shop's data.

Everything here is built around that risk:

* snapshots are taken with SQLite's **online backup API**, because a plain
  file copy of a live database can capture a half-written page;
* a snapshot is taken **only when a migration is actually pending**, so the
  last known-good backup is never overwritten by a routine launch;
* the snapshot is **verified** (``PRAGMA integrity_check``) before the real
  database is touched;
* if a migration fails, the app **refuses to start** rather than opening a
  window on a half-migrated database, and the rollback path is shown.

Snapshots live in ``%LOCALAPPDATA%\\NASS\\backups\\`` and the most recent
``KEEP_BACKUPS`` are retained. The legacy ``nass.sqlite3.bak`` next to the
database is refreshed too, so older runbooks keep working.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

BACKUP_DIRNAME = "backups"
BACKUP_PREFIX = "nass-"
BACKUP_SUFFIX = ".sqlite3"
KEEP_BACKUPS = 5


class DatabaseSafetyError(RuntimeError):
    """The database cannot be prepared safely, so the app must not start."""


def _stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def backup_dir(db_path):
    return Path(db_path).parent / BACKUP_DIRNAME


def list_backups(db_path):
    directory = backup_dir(db_path)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"), reverse=True)


def prune_backups(db_path, keep=KEEP_BACKUPS):
    """Keep the newest ``keep`` snapshots; delete the rest."""
    removed = []
    for old in list_backups(db_path)[keep:]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            pass
    return removed


def database_exists(name):
    """True when there is a database worth protecting.

    ``file:`` URIs and ``:memory:`` have no separate file on disk, so a plain
    ``os.path.exists`` would wrongly treat them as a fresh install.
    """
    text = str(name)
    if text == ":memory:" or text.startswith("file:"):
        return True
    return os.path.exists(text)


def create_backup(db_path, keep=KEEP_BACKUPS):
    """Take a consistent, verified snapshot. Returns the backup path.

    Raises :class:`DatabaseSafetyError` if a usable snapshot cannot be made;
    the caller must then refuse to migrate.
    """
    directory = backup_dir(db_path)
    directory.mkdir(parents=True, exist_ok=True)

    dest = directory / f"{BACKUP_PREFIX}{_stamp()}{BACKUP_SUFFIX}"
    suffix = 1
    while dest.exists():
        dest = directory / f"{BACKUP_PREFIX}{_stamp()}-{suffix}{BACKUP_SUFFIX}"
        suffix += 1

    source = target = None
    try:
        source = sqlite3.connect(db_path, timeout=30)
        target = sqlite3.connect(dest)
        # Online backup: writes a transactionally consistent copy even if the
        # database is being written to concurrently.
        source.backup(target)
        status = target.execute("PRAGMA integrity_check").fetchone()[0]
        if status != "ok":
            raise DatabaseSafetyError(
                f"Refusing to migrate: the backup failed its integrity check ({status})."
            )
    except DatabaseSafetyError:
        _discard(dest)
        raise
    except Exception as exc:  # noqa: BLE001
        _discard(dest)
        raise DatabaseSafetyError(f"Could not create a database backup: {exc}") from exc
    finally:
        for conn in (target, source):
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    # Legacy single-file backup, so any older restore instructions still work.
    try:
        import shutil

        shutil.copy2(dest, f"{db_path}.bak")
    except OSError:
        pass

    prune_backups(db_path, keep=keep)
    return dest


def _discard(path):
    """Remove a partial/invalid backup so it can never be restored by mistake."""
    try:
        Path(path).unlink()
    except OSError:
        pass


def has_pending_migrations():
    """True when the schema is behind the bundled migrations."""
    try:
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connections["default"])
        targets = executor.loader.graph.leaf_nodes()
        return bool(executor.migration_plan(targets))
    except Exception:
        # If we cannot tell, assume work is pending so a backup gets taken.
        return True


def prepare_database(interactive=False):
    """Snapshot if needed, then migrate.

    Returns the backup path when one was taken, or ``None`` when the schema
    was already current. Raises :class:`DatabaseSafetyError` on any failure,
    in which case the caller must not start the GUI.
    """
    from django.conf import settings
    from django.core.management import call_command

    db_path = str(settings.DATABASES["default"]["NAME"])
    if not database_exists(db_path):
        # Fresh install: it was just seeded, nothing to protect.
        call_command("migrate", interactive=interactive, verbosity=0)
        return None

    if not has_pending_migrations():
        return None

    try:
        backup = create_backup(db_path)
    except DatabaseSafetyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DatabaseSafetyError(
            f"Could not create a database backup, so the update was stopped.\n\n"
            f"Reason: {exc}"
        ) from exc

    try:
        call_command("migrate", interactive=interactive, verbosity=0)
    except Exception as exc:  # noqa: BLE001
        raise DatabaseSafetyError(
            "The database update failed, so NASS has not been started.\n\n"
            f"Reason: {exc}\n\n"
            f"Your data is safe in this backup:\n{backup}\n\n"
            f"To roll back, close NASS and copy that file over:\n"
            f"{db_path}"
        ) from exc

    return backup