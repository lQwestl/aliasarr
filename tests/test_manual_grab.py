from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.models.db import Episode, EpisodeStatus, QualityProfile, Show, DownloadClient
    from app.api.indexers import grab_release, GrabRequest
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestManualGrab(unittest.TestCase):
    def test_grab_season_release_imports_quality_profile(self):
        """Проверяем, что grab_release импортирует QualityProfile и не падает с NameError."""
        if not HAS_DEPS:
            self.skipTest('FastAPI / dependencies not installed in host runner')

        mock_db = MagicMock()
        mock_show = Show(id=1, title="Test Show", content_type="series", quality_profile_id=10)
        mock_qp = QualityProfile(id=10, name="HD - 720p/1080p", allowed_qualities=["Bluray-1080p", "WEBDL-1080p", "DVDRip-480p"], upgrade_allowed=True)
        
        ep1 = Episode(id=101, show_id=1, season_number=5, episode_number=1, status=EpisodeStatus.DOWNLOADED, downloaded_quality="WEBDL-1080p", file_path="/media/ep1.mkv")
        ep2 = Episode(id=102, show_id=1, season_number=5, episode_number=2, status=EpisodeStatus.WANTED, downloaded_quality=None, file_path=None)

        def mock_get(model, pk):
            if model == Show:
                return mock_show
            if model == QualityProfile:
                return mock_qp
            return None

        mock_db.get.side_effect = mock_get
        mock_db.query.return_value.filter.return_value.all.return_value = [ep1, ep2]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = DownloadClient(id=1, name="Transmission", type="transmission", host="localhost", port=9091, enabled=True, is_default=True)

        req = GrabRequest(
            show_id=1,
            download_url="magnet:?xt=urn:btih:dummy",
            release_title="Test.Show.S05.DVDRip.x264",
            season=5,
        )

        bg_tasks = MagicMock()
        mock_user = MagicMock()

        with patch("app.api.indexers.get_client") as mock_get_client,              patch("app.api.indexers.get_or_create_settings") as mock_settings,              patch("app.api.indexers.notify_all", new_callable=AsyncMock):
            
            mock_client = AsyncMock()
            mock_client.add_torrent.return_value = "dummyhash12345"
            mock_get_client.return_value = mock_client
            mock_settings.return_value.download_folder_series = "/downloads"

            import asyncio
            res = asyncio.run(grab_release(req, bg_tasks, db=mock_db, current_user=mock_user))
            self.assertTrue(res["grabbed"])
            self.assertEqual(res["torrent_hash"], "dummyhash12345")
            self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADED)
            self.assertEqual(ep2.status, EpisodeStatus.DOWNLOADING)
            self.assertEqual(ep2.torrent_hash, "dummyhash12345")

    def test_grab_movie_release_binds_episode_and_no_bg_search(self):
        if not HAS_DEPS:
            self.skipTest('FastAPI / dependencies not installed in host runner')

        mock_db = MagicMock()
        mock_show = Show(id=2, title="Mayday", content_type="movie", quality_profile_id=10)
        movie_ep = Episode(id=201, show_id=2, season_number=1, episode_number=1, status=EpisodeStatus.WANTED, downloaded_quality=None, file_path=None)

        def mock_get(model, pk):
            if model == Show:
                return mock_show
            return None

        mock_db.get.side_effect = mock_get
        mock_db.query.return_value.filter.return_value.all.return_value = [movie_ep]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = DownloadClient(id=1, name="Transmission", type="transmission", host="localhost", port=9091, enabled=True, is_default=True)

        req = GrabRequest(
            show_id=2,
            download_url="magnet:?xt=urn:btih:moviehash",
            release_title="Mayday 2026 DUB, Sub WEBDL 1080p - RUSSIAN",
        )

        bg_tasks = MagicMock()
        mock_user = MagicMock()

        with patch("app.api.indexers.get_client") as mock_get_client, \
             patch("app.api.indexers.get_or_create_settings") as mock_settings, \
             patch("app.api.indexers.notify_all", new_callable=AsyncMock):

            mock_client = AsyncMock()
            mock_client.add_torrent.return_value = "moviehash888"
            mock_get_client.return_value = mock_client
            mock_settings.return_value.download_folder_movies = "/downloads/movies"

            import asyncio
            res = asyncio.run(grab_release(req, bg_tasks, db=mock_db, current_user=mock_user))
            self.assertTrue(res["grabbed"])
            self.assertEqual(res["torrent_hash"], "moviehash888")
            self.assertEqual(movie_ep.status, EpisodeStatus.DOWNLOADING)
            self.assertEqual(movie_ep.torrent_hash, "moviehash888")
            bg_tasks_added = [call.args[0] for call in bg_tasks.add_task.call_args_list]
            from app.api.indexers import _background_search_show
            self.assertNotIn(_background_search_show, bg_tasks_added)


if __name__ == "__main__":
    unittest.main()
