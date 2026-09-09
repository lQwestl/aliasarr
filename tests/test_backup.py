from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import (
        Base,
        Blocklist,
        Episode,
        SeasonSplit,
        SeasonSplitPart,
        Show,
    )
    from app.services.backup_service import create_backup, restore_backup
    HAS_DB = True
except ImportError:
    HAS_DB = False


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
                "season_splits": 2,
                "custom_formats": 17,
                "quality_profiles": 3,
                "indexers": 4,
                "download_clients": 2,
                "blocklist": 5,
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

    @unittest.skipUnless(HAS_DB, "SQLAlchemy required")
    def test_backup_and_restore_season_splits_and_blocklist(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        # Seed data
        show = Show(title="Space Dandy", content_type="series", year=2014)
        db.add(show)
        db.flush()

        ep1 = Episode(show_id=show.id, season_number=1, episode_number=1, title="Live with the Flow, Baby")
        ep14 = Episode(show_id=show.id, season_number=1, episode_number=14, title="I Can't Be the Only One, Baby")
        db.add_all([ep1, ep14])

        split = SeasonSplit(show_id=show.id, name="Season 1", season_number=1)
        db.add(split)
        db.flush()

        part1 = SeasonSplitPart(split_id=split.id, target_number=1, episode_start=1, episode_end=13, episode_offset=0, aliases="Space Dandy")
        part2 = SeasonSplitPart(split_id=split.id, target_number=2, episode_start=14, episode_end=26, episode_offset=13, aliases="Space Dandy 2")
        db.add_all([part1, part2])

        block = Blocklist(show_id=show.id, release_title="Space Dandy S01 Fake", reason="fake bad audio")
        db.add(block)
        db.commit()

        # Create backup
        backup_info = create_backup(db, backup_type="full")
        self.assertEqual(backup_info["stats"]["shows"], 1)
        self.assertEqual(backup_info["stats"]["season_splits"], 1)
        self.assertEqual(backup_info["stats"]["blocklist"], 1)

        # Clear and restore in a fresh database
        engine2 = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine2)
        Session2 = sessionmaker(bind=engine2)
        db2 = Session2()

        archive_path = os.path.join(self.test_dir, backup_info["name"])
        res = restore_backup(db2, archive_path, mode="full")
        self.assertTrue(res["success"])

        # Verify restored entities
        restored_shows = db2.query(Show).all()
        self.assertEqual(len(restored_shows), 1)
        self.assertEqual(restored_shows[0].title, "Space Dandy")

        restored_splits = db2.query(SeasonSplit).all()
        self.assertEqual(len(restored_splits), 1)
        self.assertEqual(restored_splits[0].show_id, restored_shows[0].id)
        self.assertEqual(len(restored_splits[0].parts), 2)
        self.assertEqual(restored_splits[0].parts[1].episode_offset, 13)
        self.assertEqual(restored_splits[0].parts[1].aliases, "Space Dandy 2")

        restored_blocks = db2.query(Blocklist).all()
        self.assertEqual(len(restored_blocks), 1)
        self.assertEqual(restored_blocks[0].show_id, restored_shows[0].id)
        self.assertEqual(restored_blocks[0].release_title, "Space Dandy S01 Fake")

        db.close()
        db2.close()


if __name__ == "__main__":
    unittest.main()
