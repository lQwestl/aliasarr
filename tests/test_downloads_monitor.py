import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.download_client import TorrentInfo
from app.services.downloads_monitor import _COMPLETE_THRESHOLD, _folder_and_template, _resolve_download_path, check_downloads


class FakeClient:
    def __init__(self, torrents):
        self._torrents = torrents

    async def list_torrents(self):
        return self._torrents


class TestDownloadsMonitor(unittest.TestCase):
    def test_folder_and_template(self):
        settings = SimpleNamespace(
            root_folder="/media",
            root_folder_movies="/media/movies",
            root_folder_series="/media/series",
            root_folder_anime="/media/anime",
            rename_template_movie="{Movie Title}",
            rename_template_series="{Series Title}",
            rename_template_anime="{Series Title} (Anime)",
            season_folder_template_series="Season {season}",
            season_folder_template_anime="Season {season}",
        )
        movie_root, movie_tpl, _ = _folder_and_template(settings, "movie")
        self.assertEqual(movie_root, "/media/movies")
        self.assertEqual(movie_tpl, "{Movie Title}")

        series_root, series_tpl, s_tpl = _folder_and_template(settings, "series")
        self.assertEqual(series_root, "/media/series")
        self.assertEqual(s_tpl, "Season {season}")

        anime_root, anime_tpl, a_tpl = _folder_and_template(settings, "anime")
        self.assertEqual(anime_root, "/media/anime")

    def test_resolve_download_path(self):
        settings = SimpleNamespace(
            download_folder_movies="/downloads/movies",
            download_folder_series="/downloads/series",
            download_folder_anime="/downloads/anime",
        )
        t = SimpleNamespace(save_path="/downloads/movies", name="My.Movie.2024.1080p.mkv")
        res = _resolve_download_path(t, settings, "movie")
        self.assertIn("My.Movie.2024.1080p.mkv", res)

    def test_progress_updates_without_reaching_threshold(self):
        show = SimpleNamespace(id=1, title="Test Show", content_type="series", monitored=True)
        dc = SimpleNamespace(id=10, name="DC1", type="qbittorrent", enabled=True)
        ep = SimpleNamespace(
            id=101, show_id=1, season_number=1, episode_number=1,
            status="downloading", torrent_hash="hash1",
            download_client_id=10, download_progress=0.0,
        )

        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.all.side_effect = [
            [ep],   # downloading episodes
            [dc],   # active clients
        ]
        db_mock.get.return_value = show

        torrent = TorrentInfo(hash="hash1", name="Test", progress=0.42, state="downloading", save_path="/tmp/x", size=100)
        settings = SimpleNamespace(root_folder="", root_folder_series="", rename_template_series="{Series Title}", season_folder_template_series="Season {season}")

        with patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.get_client", return_value=FakeClient([torrent])), \
             patch("app.services.downloads_monitor._run_postprocess_in_thread") as mock_postprocess:
            results = asyncio.run(check_downloads(db_mock))
            self.assertAlmostEqual(ep.download_progress, 0.42)
            self.assertEqual(ep.status, "downloading")
            self.assertFalse(mock_postprocess.called)
            self.assertEqual(results, [])

    def test_completed_torrent_triggers_postprocess_once_for_season_pack(self):
        show = SimpleNamespace(id=1, title="Test Show", content_type="series", monitored=True, path="/media/series/Test Show")
        dc = SimpleNamespace(id=10, name="DC1", type="qbittorrent", enabled=True)
        ep1 = SimpleNamespace(
            id=101, show_id=1, season_number=1, episode_number=1,
            status="downloading", torrent_hash="hash-pack",
            download_client_id=10, download_progress=0.0,
        )
        ep2 = SimpleNamespace(
            id=102, show_id=1, season_number=1, episode_number=2,
            status="downloading", torrent_hash="hash-pack",
            download_client_id=10, download_progress=0.0,
        )

        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.all.side_effect = [
            [ep1, ep2],   # downloading episodes
            [dc],         # active clients
        ]
        db_mock.get.return_value = show

        torrent = TorrentInfo(hash="hash-pack", name="Season Pack", progress=1.0, state="seeding", save_path="/tmp/pack", size=1000)
        settings = SimpleNamespace(root_folder="", root_folder_series="/media/series", rename_template_series="{Series Title}", season_folder_template_series="Season {season}")

        postprocess_called = []
        def fake_postprocess(show_id, dl_path, tpl, root, s_tpl, is_movie, specific_files=None, torrent_hash=None):
            postprocess_called.append((show_id, dl_path, is_movie, specific_files, torrent_hash))
            return [{"file": "a.mkv", "status": "imported", "dest": "/media/series/Test Show/Season 1/S01E01.mkv"}]

        with patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.get_client", return_value=FakeClient([torrent])), \
             patch("app.services.downloads_monitor._run_postprocess_in_thread", side_effect=fake_postprocess):
            results = asyncio.run(check_downloads(db_mock))
            self.assertEqual(len(postprocess_called), 1)
            self.assertEqual(postprocess_called[0][0], 1)
            self.assertFalse(postprocess_called[0][2])  # is_movie is False
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["torrent_hash"], "hash-pack")

    def test_movie_content_type_triggers_movie_postprocess(self):
        show = SimpleNamespace(id=2, title="Test Movie", content_type="movie", monitored=True, path="/media/movies/Test Movie")
        dc = SimpleNamespace(id=10, name="DC1", type="qbittorrent", enabled=True)
        ep = SimpleNamespace(
            id=201, show_id=2, season_number=1, episode_number=1,
            status="downloading", torrent_hash="hash-movie",
            download_client_id=10, download_progress=0.0,
        )

        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.all.side_effect = [
            [ep],   # downloading episodes
            [dc],   # active clients
        ]
        db_mock.get.return_value = show

        torrent = TorrentInfo(hash="hash-movie", name="Movie 2024", progress=1.0, state="seeding", save_path="/tmp/movie", size=5000)
        settings = SimpleNamespace(root_folder="", root_folder_movies="/media/movies", rename_template_movie="{Movie Title}")

        postprocess_called = []
        def fake_postprocess(show_id, dl_path, tpl, root, s_tpl, is_movie, specific_files=None, torrent_hash=None):
            postprocess_called.append((show_id, dl_path, is_movie, specific_files, torrent_hash))
            return [{"file": "movie.mkv", "status": "imported", "dest": "/media/movies/Test Movie/Test Movie (2024).mkv"}]

        with patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.get_client", return_value=FakeClient([torrent])), \
             patch("app.services.downloads_monitor._run_postprocess_in_thread", side_effect=fake_postprocess):
            results = asyncio.run(check_downloads(db_mock))
            self.assertEqual(len(postprocess_called), 1)
            self.assertTrue(postprocess_called[0][2])  # is_movie is True
            self.assertEqual(len(results), 1)

    def test_torrent_file_isolation_guarantee(self):
        import tempfile
        import shutil
        from app.services.download_client import TorrentFile
        from app.services.downloads_monitor import _resolve_torrent_files_and_path

        tmp = tempfile.mkdtemp()
        try:
            dl = os.path.join(tmp, "downloads")
            os.makedirs(dl, exist_ok=True)

            # Movie file in downloads root
            m_file = os.path.join(dl, "Robot.Chicken.Star.Wars.Episode.II.x264.BDRip.1080p-SergeZuich.mkv")
            with open(m_file, "wb") as f:
                f.write(b"video data")

            # Unrelated TV-sonarr directory with episodes
            unrelated = os.path.join(dl, "complete", "tv-sonarr", "Mushoku.Tensei.Season3.WEB-DL.1080p")
            os.makedirs(unrelated, exist_ok=True)
            for i in range(1, 9):
                with open(os.path.join(unrelated, f"Mushoku.Tensei.S03E0{i}.1080p.mkv"), "wb") as f:
                    f.write(b"anime episode data")

            show_movie = SimpleNamespace(id=5, title="Robot Chicken: Star Wars Episode II", content_type="movie", year=2008, path="")
            settings = SimpleNamespace(root_folder=tmp, download_folder_movies=dl, root_folder_movies="")

            t_movie = TorrentInfo(
                hash="hash-robot",
                name="Robot Chicken Star Wars Episode II (2008) BDRip 1080p",
                progress=1.0,
                state="seeding",
                save_path=dl,
                size=1000,
                files=[TorrentFile(index=0, name="Robot.Chicken.Star.Wars.Episode.II.x264.BDRip.1080p-SergeZuich.mkv", size=1000, progress=1.0, priority=1)],
            )

            resolved_path, specific_files = _resolve_torrent_files_and_path(t_movie, settings, show_movie)
            self.assertEqual(specific_files, [m_file])
            self.assertEqual(resolved_path, m_file)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_seeding_time_limit_logic(self):
        show = SimpleNamespace(id=1, title="Test Show", content_type="series", monitored=True)
        dc = SimpleNamespace(id=10, name="DC1", type="qbittorrent", enabled=True, seed_time_limit=60, seed_ratio_limit=None)
        ep = SimpleNamespace(
            id=101, show_id=1, season_number=1, episode_number=1,
            status="downloading", torrent_hash="hash1",
            download_client_id=10, download_progress=1.0,
        )

        def make_db():
            db = MagicMock()
            db.query.return_value.filter.return_value.all.side_effect = [
                [ep],   # episodes with downloading status
                [dc],   # download clients
            ]
            db.get.return_value = show
            return db

        settings = SimpleNamespace(
            root_folder="/media",
            root_folder_movies="",
            root_folder_series="/media/series",
            root_folder_anime="",
            rename_template_series="{Series Title}",
            rename_template_movie="{Movie Title}",
            rename_template_anime="{Series Title}",
            season_folder_template_series="Season {season}",
            season_folder_template_anime="Season {season}",
            download_folder_series="",
            download_folder_movies="",
            download_folder_anime="",
        )

        # 1. Seeding time not reached yet (20 minutes < 60 minutes)
        t_seeding = TorrentInfo(
            hash="hash1",
            name="Test.Show.S01E01.mkv",
            progress=1.0,
            state="seeding",
            save_path="/downloads",
            size=1000,
            seeding_time=1200,  # 20 min
            ratio=0.5,
        )
        fake_client = FakeClient([t_seeding])
        fake_client.pause_torrent = AsyncMock()
        fake_client.get_torrent = AsyncMock(return_value=t_seeding)

        db1 = make_db()
        with patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.get_client", return_value=fake_client), \
             patch("app.services.downloads_monitor._folder_and_template", return_value=("/media/series", "{Series Title}", "Season {season}")), \
             patch("app.services.downloads_monitor._run_postprocess_in_thread") as mock_postprocess:
            
            loop = asyncio.new_event_loop()
            results = loop.run_until_complete(check_downloads(db1))
            loop.close()

            # Import should not have triggered yet
            self.assertEqual(len(results), 0)
            mock_postprocess.assert_not_called()
            fake_client.pause_torrent.assert_not_called()

        # 2. Seeding time reached (70 minutes >= 60 minutes)
        t_seeding_done = TorrentInfo(
            hash="hash1",
            name="Test.Show.S01E01.mkv",
            progress=1.0,
            state="seeding",
            save_path="/downloads",
            size=1000,
            seeding_time=4200,  # 70 min
            ratio=1.2,
        )
        fake_client2 = FakeClient([t_seeding_done])
        fake_client2.pause_torrent = AsyncMock()
        fake_client2.get_torrent = AsyncMock(return_value=t_seeding_done)

        db2 = make_db()
        with patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.get_client", return_value=fake_client2), \
             patch("app.services.downloads_monitor._folder_and_template", return_value=("/media/series", "{Series Title}", "Season {season}")), \
             patch("app.services.downloads_monitor._resolve_torrent_files_and_path", return_value=("/downloads/Test.Show.S01E01.mkv", ["/downloads/Test.Show.S01E01.mkv"])), \
             patch("app.services.downloads_monitor._run_postprocess_in_thread", return_value=[{"status": "imported", "dest": "/media/series/Test Show/Test Show.mkv"}]) as mock_postprocess2:
            
            loop = asyncio.new_event_loop()
            results2 = loop.run_until_complete(check_downloads(db2))
            loop.close()

            # Torrent should be paused and imported
            fake_client2.pause_torrent.assert_called_once_with("hash1")
            self.assertEqual(len(results2), 1)

    def test_premature_import_prevented_at_99_97_percent(self):
        """Проверяет, что при 99.97% прогресса в состоянии downloading импорт НЕ запускается."""
        show = SimpleNamespace(id=1, title="Test Anime", content_type="anime", monitored=True)
        dc = SimpleNamespace(id=10, name="DC1", type="qbittorrent", enabled=True, seed_time_limit=None, seed_ratio_limit=None)
        ep = SimpleNamespace(
            id=101, show_id=1, season_number=2, episode_number=1,
            status="downloading", torrent_hash="hash-anime",
            download_client_id=10, download_progress=0.0,
        )

        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.all.side_effect = [
            [ep],   # downloading episodes
            [dc],   # active clients
        ]
        db_mock.get.return_value = show

        # Торрент ещё активно качается (99.97%, state='downloading')
        torrent = TorrentInfo(hash="hash-anime", name="Test Anime S2", progress=0.9997, state="downloading", save_path="/tmp/anime", size=1000)
        settings = SimpleNamespace(
            root_folder="", root_folder_anime="/media/anime",
            rename_template_anime="{Series Title} - S{season:00}E{episode:00} - {Episode Title}",
            season_folder_template_anime="Сезон {season}",
            download_folder_anime="",
        )

        with patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.get_client", return_value=FakeClient([torrent])), \
             patch("app.services.downloads_monitor._run_postprocess_in_thread") as mock_postprocess:
            results = asyncio.run(check_downloads(db_mock))
            # Прогресс обновляется до 0.9997, но импорт НЕ запускается
            self.assertEqual(ep.download_progress, 0.9997)
            self.assertEqual(ep.status, "downloading")
            self.assertFalse(mock_postprocess.called)
            self.assertEqual(results, [])

    def test_orphan_torrent_resets_episodes_to_wanted(self):
        """Проверяет, что если торрент был удален или отсутствует в клиенте, серии сбрасываются в wanted/unaired."""
        import datetime as dt
        show = SimpleNamespace(id=1, title="Test Anime", content_type="anime", monitored=True)
        dc = SimpleNamespace(id=10, name="DC1", type="qbittorrent", enabled=True)
        ep_aired = SimpleNamespace(
            id=101, show_id=1, season_number=2, episode_number=8,
            status="downloading", torrent_hash="hash-missing",
            download_client_id=10, download_progress=1.0,
            air_date=dt.datetime(2026, 8, 15),
        )
        ep_future = SimpleNamespace(
            id=102, show_id=1, season_number=2, episode_number=9,
            status="downloading", torrent_hash="hash-missing",
            download_client_id=10, download_progress=1.0,
            air_date=dt.datetime(2026, 9, 15),
        )

        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.all.side_effect = [
            [ep_aired, ep_future],   # downloading episodes
            [dc],                    # active clients
        ]

        # Клиент пустой (торрент отсутствует)
        settings = SimpleNamespace(root_folder="", download_folder_anime="")
        with patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.get_client", return_value=FakeClient([])), \
             patch("app.services.downloads_monitor._run_postprocess_in_thread") as mock_postprocess:
            results = asyncio.run(check_downloads(db_mock))
            self.assertEqual(ep_aired.status, "wanted")
            self.assertEqual(ep_aired.download_progress, 0.0)
            self.assertIsNone(ep_aired.torrent_hash)

            self.assertEqual(ep_future.status, "unaired")
            self.assertEqual(ep_future.download_progress, 0.0)
            self.assertIsNone(ep_future.torrent_hash)


if __name__ == "__main__":
    unittest.main()


