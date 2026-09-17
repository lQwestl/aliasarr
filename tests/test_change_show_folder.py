"""Смена папки тайтла: перенос файлов, перепривязка путей и защита от опасных путей."""

from __future__ import annotations

import os
import tempfile
import unittest

try:
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.shows import change_show_folder, preview_change_show_folder, ChangeShowFolderIn
    from app.models.db import AppSettings, Base, Episode, Show, User
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "SQLAlchemy / FastAPI dependencies not installed in host runner")
class TestChangeShowFolder(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.old_dir = os.path.join(self.root, "Old Title")
        os.makedirs(os.path.join(self.old_dir, "Season 01"))

        self.episode_file = os.path.join(self.old_dir, "Season 01", "ep01.mkv")
        with open(self.episode_file, "w", encoding="utf-8") as fh:
            fh.write("video")

        self.db.add(AppSettings(id=1, api_key="test-key", root_folder=self.root, root_folder_series=self.root))
        self.user = User(username="admin", password_hash="hash", is_admin=True, is_owner=True)
        self.db.add(self.user)
        self.db.commit()

        self.show = Show(title="Old Title", content_type="series", path=self.old_dir)
        self.db.add(self.show)
        self.db.commit()

        self.episode = Episode(
            show_id=self.show.id,
            season_number=1,
            episode_number=1,
            title="Ep 1",
            file_path=self.episode_file,
        )
        self.db.add(self.episode)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _change(self, path: str, move_files: bool = True):
        return change_show_folder(
            self.show.id,
            ChangeShowFolderIn(path=path, move_files=move_files),
            db=self.db,
            current_user=self.user,
        )

    def test_move_relocates_files_and_repoints_episodes(self):
        new_dir = os.path.join(self.root, "New Title")
        res = self._change(new_dir)

        self.assertTrue(res["success"], res["errors"])
        self.assertEqual(res["updated_episodes"], 1)

        self.db.refresh(self.show)
        self.db.refresh(self.episode)

        self.assertEqual(self.show.path, new_dir)
        self.assertEqual(self.episode.file_path, os.path.join(new_dir, "Season 01", "ep01.mkv"))
        self.assertTrue(os.path.isfile(self.episode.file_path))
        self.assertFalse(os.path.exists(self.old_dir), "опустевшая старая папка должна удаляться")

    def test_relink_mode_leaves_disk_untouched(self):
        new_dir = os.path.join(self.root, "Already Moved")
        os.makedirs(new_dir)

        res = self._change(new_dir, move_files=False)

        self.db.refresh(self.show)
        self.db.refresh(self.episode)

        self.assertEqual(self.show.path, new_dir)
        self.assertEqual(self.episode.file_path, os.path.join(new_dir, "Season 01", "ep01.mkv"))
        self.assertEqual(res["moved_files"], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.old_dir, "Season 01", "ep01.mkv")),
                        "в режиме перепривязки файлы на диске не трогаем")

    def test_existing_destination_entry_is_not_overwritten(self):
        new_dir = os.path.join(self.root, "New Title")
        os.makedirs(os.path.join(new_dir, "Season 01"))
        with open(os.path.join(new_dir, "Season 01", "keepme.mkv"), "w", encoding="utf-8") as fh:
            fh.write("other")

        res = self._change(new_dir)

        # «Season 01» уже существует в цели — папка не затирается, о конфликте сообщаем.
        self.assertFalse(res["success"])
        self.assertTrue(any("Season 01" in e for e in res["errors"]), res["errors"])
        self.assertTrue(os.path.isfile(os.path.join(new_dir, "Season 01", "keepme.mkv")))
        self.assertTrue(os.path.isfile(self.episode_file))

    def test_same_path_is_a_noop(self):
        res = self._change(self.old_dir)
        self.assertTrue(res["success"])
        self.assertEqual(res["moved_files"], 0)
        self.assertEqual(res["updated_episodes"], 0)

    def test_path_outside_library_roots_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._change("/etc/aliasarr-should-not-go-here")
        self.assertEqual(ctx.exception.status_code, 400)

        self.db.refresh(self.show)
        self.assertEqual(self.show.path, self.old_dir)

    def test_library_root_itself_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._change(self.root)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_nested_target_is_rejected_when_moving(self):
        with self.assertRaises(HTTPException) as ctx:
            self._change(os.path.join(self.old_dir, "Inner"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_relative_and_untidy_paths_are_normalized(self):
        messy = os.path.join(self.root, "A", "..", "New Title") + "/"
        res = self._change(messy)
        self.assertEqual(res["new_path"], os.path.join(self.root, "New Title"))

    def test_preview_reports_volume_and_warnings(self):
        new_dir = os.path.join(self.root, "New Title")
        os.makedirs(new_dir)
        with open(os.path.join(new_dir, "stray.txt"), "w", encoding="utf-8") as fh:
            fh.write("x")

        data = preview_change_show_folder(
            self.show.id, path=new_dir, db=self.db, current_user=self.user
        )

        self.assertEqual(data["old_path"], self.old_dir)
        self.assertEqual(data["new_path"], new_dir)
        self.assertTrue(data["old_path_exists"])
        self.assertEqual(data["files_to_move"], 1)
        self.assertGreater(data["bytes_to_move"], 0)
        self.assertEqual(data["episodes_linked"], 1)
        self.assertTrue(data["target_exists"])
        self.assertTrue(any("не пуста" in w for w in data["warnings"]), data["warnings"])

    def test_missing_source_folder_degrades_to_relink(self):
        import shutil

        shutil.rmtree(self.old_dir)
        new_dir = os.path.join(self.root, "New Title")

        res = self._change(new_dir)

        self.db.refresh(self.show)
        self.assertEqual(self.show.path, new_dir)
        self.assertEqual(res["moved_files"], 0)
        self.assertTrue(any("не найдена" in e for e in res["errors"]), res["errors"])
        self.assertTrue(os.path.isdir(new_dir), "новая папка создаётся даже без переноса")


if __name__ == "__main__":
    unittest.main()
