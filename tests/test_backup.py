import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.backup_service import (
    APP_VERSION,
    cleanup_old_backups,
    delete_backups,
    inspect_backup,
)


class TestBackupService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="aliasarr_test_backups_")
        self.patcher = patch("app.services.backup_service.BACKUP_DIR", self.test_dir)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_inspect_modern_backup_manifest(self):
        manifest_data = {
            "app": "Aliasarr",
            "version": APP_VERSION,
            "backup_type": "full",
            "created_at": "2026-08-19T17:45:00",
            "stats": {
                "shows": 12,
                "episodes": 350,
                "custom_formats": 17,
                "quality_profiles": 3,
                "indexers": 4,
                "download_clients": 2,
            },
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest_data))
            zf.writestr("database_export.json", json.dumps({"tables": {}}))
            zf.writestr("aliasarr.db", b"fake sqlite binary data")

        meta = inspect_backup(buf.getvalue())
        self.assertTrue(meta["valid"])
        self.assertEqual(meta["backup_type"], "full")
        self.assertEqual(meta["version"], APP_VERSION)
        self.assertEqual(meta["stats"]["shows"], 12)
        self.assertEqual(meta["stats"]["custom_formats"], 17)
        self.assertTrue(meta["has_database_dump"])

    def test_inspect_legacy_backup_compatibility(self):
        legacy_payload = {
            "created_at": "2026-01-01T12:00:00",
            "app_settings": {"rename_template": "{Series Title}"},
            "tables": {
                "indexers": [{"id": 1, "name": "Rutracker"}],
                "quality_profiles": [{"id": 1, "name": "HD-1080p"}],
            },
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("settings.json", json.dumps(legacy_payload))

        meta = inspect_backup(buf.getvalue())
        self.assertTrue(meta["valid"])
        self.assertEqual(meta["backup_type"], "config")
        self.assertEqual(meta["stats"]["indexers"], 1)
        self.assertFalse(meta["has_database_dump"])

    def test_cleanup_old_backups(self):
        for i in range(5):
            fname = os.path.join(self.test_dir, f"backup_{i}.zip")
            with zipfile.ZipFile(fname, "w") as zf:
                zf.writestr("manifest.json", "{}")

        self.assertEqual(len(os.listdir(self.test_dir)), 5)
        deleted = cleanup_old_backups(retention_count=3)
        self.assertEqual(deleted, 2)
        remaining = [f for f in os.listdir(self.test_dir) if f.endswith(".zip")]
        self.assertEqual(len(remaining), 3)

    def test_delete_backups(self):
        fname1 = os.path.join(self.test_dir, "b1.zip")
        fname2 = os.path.join(self.test_dir, "b2.zip")
        for f in (fname1, fname2):
            with open(f, "w") as fp:
                fp.write("dummy")

        deleted = delete_backups(["b1.zip", "b2.zip", "non_existent.zip"])
        self.assertEqual(set(deleted), {"b1.zip", "b2.zip"})
        self.assertFalse(os.path.exists(fname1))
        self.assertFalse(os.path.exists(fname2))


if __name__ == "__main__":
    unittest.main()
