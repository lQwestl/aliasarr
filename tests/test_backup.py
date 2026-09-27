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
        AppSettings,
        Base,
        Blocklist,
        CustomFormat,
        DownloadClient,
        DownloadHistory,
        Episode,
        Indexer,
        MovieCollection,
        QualityProfile,
        SeasonSplit,
        SeasonSplitPart,
        Show,
        TrackedRelease,
        User,
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

    def _file_db(self, name):
        engine = create_engine(f"sqlite:///{os.path.join(self.test_dir, name)}")
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)

    def _rewrite_export(self, archive_path, mutate):
        with zipfile.ZipFile(archive_path) as src:
            entries = {name: src.read(name) for name in src.namelist()}
        payload = json.loads(entries["database_export.json"])
        mutate(payload)
        entries["database_export.json"] = json.dumps(payload).encode("utf-8")
        patched = archive_path + ".patched.zip"
        with zipfile.ZipFile(patched, "w") as dst:
            for name, data in entries.items():
                dst.writestr(name, data)
        return patched

    @unittest.skipUnless(HAS_DB, "SQLAlchemy required")
    def test_restore_ignores_columns_unknown_to_this_version(self):
        Session = self._file_db("unknown_columns.db")
        db = Session()
        show = Show(title="Dexter", content_type="series")
        db.add(show)
        db.flush()
        db.add(Episode(show_id=show.id, season_number=1, episode_number=1))
        db.commit()
        info = create_backup(db, backup_type="full")

        def add_legacy_fields(payload):
            payload["tables"]["shows"][0]["legacy_removed_column"] = 1
            payload["tables"]["episodes"][0]["column_from_newer_version"] = "x"

        archive = self._rewrite_export(os.path.join(self.test_dir, info["name"]), add_legacy_fields)
        res = restore_backup(db, archive, mode="full")
        self.assertTrue(res["success"])
        check = Session()
        self.assertEqual([s.title for s in check.query(Show).all()], ["Dexter"])
        self.assertEqual(check.query(Episode).count(), 1)
        check.close()
        db.close()

    @unittest.skipUnless(HAS_DB, "SQLAlchemy required")
    def test_failed_restore_leaves_library_untouched(self):
        Session = self._file_db("failed_restore.db")
        db = Session()
        show = Show(title="Space Dandy", content_type="series")
        db.add(show)
        db.flush()
        db.add(SeasonSplit(show_id=show.id, name="Season 1", season_number=1))
        db.commit()
        info = create_backup(db, backup_type="full")

        db.add(Show(title="Added after backup", content_type="series"))
        db.commit()

        import app.services.backup_service as backup_service

        class _BrokenSplit:
            __table__ = SeasonSplit.__table__

            def __init__(self, **kwargs):
                raise RuntimeError("simulated failure in the middle of a restore")

        with patch.object(backup_service, "SeasonSplit", _BrokenSplit):
            with self.assertRaises(RuntimeError):
                restore_backup(db, os.path.join(self.test_dir, info["name"]), mode="full")

        check = Session()
        self.assertEqual(
            sorted(s.title for s in check.query(Show).all()),
            ["Added after backup", "Space Dandy"],
        )
        self.assertEqual(check.query(SeasonSplit).count(), 1)
        check.close()
        db.close()

    @unittest.skipUnless(HAS_DB, "SQLAlchemy required")
    def test_backup_and_restore_movie_collections_and_foreign_keys(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        # 1. Настройки и профиль качества
        qp = QualityProfile(id=7, name="Ultra-HD 4K", cutoff_score=100)
        db.add(qp)
        settings = AppSettings(
            id=1,
            api_key="secret_test_key_12345",
            default_quality_profile_movie_id=7,
            metadata_title_language="ru",
        )
        db.add(settings)
        db.flush()

        # 2. Коллекция фильмов
        col = MovieCollection(
            id=10,
            tmdb_collection_id=12444,
            title="Harry Potter Collection",
            overview="All Harry Potter movies",
            quality_profile_id=7,
        )
        db.add(col)
        db.flush()

        # 3. Фильм внутри коллекции с привязкой к профилю
        show = Show(
            id=42,
            title="Гарри Поттер и философский камень",
            content_type="movie",
            year=2001,
            collection_id=col.id,
            quality_profile_id=7,
        )
        db.add(show)
        db.flush()

        # 4. Эпизод и история загрузок
        ep = Episode(id=101, show_id=show.id, season_number=1, episode_number=1, title="Movie")
        db.add(ep)
        db.flush()

        hist = DownloadHistory(
            show_id=show.id,
            episode_id=ep.id,
            release_title="Harry Potter 2001 2160p UHD",
            event_type="grabbed",
        )
        db.add(hist)
        db.commit()

        # Создание бэкапа
        backup_info = create_backup(db, backup_type="full")
        self.assertEqual(backup_info["stats"]["movie_collections"], 1)
        self.assertEqual(backup_info["stats"]["shows"], 1)
        self.assertEqual(backup_info["stats"]["episodes"], 1)
        self.assertEqual(backup_info["stats"]["quality_profiles"], 1)

        # Восстановление в чистую базу
        engine2 = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine2)
        Session2 = sessionmaker(bind=engine2)
        db2 = Session2()

        archive_path = os.path.join(self.test_dir, backup_info["name"])
        res = restore_backup(db2, archive_path, mode="full")
        self.assertTrue(res["success"])

        # Проверка восстановления коллекции и связей
        restored_cols = db2.query(MovieCollection).all()
        self.assertEqual(len(restored_cols), 1)
        self.assertEqual(restored_cols[0].title, "Harry Potter Collection")
        self.assertEqual(restored_cols[0].quality_profile_id, 7)

        restored_shows = db2.query(Show).all()
        self.assertEqual(len(restored_shows), 1)
        self.assertEqual(restored_shows[0].title, "Гарри Поттер и философский камень")
        self.assertEqual(restored_shows[0].collection_id, restored_cols[0].id)
        self.assertEqual(restored_shows[0].quality_profile_id, 7)

        # Проверка сохранения настроек и ключа API
        restored_settings = db2.query(AppSettings).first()
        self.assertIsNotNone(restored_settings)
        self.assertEqual(restored_settings.api_key, "secret_test_key_12345")
        self.assertEqual(restored_settings.default_quality_profile_movie_id, 7)
        self.assertEqual(restored_settings.metadata_title_language, "ru")

        # Проверка связности истории загрузок с эпизодом
        restored_eps = db2.query(Episode).all()
        self.assertEqual(len(restored_eps), 1)
        restored_hist = db2.query(DownloadHistory).all()
        self.assertEqual(len(restored_hist), 1)
        self.assertEqual(restored_hist[0].episode_id, restored_eps[0].id)

        db.close()
        db2.close()


if __name__ == "__main__":
    unittest.main()
