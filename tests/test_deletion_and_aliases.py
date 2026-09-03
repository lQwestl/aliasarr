from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import datetime as dt

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import Base, Show, Episode, Alias, EpisodeStatus, AliasLanguage, User, UserRole
    from app.schemas import AliasCreate, ShowCreate, DeleteContentPayload
    from app.api.shows import add_alias, create_show, delete_content
    from app.services.metadata import should_refresh_show, trigger_show_metadata_refresh_if_needed
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "Requires sqlalchemy, fastapi, and pydantic")
class TestDeletionAndAliases(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.temp_dir = tempfile.mkdtemp()

        self.user = User(
            id=1,
            username="admin",
            role=UserRole.ADMIN,
            is_active=True,
            password_hash="hash",
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_alias_priority_autoincrement(self):
        # 1. Создаем шоу с 2 алиасами без явного приоритета -> должны получить 1 и 2
        payload = ShowCreate(
            title="Test Show",
            aliases=[
                AliasCreate(text="Test Alias 1"),
                AliasCreate(text="Test Alias 2"),
            ],
        )
        show = create_show(payload, db=self.db, current_user=self.user)
        aliases = self.db.query(Alias).filter(Alias.show_id == show.id).order_by(Alias.priority).all()
        self.assertEqual(len(aliases), 2)
        self.assertEqual(aliases[0].priority, 1)
        self.assertEqual(aliases[1].priority, 2)

        # 2. Добавляем новый алиас через add_alias без явного приоритета -> должен получить 3
        new_alias = add_alias(show.id, AliasCreate(text="Test Alias 3"), db=self.db, current_user=self.user)
        self.assertEqual(new_alias.priority, 3)

        # 3. Добавляем еще один -> должен получить 4
        new_alias2 = add_alias(show.id, AliasCreate(text="Test Alias 4"), db=self.db, current_user=self.user)
        self.assertEqual(new_alias2.priority, 4)

    def test_granular_delete_seasons_resets_to_wanted(self):
        import asyncio

        # Создаем тестовую структуру файлов
        show_dir = os.path.join(self.temp_dir, "Show Title")
        s1_dir = os.path.join(show_dir, "Season 1")
        s2_dir = os.path.join(show_dir, "Season 2")
        os.makedirs(s1_dir, exist_ok=True)
        os.makedirs(s2_dir, exist_ok=True)

        ep1_file = os.path.join(s1_dir, "Show Title - S01E01.mkv")
        ep1_sub = os.path.join(s1_dir, "Show Title - S01E01.rus.srt")
        ep2_file = os.path.join(s1_dir, "Show Title - S01E02.mkv")
        ep3_file = os.path.join(s2_dir, "Show Title - S02E01.mkv")

        with open(ep1_file, "w") as f: f.write("video1")
        with open(ep1_sub, "w") as f: f.write("sub1")
        with open(ep2_file, "w") as f: f.write("video2")
        with open(ep3_file, "w") as f: f.write("video3")

        show = Show(title="Show Title", path=show_dir, content_type="series")
        self.db.add(show)
        self.db.flush()

        ep1 = Episode(show_id=show.id, season_number=1, episode_number=1, title="Ep 1", file_path=ep1_file, file_size=6, status=EpisodeStatus.DOWNLOADED)
        ep2 = Episode(show_id=show.id, season_number=1, episode_number=2, title="Ep 2", file_path=ep2_file, file_size=6, status=EpisodeStatus.DOWNLOADED)
        ep3 = Episode(show_id=show.id, season_number=2, episode_number=1, title="Ep 3", file_path=ep3_file, file_size=6, status=EpisodeStatus.DOWNLOADED)
        self.db.add_all([ep1, ep2, ep3])
        self.db.commit()

        # Удаляем Season 1 с физическим удалением файлов и сбросом в WANTED
        del_payload = DeleteContentPayload(
            delete_mode="seasons",
            delete_files=True,
            season_numbers=[1],
            reset_to_wanted=True,
        )
        res = asyncio.run(delete_content(show.id, del_payload, db=self.db, current_user=self.user))
        self.assertTrue(res.success)
        self.assertEqual(res.episodes_affected_count, 2)
        self.assertEqual(res.deleted_files_count, 2)

        # Проверяем, что файлы 1-го сезона удалены с диска, а 2-й сезон остался
        self.assertFalse(os.path.exists(ep1_file))
        self.assertFalse(os.path.exists(ep1_sub))
        self.assertFalse(os.path.exists(ep2_file))
        self.assertTrue(os.path.exists(ep3_file))

        # Проверяем, что записи серий 1-го сезона сброшены в WANTED и file_path = None
        self.db.refresh(ep1)
        self.db.refresh(ep2)
        self.db.refresh(ep3)

        self.assertEqual(ep1.status, EpisodeStatus.WANTED)
        self.assertIsNone(ep1.file_path)
        self.assertEqual(ep1.file_size, 0)
        self.assertTrue(ep1.monitored)

        self.assertEqual(ep2.status, EpisodeStatus.WANTED)
        self.assertIsNone(ep2.file_path)

        # Сезон 2 не затронут
        self.assertEqual(ep3.status, EpisodeStatus.DOWNLOADED)
        self.assertEqual(ep3.file_path, ep3_file)

    def test_granular_delete_episodes_resets_to_wanted(self):
        import asyncio

        show_dir = os.path.join(self.temp_dir, "Show Title 2")
        os.makedirs(show_dir, exist_ok=True)
        ep1_file = os.path.join(show_dir, "ep1.mkv")
        ep2_file = os.path.join(show_dir, "ep2.mkv")
        with open(ep1_file, "w") as f: f.write("video1")
        with open(ep2_file, "w") as f: f.write("video2")

        show = Show(title="Show Title 2", path=show_dir, content_type="series")
        self.db.add(show)
        self.db.flush()

        ep1 = Episode(show_id=show.id, season_number=1, episode_number=1, file_path=ep1_file, file_size=6, status=EpisodeStatus.DOWNLOADED)
        ep2 = Episode(show_id=show.id, season_number=1, episode_number=2, file_path=ep2_file, file_size=6, status=EpisodeStatus.DOWNLOADED)
        self.db.add_all([ep1, ep2])
        self.db.commit()

        # Удаляем только серию 1
        del_payload = DeleteContentPayload(
            delete_mode="episodes",
            delete_files=True,
            episode_ids=[ep1.id],
            reset_to_wanted=True,
        )
        res = asyncio.run(delete_content(show.id, del_payload, db=self.db, current_user=self.user))
        self.assertTrue(res.success)
        self.assertEqual(res.episodes_affected_count, 1)

        self.assertFalse(os.path.exists(ep1_file))
        self.assertTrue(os.path.exists(ep2_file))

        self.db.refresh(ep1)
        self.db.refresh(ep2)
        self.assertEqual(ep1.status, EpisodeStatus.WANTED)
        self.assertIsNone(ep1.file_path)
        self.assertEqual(ep2.status, EpisodeStatus.DOWNLOADED)

    def test_should_refresh_throttle_15_minutes(self):
        now = dt.datetime.utcnow()
        show = Show(
            title="Anime Test",
            content_type="anime",
            last_metadata_refresh_at=now - dt.timedelta(minutes=5),
        )
        self.db.add(show)
        self.db.flush()
        ep = Episode(show_id=show.id, season_number=1, episode_number=1, title="Episode 1")
        self.db.add(ep)
        self.db.commit()

        # Несмотря на наличие placeholder title ("Episode 1"), прошло только 5 минут -> should_refresh_show = False
        self.assertFalse(should_refresh_show(show, self.db))

        # Если прошло 20 минут -> should_refresh_show = True
        show.last_metadata_refresh_at = now - dt.timedelta(minutes=20)
        self.db.commit()
        self.assertTrue(should_refresh_show(show, self.db))

    def test_delete_queue_item_resets_episodes(self):
        import asyncio
        from app.api.operations import delete_queue_item

        show = Show(title="Queue Show", content_type="anime")
        self.db.add(show)
        self.db.flush()

        t_hash = "abcdef1234567890"
        ep = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=1,
            torrent_hash=t_hash,
            status=EpisodeStatus.DOWNLOADING,
            download_progress=0.45,
        )
        self.db.add(ep)
        self.db.commit()

        res = asyncio.run(delete_queue_item(torrent_hash=t_hash, delete_files=False, db=self.db, current_user=self.user))
        self.assertEqual(res["status"], "deleted")
        self.assertEqual(res["affected_episodes"], 1)

        self.db.refresh(ep)
        self.assertEqual(ep.status, EpisodeStatus.WANTED)
        self.assertIsNone(ep.torrent_hash)
        self.assertEqual(ep.download_progress, 0.0)


if __name__ == "__main__":
    unittest.main()
