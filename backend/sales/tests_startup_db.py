"""Tests for the startup database safety net used by the desktop app.

An update runs migrations against the shop's live database, so these tests
pin the guarantees that make that recoverable: a verified snapshot, no
snapshot churn when there is nothing to migrate, and a hard stop (no GUI)
when the migration fails.
"""

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DESKTOP_APP = _REPO_ROOT / "desktop_app"
if str(_DESKTOP_APP) not in sys.path:
    sys.path.insert(0, str(_DESKTOP_APP))

from django.test import TestCase  # noqa: E402

import startup_db  # noqa: E402
from startup_db import DatabaseSafetyError, prepare_database  # noqa: E402


def logical_fingerprint(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = sorted(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        rows = []
        for table in tables:
            rows.append((table, conn.execute(f'SELECT * FROM "{table}"').fetchall()))
        return rows
    finally:
        conn.close()


class CreateBackupTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "nass.sqlite3"

        source = sqlite3.connect(self.db_path)
        source.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT)")
        source.executemany(
            "INSERT INTO widget (name) VALUES (?)", [(f"w{i}",) for i in range(50)]
        )
        source.commit()
        source.close()

    def test_backup_captures_all_rows(self):
        backup = startup_db.create_backup(self.db_path)
        self.assertTrue(backup.exists())
        self.assertEqual(
            logical_fingerprint(backup), logical_fingerprint(self.db_path)
        )

    def test_backup_is_written_into_a_backups_subfolder(self):
        backup = startup_db.create_backup(self.db_path)
        self.assertEqual(backup.parent, self.root / "backups")

    def test_backup_passes_integrity_check(self):
        backup = startup_db.create_backup(self.db_path)
        conn = sqlite3.connect(backup)
        try:
            self.assertEqual(
                conn.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )
        finally:
            conn.close()

    def test_legacy_bak_file_is_also_written(self):
        startup_db.create_backup(self.db_path)
        legacy = Path(f"{self.db_path}.bak")
        self.assertTrue(legacy.exists(), "older runbooks restore from .bak")
        self.assertEqual(
            logical_fingerprint(legacy), logical_fingerprint(self.db_path)
        )

    def test_prune_keeps_only_the_newest(self):
        directory = self.root / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        for i in range(9):
            (directory / f"nass-2026010{i}-000000.sqlite3").write_bytes(b"old")
        removed = startup_db.prune_backups(self.db_path, keep=3)
        self.assertEqual(len(list(startup_db.list_backups(self.db_path))), 3)
        self.assertEqual(len(removed), 6)

    def test_corrupt_source_raises_instead_of_writing_a_backup(self):
        broken = self.root / "broken.sqlite3"
        broken.write_bytes(b"this is definitely not a sqlite database")
        with self.assertRaises(DatabaseSafetyError):
            startup_db.create_backup(broken)


class PrepareDatabaseTests(TestCase):
    def test_no_backup_when_schema_is_current(self):
        # The test database is fully migrated, so a routine launch must not
        # churn backups or overwrite the last known-good one.
        with mock.patch("django.core.management.call_command") as migrate:
            backup = prepare_database()
        self.assertIsNone(backup)
        migrate.assert_not_called()

    def test_backup_is_taken_before_migrating(self):
        order = []

        def record_backup(_db_path, keep=startup_db.KEEP_BACKUPS):
            order.append("backup")
            return Path("backup.sqlite3")

        def record_migrate(*_a, **k):
            order.append("migrate")

        with mock.patch.object(
            startup_db, "has_pending_migrations", return_value=True
        ), mock.patch.object(
            startup_db, "create_backup", side_effect=record_backup
        ), mock.patch(
            "django.core.management.call_command", side_effect=record_migrate
        ):
            backup = prepare_database()

        self.assertEqual(order, ["backup", "migrate"])
        self.assertEqual(backup, Path("backup.sqlite3"))

    def test_failed_migration_raises_and_stops_the_app(self):
        with mock.patch.object(
            startup_db, "has_pending_migrations", return_value=True
        ), mock.patch.object(
            startup_db, "create_backup", return_value=Path("backup.sqlite3")
        ), mock.patch(
            "django.core.management.call_command",
            side_effect=RuntimeError("migration 0018 blew up"),
        ):
            with self.assertRaises(DatabaseSafetyError) as caught:
                prepare_database()

        message = str(caught.exception)
        self.assertIn("has not been started", message)
        self.assertIn("backup.sqlite3", message)
        self.assertIn("migration 0018 blew up", message)

    def test_failed_backup_raises_rather_than_migrating(self):
        with mock.patch.object(
            startup_db, "has_pending_migrations", return_value=True
        ), mock.patch.object(
            startup_db,
            "create_backup",
            side_effect=OSError("disk full"),
        ), mock.patch("django.core.management.call_command") as migrate:
            with self.assertRaises(DatabaseSafetyError):
                prepare_database()

        migrate.assert_not_called()


class MainWiringTests(TestCase):
    def test_main_exits_instead_of_starting_the_gui_on_failure(self):
        source = (_DESKTOP_APP / "main.py").read_text(encoding="utf-8")
        self.assertIn("except DatabaseSafetyError", source)
        self.assertIn("sys.exit(1)", source)
        self.assertIn("prepare_database()", source)

    def test_main_no_longer_backs_up_with_a_plain_file_copy(self):
        source = (_DESKTOP_APP / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("shutil.copy2", source)


if __name__ == "__main__":
    import unittest

    unittest.main()