"""Гранулярное удаление контента: что именно уходит с диска.

Проверяет два сценария потери данных: удаление соседних серий заодно с выбранной
и вынос корневой папки при чистке «пустой папки сезона».
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.shows import delete_content
    from app.models.db import AppSettings, Base, Episode, EpisodeStatus, Show, User
    from app.schemas import DeleteContentPayload
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "SQLAlchemy / FastAPI dependencies not installed in host runner")
class TestDeleteContentFileSafety(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)

        self.db.add(AppSettings(id=1, api_key="test-key", root_folder=self.root, root_folder_anime=self.root))
        self.user = User(username="admin", password_hash="hash", is_admin=True, is_owner=True)
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _write(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")
        return path

    def _delete_seasons(self, show, seasons):
        return asyncio.run(
            delete_content(
                show.id,
                DeleteContentPayload(delete_mode="seasons", delete_files=True, season_numbers=seasons),
                db=self.db,
                current_user=self.user,
            )
        )

    def test_unpadded_numbering_does_not_take_neighbouring_episodes(self):
        show_dir = os.path.join(self.root, "Naruto")
        season_dir = os.path.join(show_dir, "Сезон 1")
        show = Show(title="Naruto", content_type="anime", path=show_dir)
        self.db.add(show)
        self.db.commit()

        ep1_file = self._write(os.path.join(season_dir, "Naruto - 1.mkv"))
        ep1_sub = self._write(os.path.join(season_dir, "Naruto - 1.rus.srt"))
        ep10_file = self._write(os.path.join(season_dir, "Naruto - 10.mkv"))
        ep10_sub = self._write(os.path.join(season_dir, "Naruto - 10.rus.srt"))

        self.db.add(Episode(show_id=show.id, season_number=1, episode_number=1,
                            title="1", file_path=ep1_file, status=EpisodeStatus.DOWNLOADED))
        self.db.add(Episode(show_id=show.id, season_number=2, episode_number=1,
                            title="10", file_path=ep10_file, status=EpisodeStatus.DOWNLOADED))
        self.db.commit()

        self._delete_seasons(show, [1])

        self.assertFalse(os.path.exists(ep1_file))
        self.assertFalse(os.path.exists(ep1_sub))
        self.assertTrue(os.path.exists(ep10_file), "десятая серия не должна удаляться вместе с первой")
        self.assertTrue(os.path.exists(ep10_sub), "субтитры десятой серии тоже должны остаться")

    def test_files_stored_in_the_library_root_do_not_wipe_it(self):
        # Файлы лежат прямо в корне медиатеки: родитель удалённого файла — сам корень.
        show = Show(title="Loose Movie", content_type="anime", path=self.root)
        self.db.add(show)
        self.db.commit()

        ep_file = self._write(os.path.join(self.root, "loose.mkv"))

        self.db.add(Episode(show_id=show.id, season_number=1, episode_number=1,
                            title="1", file_path=ep_file, status=EpisodeStatus.DOWNLOADED))
        self.db.commit()

        self._delete_seasons(show, [1])

        self.assertFalse(os.path.exists(ep_file))
        # Корень опустел — старая чистка «пустой папки сезона» снесла бы его целиком
        # вместе со всем, что появится в нём позже.
        self.assertTrue(os.path.isdir(self.root), "корень медиатеки удалять нельзя")

    def test_empty_season_folder_is_still_cleaned_up(self):
        show_dir = os.path.join(self.root, "Show")
        season_dir = os.path.join(show_dir, "Season 01")
        show = Show(title="Show", content_type="anime", path=show_dir)
        self.db.add(show)
        self.db.commit()

        ep_file = self._write(os.path.join(season_dir, "Show - S01E01.mkv"))
        self.db.add(Episode(show_id=show.id, season_number=1, episode_number=1,
                            title="1", file_path=ep_file, status=EpisodeStatus.DOWNLOADED))
        self.db.commit()

        self._delete_seasons(show, [1])

        self.assertFalse(os.path.isdir(season_dir), "опустевшая папка сезона убирается как и раньше")
        self.assertTrue(os.path.isdir(show_dir), "папка тайтла остаётся")


if __name__ == "__main__":
    unittest.main()
